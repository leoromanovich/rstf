#!/usr/bin/env python3
"""Nix check entry point: lifecycle tests and resolved recipe contracts."""
from pathlib import Path
import subprocess
import sys
from contract import main

if __name__ == '__main__':
    root = Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[2]
    subprocess.run([sys.executable, str(root/'misc/telemetry/tests/test_control.py')], check=True)
    subprocess.run([sys.executable, str(root/"vllm/deepseek-v4-flash-vision-hgx-h200-lmcache/test_probes.py")], check=True)
    main(root)
