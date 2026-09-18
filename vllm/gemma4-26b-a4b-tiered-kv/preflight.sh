#!/usr/bin/env bash
set -euo pipefail
recipe_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$recipe_dir/../../misc/telemetry/control.py" vllm/gemma4-26b-a4b-tiered-kv preflight \
  --env-file "${1:-$recipe_dir/.env}" --variant "${2:-base}" --cache "${RECIPE_CACHE:-none}"
