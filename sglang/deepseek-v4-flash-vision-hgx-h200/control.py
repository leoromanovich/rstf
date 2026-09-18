"""Compatibility entry point for the shared, tier-aware Nix lifecycle."""
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parent
shared=ROOT.parents[1]/'misc/telemetry'
if os.environ.get('DSV4_CONFIRM')=='mutate-dsv4-vision-h200':
    os.environ['RECIPE_CONFIRM']='mutate-inference'
action=sys.argv[1] if len(sys.argv)>1 else 'config'
extra=sys.argv[2:]
env_file=Path(os.environ.get('DSV4_ENV_FILE',str(ROOT/('.env.example' if action=='config' else '.env'))))
if action=='smoke':
    sys.path.insert(0,str(shared))
    from contract import render
    config=render(ROOT,env_file)
    os.environ['SGLANG_API_KEY']=config['services']['sglang']['environment']['SGLANG_API_KEY']
    subprocess.run([sys.executable,str(ROOT/'smoke.py'),*extra],check=True)
else:
    subprocess.run([sys.executable,str(shared/'control.py'),'sglang/deepseek-v4-flash-vision-hgx-h200',action,'--env-file',str(env_file),'--cache',os.environ.get('RECIPE_CACHE','none'),*extra],check=True)
