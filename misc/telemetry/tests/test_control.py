#!/usr/bin/env python3
"""Exercise the lifecycle build boundary without running Docker."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CONTROL = Path(__file__).resolve().parents[1] / "control.py"
ROOT = CONTROL.parents[2]
RECIPE = "vllm/kimi-k2.6-tp8"


class BuildBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.log = Path(self.temp.name) / "calls.jsonl"
        self.fake = Path(self.temp.name) / "compose"
        self.fake.write_text(
            "#!" + sys.executable + "\n"
            "import json, os, sys, pathlib\n"
            "if '--format' in sys.argv: print(json.dumps({'services':{'vllm':{},'smg':{},'otel-collector':{}}}))\n"
            "for arg in sys.argv:\n"
            "    if arg.endswith('restart.json') and pathlib.Path(arg).exists():\n"
            "        pathlib.Path(os.environ['COMPOSE_TEST_LOG']+'.override').write_text(pathlib.Path(arg).read_text())\n"
            "with open(os.environ['COMPOSE_TEST_LOG'], 'a') as stream:\n"
            "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        )
        self.fake.chmod(0o755)
        self.env = os.environ | {
            "RECIPE_ROOT": str(ROOT),
            "COMPOSE_BIN": str(self.fake),
            "COMPOSE_TEST_LOG": str(self.log),
            "RECIPE_CONFIRM": "mutate-inference",
        }

    def run_control(self, action, *extra):
        return subprocess.run(
            [sys.executable, str(CONTROL), RECIPE, action,
             "--env-file", str(ROOT / RECIPE / ".env.example"), *extra],
            env=self.env, capture_output=True, text=True,
        )

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_up_validates_then_forbids_build(self):
        result = self.run_control("up")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][-2:], ["config", "--quiet"])
        self.assertEqual(calls[1][-3:], ["up", "-d", "--no-build"])

    def test_up_rejects_build_overrides(self):
        for option in ("--build", "--build=true", "--no-build=false"):
            with self.subTest(option=option):
                result = self.run_control("up", option)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("up never builds", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_build_requires_explicit_opt_in(self):
        result = self.run_control("build")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit user decision", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_explicit_build_is_separate_from_up(self):
        result = self.run_control("build", "--allow-local-build", "vllm")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[0][-2:], ["build", "vllm"])


    def test_cache_overlays_are_independent(self):
        for tier in ('ram', 'ssd'):
            result = self.run_control('config', '--cache', tier)
            self.assertEqual(result.returncode, 0, result.stderr)
            files = [arg for arg in self.calls()[-1] if arg.endswith('.yaml')]
            self.assertEqual([Path(p).name for p in files], ['docker-compose.yaml', 'compose.'+tier+'.yaml'])

    def test_unverified_lmcache_tier_is_rejected_before_compose(self):
        result = subprocess.run([sys.executable, str(CONTROL),
            'vllm/deepseek-v4-flash-vision-hgx-h200-lmcache', 'config', '--cache', 'ram'],
            env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('compatibility', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_experiment_disables_restart_for_every_service(self):
        result = self.run_control('config', '--experiment')
        self.assertEqual(result.returncode, 0, result.stderr)
        override = json.loads(Path(str(self.log)+'.override').read_text())
        self.assertEqual(set(override['services']), {'vllm','smg','otel-collector'})
        self.assertTrue(all(service['restart']=='no' for service in override['services'].values()))


    def test_mtp_restart_selects_only_the_active_gpu_service(self):
        recipe = 'vllm/gemma4-26b-a4b-tiered-kv'
        result = subprocess.run([sys.executable, str(CONTROL), recipe, 'restart',
            '--variant', 'mtp', '--env-file', str(ROOT/recipe/'.env.example')],
            env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[0][-5:], ['restart','gemma4-mtp','smg','otel-collector','jaeger'])


if __name__ == "__main__":
    unittest.main()
