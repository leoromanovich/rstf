#!/usr/bin/env python3
"""Static contract checks for base/RAM/SSD recipes; never starts Docker."""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / 'misc/telemetry/recipes.json').read_text())


def compose_args(directory, env_file=None, cache='none', variant='base'):
    binary = os.environ.get('COMPOSE_BIN') or os.environ.get('DSV4_COMPOSE_BIN') or os.environ.get('VLLM_DSV4_COMPOSE_BIN')
    command = ([binary] if binary else ['docker', 'compose'])
    command += ['--project-directory', str(directory), '--env-file', str(env_file or directory/'.env.example'), '-f', str(directory/'docker-compose.yaml')]
    if cache != 'none':
        command += ['-f', str(directory/f'compose.{cache}.yaml')]
    if variant == 'mtp':
        command += ['-f', str(directory/'compose.mtp.yaml'), '--profile', 'mtp']
    return command


def render(directory, env_file=None, cache='none', variant='base'):
    command = compose_args(directory, env_file, cache, variant)
    subprocess.run(command + ['config', '--quiet'], check=True, capture_output=True)
    return json.loads(subprocess.check_output(command + ['config', '--format', 'json'], stderr=subprocess.PIPE))


def argv(service):
    return (service.get('entrypoint') or []) + (service.get('command') or [])


def options(service):
    result = {}
    for arg in argv(service):
        if arg.startswith('--'):
            key, sep, value = arg.partition('=')
            assert key not in result, f'duplicate flag: {key}'
            result[key] = value if sep else None
        elif 'key' in locals() and result[key] is None:
            result[key] = arg
    return result


def duplicate_keys(node):
    import yaml
    if isinstance(node, yaml.MappingNode):
        keys = [k.value for k, _ in node.value]
        assert len(keys) == len(set(keys)), 'duplicate YAML key'
        for _, child in node.value:
            duplicate_keys(child)
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            duplicate_keys(child)


def validate_recipe(root, recipe):
    directory = root / recipe['path']
    base = render(directory)
    variants = ['base', 'mtp'] if 'gemma4-mtp' in recipe['services'] else ['base']
    tiers = ['none'] if recipe.get('cache_blocker') else ['none', 'ram', 'ssd']
    count = 0
    for variant in variants:
        baseline = render(directory, variant=variant)
        for tier in tiers:
            config = render(directory, cache=tier, variant=variant)
            services = config['services']
            for name, service in services.items():
                assert 'build' not in service and not service['image'].startswith('local/'), name
                assert '@sha256:' in service['image'], f'unpinned image: {name}'
                assert service.get('network_mode') != 'host', name
                assert service.get('restart') == ('no' if name == 'download' else 'unless-stopped'), name
                for field in ['entrypoint', 'command']:
                    args = service.get(field) or []
                    assert isinstance(args, list), (name, field)
                    assert all(a == a.strip() and '\n' not in a and '\\' != a for a in args), (name, field)
                    assert not any(a.startswith('--') and ' --' in a for a in args), (name, field)
                options(service)
            smg = services['smg']; so = options(smg)
            worker = 'gemma4-mtp' if variant == 'mtp' else recipe['services'][0]
            assert so['--port'] == '30001' and so['--prometheus-port'] == '9234'
            assert so['--worker-urls'] == f'http://{worker}:30000'
            assert [(p['published'], p['target']) for p in smg['ports']] == [('30001', 30001)]
            collector = services['otel-collector']
            assert [(p['published'], p['target']) for p in collector['ports']] == [('9234', 9234)]
            assert collector['environment']['ENGINE_METRICS_TARGET'] == f'{worker}:30000'
            assert int(collector['mem_limit']) <= 512 * 1024**2
            for name in ('smg', 'otel-collector'):
                assert not services[name].get('deploy', {}).get('resources', {}).get('reservations', {}).get('devices')
            if recipe['mode'] == 'local':
                assert 'jaeger' in services
            else:
                assert not {'jaeger', 'open-webui', 'litellm'} & services.keys()
            for name in recipe['services']:
                if name not in services:
                    continue
                s = services[name]; o = options(s)
                assert not s.get('ports') and o['--port'] == '30000' and o['--host'] == '0.0.0.0'
                assert o['--otlp-traces-endpoint'] == 'otel-collector:4317'
                path = recipe['path']
                if 'glm-' in path:
                    assert o['--tp-size'] == '8' and o['--dp-size'] == '8'
                    assert '--enable-dp-attention' in o and '--speculative-algorithm' not in o
                if 'qwen3-8b' in path:
                    assert o['--tp-size'] == '2' and o['--dp-size'] == '2'
                if 'deepseek' in path:
                    assert o['--revision'] == '6821d6ad3681a4b137b066b76094fa82ebd0a380'
                    if recipe['engine'] == 'sglang':
                        assert (o['--tp-size'], o['--dp-size'], o['--ep-size']) == ('8','8','1')
                        assert o['--moe-a2a-backend'] == 'none' and o['--page-size'] == '256'
                        assert o['--max-running-requests'] == '256' and o['--max-queued-requests'] == '64'
                        assert '--hicache-size' not in o and '--quantization' not in o
                        if tier != 'none':
                            assert o['--hicache-ratio'] == '1.25'
                            assert o['--hicache-io-backend'] == 'direct'
                    else:
                        assert o['--tensor-parallel-size'] == '1' and o['--data-parallel-size'] == '8'
                        assert o['--max-model-len'] == '400000'
                        assert '--no-disable-hybrid-kv-cache-manager' in o
                        assert '--kv-transfer-config' not in o
                if 'gemma' in path:
                    assert o['--attention-backend'] == 'TRITON_ATTN' and o['--dtype'] == 'bfloat16'
                    diffusion = 'diffusiongemma' in path
                    assert o['--max-num-seqs'] == ('4' if diffusion else '24')
                    assert o['--max-model-len'] == ('65536' if diffusion else '131072')
                    assert o['--max-num-batched-tokens'] == '8192'
                    assert s['environment']['HF_HUB_OFFLINE'] == '1'
                    assert any(v['target']=='/models' and v['read_only'] for v in s['volumes'])
                if recipe['engine'] == 'vllm' and 'deepseek' not in path:
                    assert o['--performance-mode'] == 'throughput'
                defaults = json.loads(o['--default-chat-template-kwargs'])
                assert defaults.get('enable_thinking', defaults.get('thinking')) is True
                if 'qwen3.8' in recipe['path']:
                    assert defaults['reasoning_effort'] == 'medium'
                for k, value in o.items():
                    if value and value.startswith('{'):
                        json.loads(value)
                if tier == 'none':
                    assert '--enable-hierarchical-cache' not in o
                    assert not any(k.startswith(('--hicache-', '--kv-offload', '--kv-transfer')) for k in o)
                    assert not any(n.startswith(('mooncake', 'lmcache')) for n in services)
                elif recipe['engine'] == 'sglang':
                    assert '--enable-hierarchical-cache' in o
                    assert ('--hicache-storage-backend' in o) == (tier == 'ssd')
                    assert '--hicache-size' in o or '--hicache-ratio' in o
                else:
                    assert o['--kv-offloading-backend'] == 'native'
                    assert int(o['--kv-offloading-size']) > 0
                    assert s['ipc'] == 'private'
                    assert s['environment']['PYTHONHASHSEED'] == '0'
                    if tier == 'ssd':
                        cfg = json.loads(o['--kv-transfer-config'])['kv_connector_extra_config']
                        assert cfg['spec_name'] == 'TieringOffloadingSpec'
                        assert cfg['secondary_tiers'][0]['type'] == 'fs'
                    else:
                        assert '--kv-transfer-config' not in o
                # Engine base argv must survive both independent overlays unchanged.
                assert s['entrypoint'] == baseline['services'][name]['entrypoint']
            count += 1
    if recipe.get('cache_blocker'):
        assert not (directory/'compose.ram.yaml').exists()
        assert not (directory/'compose.ssd.yaml').exists()
        assert 'BLOCKED' in (directory/'README.md').read_text()
    env = (directory/'.env.example').read_text()
    keys = re.findall(r'^([A-Z_]+)=', env, re.M)
    assert all(k.endswith(('API_KEY', 'TOKEN', 'AUTHORIZATION')) or k == 'OTLP_UPSTREAM_ENDPOINT' for k in keys)
    return count


def main(root=ROOT, selected=None):
    import yaml
    catalog = json.loads((root/'misc/telemetry/recipes.json').read_text())
    if selected:
        catalog = [r for r in catalog if r['path'] == selected]
        assert catalog, selected
    for path in root.rglob('*.py'):
        ast.parse(path.read_text(), filename=str(path))
    for path in root.rglob('*.yaml'):
        duplicate_keys(yaml.compose(path.read_text()))
    count = 0
    for recipe in catalog:
        count += validate_recipe(root, recipe)
    print(f'OK: {len(catalog)} recipes, {count} resolved variants; images, ports, argv, reasoning, cache tiers, restart')
    return count


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT)
