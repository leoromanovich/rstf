"""Resolved recipe contracts, including model topology and cache variants."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[1]/'misc/telemetry'))
from contract import main
if __name__ == '__main__':
    main(ROOT.parents[1], 'vllm/deepseek-v4-flash-vision-hgx-h200-lmcache')
