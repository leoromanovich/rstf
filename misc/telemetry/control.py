#!/usr/bin/env python3
"""Run one catalogued recipe without printing resolved secrets."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(os.getenv("RECIPE_ROOT", str(Path(__file__).resolve().parents[2]))).resolve()
CATALOG = json.loads((Path(__file__).parent / 'recipes.json').read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe', choices=[x['path'] for x in CATALOG])
    parser.add_argument('action', choices=['config', 'preflight', 'build', 'pull', 'up', 'restart', 'stop', 'down', 'logs', 'ps', 'trace-check'])
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--allow-local-build', action='store_true', help='Use only after the user explicitly approves this local image build')
    parser.add_argument('--cache', choices=['none', 'ram', 'ssd'], default='none')
    parser.add_argument('--experiment', action='store_true', help='Temporary restart=no override for all running services')
    parser.add_argument('--variant', choices=['base', 'mtp'], default='base')
    parser.add_argument('--model', help='Model ID from /v1/models; required for trace-check')
    args, extra = parser.parse_known_args()
    if str(ROOT).startswith('/nix/store/') and args.action != 'config' and not os.environ.get('RECIPE_ROOT'):
        parser.error('set RECIPE_ROOT to the writable checkout on the inference host; Nix store cannot hold runtime bind directories')
    recipe = next(x for x in CATALOG if x['path'] == args.recipe)
    directory = ROOT / args.recipe
    if args.cache != 'none' and recipe.get('cache_blocker'):
        parser.error(recipe['cache_blocker'])
    envfile = args.env_file or directory / ('.env.example' if args.action == 'config' else '.env')
    if not envfile.is_file():
        parser.error('copy .env.example to .env and configure keys and OTLP endpoint; paths and limits live in Compose')
    if args.action == 'preflight':
        from preflight import run
        run(directory, recipe, envfile, args.cache, args.variant)
        return
    env = os.environ.copy()
    binary = env.get('COMPOSE_BIN') or env.get('DSV4_COMPOSE_BIN') or env.get('VLLM_DSV4_COMPOSE_BIN')
    prefix = [binary] if binary else ['docker', 'compose']
    compose = prefix + ['--project-directory', str(directory), '--env-file', str(envfile), '-f', str(directory/'docker-compose.yaml')]
    if args.cache != 'none':
        compose += ['-f', str(directory / ('compose.' + args.cache + '.yaml'))]
    if args.variant == 'mtp':
        if 'gemma4-mtp' not in recipe['services']:
            parser.error('this recipe has no MTP variant')
        compose += ['-f', str(directory/'compose.mtp.yaml'), '--profile', 'mtp']
    # Keep this context alive until Compose exits; override files stay local.
    temporary = tempfile.TemporaryDirectory(prefix='recipe-experiment-')
    if args.experiment:
        config = json.loads(subprocess.check_output(compose + ['config', '--format', 'json'], env=env))
        override = Path(temporary.name)/'restart.json'
        override.write_text(json.dumps({'services': {n: {'restart': 'no'} for n in config['services']}}))
        compose += ['-f', str(override)]
    if args.action == 'config':
        subprocess.run(compose + ['config', '--quiet'], env=env, check=True)
        print('Compose configuration valid')
        return
    if args.action in {'up','restart','stop','down'} and env.get('RECIPE_CONFIRM') != 'mutate-inference':
        parser.error('set RECIPE_CONFIRM=mutate-inference for runtime changes')
    if args.action == 'build' and not args.allow_local_build:
        parser.error('local image builds require an explicit user decision; then pass --allow-local-build')
    if args.action == 'up' and any(value.split('=', 1)[0] in {'--build', '--no-build'} for value in extra):
        parser.error('up never builds images; use build --allow-local-build after explicit approval')
    if args.action == 'up':
        subprocess.run(compose + ['config', '--quiet'], env=env, check=True)
        if args.variant == 'mtp':
            selected = ['gemma4-mtp', 'smg', 'otel-collector', 'jaeger']
        elif 'gemma4-mtp' in recipe['services']:
            selected = ['gemma4', 'smg', 'otel-collector', 'jaeger']
        else:
            selected = []
        command = ['up', '-d', '--no-build'] + extra + selected
    elif args.action == 'trace-check':
        if not args.model:
            parser.error('--model is required for trace-check')
        # Resolve only in memory to obtain actual internal addresses/ports.
        config = json.loads(subprocess.check_output(compose + ['config', '--format', 'json'], env=env))
        smg = config['services']['smg']
        arguments = smg.get('command', [])
        port = arguments[arguments.index('--port')+1]
        host = arguments[arguments.index('--host')+1]
        base = 'http://' + ('127.0.0.1' if host=='0.0.0.0' else host) + ':' + port
        collector = config['services']['otel-collector']['environment']
        http = 'http://otel-collector:4318/v1/traces'
        command = ['exec', '-T', '-e', 'TRACE_API_KEY', 'smg', 'python3', '/opt/telemetry/trace_probe.py', '--engine', recipe['engine'], '--model', args.model, '--base-url', base, '--otlp-http-endpoint', http]
        if recipe['mode'] == 'external' and '--jaeger-url' not in extra:
            command += ['--no-verify']
        command += extra
    else:
        command = [args.action] + extra
        if args.action in {'restart', 'stop'} and 'gemma4-mtp' in recipe['services']:
            command += ['gemma4-mtp' if args.variant == 'mtp' else 'gemma4', 'smg', 'otel-collector', 'jaeger']
    subprocess.run(compose + command, env=env, check=True)


if __name__ == '__main__':
    main()
