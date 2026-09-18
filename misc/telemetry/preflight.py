#!/usr/bin/env python3
"""Read-only host admission checks against the selected resolved Compose tier."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from contract import render, options


def model_check(path, recipe, args, variant):
    required = ['config.json', 'tokenizer_config.json']
    if 'gemma' in recipe:
        required += ['chat_template.jinja', 'generation_config.json', 'processor_config.json', 'tokenizer.json', 'model.safetensors.index.json']
    for name in required:
        if not (path/name).is_file():
            raise RuntimeError('missing model file: ' + str(path/name))
    config = json.loads((path/'config.json').read_text())
    if 'diffusiongemma' in recipe:
        quant = config.get('quantization_config', {})
        assert config['model_type'] == 'diffusion_gemma'
        assert quant.get('quant_method') == 'compressed-tensors' and quant.get('format') == 'int-quantized'
    elif 'gemma4' in recipe:
        assert config['model_type'] == 'gemma4'
        assert 'Gemma4ForConditionalGeneration' in config.get('architectures', [])
        text = config['text_config']
        assert text['enable_moe_block'] and text['num_experts'] == 128 and text['top_k_experts'] == 8
        assert not config.get('quantization_config') and config.get('dtype') in ('bf16','bfloat16')
        assert int(text['max_position_embeddings']) >= int(args['--max-model-len'])
    index = path/'model.safetensors.index.json'
    if index.exists():
        shards = set(json.loads(index.read_text())['weight_map'].values())
        assert shards and all((path/name).is_file() for name in shards), 'missing weight shards'
        if 'gemma4' in recipe:
            assert sum((path/name).stat().st_size for name in shards) >= 45*1024**3
    elif not list(path.glob('*.safetensors')):
        raise RuntimeError('missing weights: ' + str(path))


def check_storage(config, recipe):
    # Capacity applies only to model/cache directories in the selected tier.
    for svc in config['services'].values():
        for mount in svc.get('volumes', []):
            if mount['type'] != 'bind':
                continue
            path = Path(mount['source'])
            if not path.exists():
                raise RuntimeError('missing service bind source: ' + str(path))
            if not mount.get('read_only') and not os.access(path, os.W_OK):
                raise RuntimeError('bind path must be writable: ' + str(path))
            minimum = 0
            if mount['target'] in ('/kv-cache', '/hicache', '/mooncake_cache'):
                minimum = 20 * 1024**3 if 'qwen3.8' in recipe else 512 * 1024**3
            elif mount['target'] == '/models' and 'deepseek' in recipe:
                minimum = 500_000_000_000
            if minimum:
                if not path.is_dir() or shutil.disk_usage(path).free < minimum:
                    raise RuntimeError('insufficient free storage: ' + str(path))


def run(directory, recipe, env_file, cache='none', variant='base'):
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise RuntimeError('preflight requires the Linux x86_64 inference host')
    config = render(directory, env_file, cache, variant)
    name = 'gemma4-mtp' if variant == 'mtp' else recipe['services'][0]
    service = config['services'][name]; args = options(service)
    key = 'SGLANG_API_KEY' if recipe['engine']=='sglang' else 'VLLM_API_KEY'
    value = service['environment'].get(key, '')
    if not value or value.startswith('replace-with-'):
        raise RuntimeError('configure the inference API key')
    if '--admin-api-key' in args and (args['--admin-api-key'].startswith('replace-with-') or args['--admin-api-key']==value):
        raise RuntimeError('configure a distinct admin key')
    rows = subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader,nounits'], text=True).strip().splitlines()
    devices = service.get('deploy',{}).get('resources',{}).get('reservations',{}).get('devices',[])
    needed = devices[0].get('count',1) if devices else 1
    if isinstance(needed,int) and needed>0 and len(rows)<needed:
        raise RuntimeError('insufficient GPU count')
    if 'deepseek' in recipe['path']:
        assert len(rows)==8 and all('H200' in row and float(row.split(',')[1])>=130000 for row in rows), 'expected 8 x H200'
        assert all(int(row.split(',')[2].strip().split('.')[0])>=580 for row in rows), 'R580+ driver required'
    if 'gemma' in recipe['path']:
        assert 'A100' in rows[0] and float(rows[0].split(',')[1])>=79000, 'expected A100 80 GB'
        driver=tuple(int(x) for x in rows[0].split(',')[2].strip().split('.'))
        assert driver >= (525,60,13), 'CUDA 12 baseline driver required'
        assert driver >= (575,51,3) or service['environment'].get('VLLM_ENABLE_CUDA_COMPATIBILITY')=='1'
    check_storage(config, recipe['path'])
    mounts={v['target']:Path(v['source']) for v in service.get('volumes',[]) if v['type']=='bind'}
    model=args.get('--model-path') or args.get('--model')
    if not model:
        tokens=service.get('entrypoint',[])
        model=next((v for v in tokens if v.startswith('/models/')),None)
    if model and model.startswith('/'):
        parent=next((target for target in sorted(mounts,key=len,reverse=True) if model==target or model.startswith(target+'/')),None)
        assert parent, 'model path must be mounted'
        model_check(mounts[parent]/model[len(parent):].lstrip('/'),recipe['path'],args,variant)
    if variant=='mtp':
        path=mounts['/assistant-model']; c=json.loads((path/'config.json').read_text())
        assert c['model_type']=='gemma4_assistant'
        assert (path/'model.safetensors').stat().st_size>=700*1024**2
    available=next(int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    if '--kv-offloading-size' in args:
        # Native CPU budget is shared by TP workers and independently allocated per DP replica.
        budget=int(args['--kv-offloading-size'])*int(args.get('--data-parallel-size') or 1)*1024**3
        assert available>=budget+32*1024**3, 'insufficient host RAM for selected cache tier'
        assert int(service['shm_size'])>=budget+16*1024**3, 'private shared memory too small'
    if '--hicache-size' in args:
        budget=int(args['--hicache-size'])*int(args.get('--tp-size') or args.get('--tp') or 1)*1024**3
        assert available>=budget+32*1024**3, 'insufficient host RAM for HiCache ranks'
    if '--hicache-ratio' in args and 'deepseek' in recipe['path']:
        assert available>=1_500_000_000_000, 'DSV4 ratio tier requires 1.5 TB available RAM'
    subprocess.run(['docker','image','inspect',service['image']],check=True,stdout=subprocess.DEVNULL)
    print('OK: selected Compose tier, credentials, local image, GPU, mounts, model and cache capacity')
    print('GPU startup, reasoning output, throughput and cold/warm cache restore still require acceptance tests.')
