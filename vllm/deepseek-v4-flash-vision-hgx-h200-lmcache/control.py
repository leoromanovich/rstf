"""Compatibility entry point for the shared, tier-aware Nix lifecycle."""
import os
from pathlib import Path
import subprocess
import sys

RECIPE = 'vllm/deepseek-v4-flash-vision-hgx-h200-lmcache'
SOURCE = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get('RECIPE_ROOT', str(SOURCE))).resolve() / RECIPE
SHARED = SOURCE / 'misc/telemetry'


def main():
    if os.environ.get('VLLM_DSV4_CONFIRM') == 'mutate-vllm-dsv4-h200':
        os.environ['RECIPE_CONFIRM'] = 'mutate-inference'
    action = sys.argv[1] if len(sys.argv) > 1 else 'config'
    extra = sys.argv[2:]
    env_file = Path(os.environ.get('VLLM_DSV4_ENV_FILE', str(ROOT / ('.env.example' if action == 'config' else '.env'))))
    if action in {'smoke', 'acceptance'}:
        if str(ROOT).startswith('/nix/store/'):
            raise SystemExit('set RECIPE_ROOT to the checkout on the inference host')
        sys.path.insert(0, str(SHARED))
        from contract import compose_args
        subprocess.run(compose_args(ROOT, env_file) + [
            'exec', '-T', '-e', 'VLLM_DSV4_BASE_URL=http://127.0.0.1:30000/v1',
            'vllm', 'python3', f'/opt/recipe/{action}.py', *extra,
        ], check=True)
    else:
        subprocess.run([sys.executable, str(SHARED / 'control.py'), RECIPE, action,
                        '--env-file', str(env_file), '--cache', os.environ.get('RECIPE_CACHE', 'none'), *extra], check=True)


if __name__ == '__main__':
    main()
