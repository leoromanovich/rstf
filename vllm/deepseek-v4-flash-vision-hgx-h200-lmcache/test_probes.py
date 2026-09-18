"""Offline fixtures for probe false-positive and streaming failure cases."""
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from acceptance import answer_matches, cache_evidence, delta_metrics, fit_prompt, parse_metrics
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "misc/telemetry"))
from preflight import check_storage
from smoke import collect_stream


def sse(events, done=True):
    lines = [b": keepalive\n\n"]
    lines += [b"data: " + json.dumps(event).encode() + b"\n\n" for event in events]
    if done:
        lines.append(b"data: [DONE]\n\n")
    return io.BytesIO(b"".join(lines))


def choice(delta, finish=None):
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


class StreamFixtures(unittest.TestCase):
    def test_fragmented_tool_arguments_and_trailing_usage(self):
        events = [choice({"role": "assistant"}),
                  choice({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                           "function": {"name": "lookup_build", "arguments": ""}}]}),
                  choice({"tool_calls": [{"index": 0, "function": {"arguments": '{"id":"te'}}]}),
                  choice({"tool_calls": [{"index": 0, "function": {"arguments": 'st-42"}'}}]}),
                  choice({}, "tool_calls"), {"choices": [], "usage": {"prompt_tokens": 93}}]
        message, stats = collect_stream(sse(events), time.monotonic())
        call = message["tool_calls"][0]
        self.assertEqual(call["id"], "call_1")
        self.assertEqual(json.loads(call["function"]["arguments"]), {"id": "test-42"})
        self.assertEqual(stats["usage"]["prompt_tokens"], 93)
        self.assertIsNotNone(stats["ttft_seconds"])

    def test_truncation_error_and_missing_finish_are_rejected(self):
        for events, done in [([choice({"content": "42"}, "stop")], False),
                             ([choice({"content": "42"}, "length")], True),
                             ([choice({"content": "42"})], True),
                             ([{"error": {"message": "synthetic failure"}}], True)]:
            with self.subTest(events=events, done=done), self.assertRaises(AssertionError):
                collect_stream(sse(events, done), time.monotonic())


class StorageFixtures(unittest.TestCase):
    def test_telemetry_file_mounts_do_not_require_cache_disk_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "trace_probe.py"
            script.write_text("# synthetic fixture\n")
            config = {"services": {
                "smg": {"volumes": [{"type": "bind", "source": str(script), "target": "/probe.py", "read_only": True}]},
                "lmcache": {"volumes": [{"type": "bind", "source": str(root), "target": "/kv-cache"}]},
            }}
            with patch("preflight.shutil.disk_usage", return_value=SimpleNamespace(free=4_000_000_000_000)) as disk:
                check_storage(config, "vllm/deepseek-v4-flash-vision-hgx-h200-lmcache")
                disk.assert_called_once_with(root)
            with patch("preflight.shutil.disk_usage", return_value=SimpleNamespace(free=1_000_000_000)):
                with self.assertRaisesRegex(RuntimeError, "insufficient free storage"):
                    check_storage(config, "vllm/deepseek-v4-flash-vision-hgx-h200-lmcache")

    def test_missing_telemetry_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"services": {"otel-collector": {
                "volumes": [{"type": "bind", "source": str(Path(tmp) / "missing.yaml"), "target": "/config.yaml"}],
            }}}
            with self.assertRaisesRegex(RuntimeError, "missing service bind source"):
                check_storage(config, "vllm/deepseek-v4-flash-vision-hgx-h200-lmcache")


class CacheFixtures(unittest.TestCase):
    def test_base_stage_has_no_lmcache_dependency(self):
        from acceptance import main
        expected = {"START": "a", "MIDDLE": "b", "END": "c"}
        with patch("sys.argv", ["acceptance", "--run-id", "fixture"]), \
             patch("acceptance.fit_prompt", return_value=([], expected, 384000)), \
             patch("acceptance.stream_chat", side_effect=lambda *a, **kw: (
                 {"content": json.dumps(expected)}, {"usage": {"prompt_tokens": 384000}, "ttft_seconds": 1}
             )) as chat, patch("acceptance.metrics") as metrics, patch("sys.stdout", new_callable=io.StringIO):
            main()
            metrics.assert_not_called()
            self.assertEqual([c.kwargs["rank"] for c in chat.call_args_list], [0, 0, 1, 7])


    def test_aggregate_counters_without_retaining_labels(self):
        body = ('# HELP ignored\n'
                'lmcache_mp_num_chunks_loaded_total{worker_id="0",cache_salt="a"} 12\n'
                'lmcache_mp_num_chunks_loaded_total{worker_id="7",cache_salt="b"} 4\n'
                'unrelated_metric{prompt="private"} 7\n')
        self.assertEqual(parse_metrics(body), {"lmcache_mp_num_chunks_loaded_total": 16})

    def test_finished_transfer_or_l2_alone_does_not_prove_restore(self):
        self.assertFalse(cache_evidence({"lmcache_mp_num_finished_retrieves_total": 1})["ram_to_gpu_observed"])
        evidence = cache_evidence({"lmcache_mp_l2_load_completed_requests_total": 1})
        self.assertTrue(evidence["ssd_to_ram_observed"])
        self.assertFalse(evidence["ram_to_gpu_observed"])
        self.assertTrue(cache_evidence({"lmcache_mp_num_chunks_loaded_total": 3})["ram_to_gpu_observed"])

    def test_lazy_counter_creation_and_server_reset(self):
        self.assertEqual(delta_metrics({}, {"new": 4}), {"new": 4})
        for after in ({"loaded": 2}, {}):
            with self.subTest(after=after), self.assertRaises(AssertionError):
                delta_metrics({"loaded": 3}, after)

    def test_three_markers_required(self):
        expected = {"START": "abc", "MIDDLE": "def", "END": "123"}
        self.assertTrue(answer_matches(json.dumps(expected), expected))
        self.assertTrue(answer_matches("```json\n" + json.dumps(expected) + "\n```", expected))
        self.assertFalse(answer_matches('{"END":"123"}', expected))
        self.assertFalse(answer_matches("unstructured " + json.dumps(expected), expected))

    def test_prompt_fits_counted_budget_with_template_overhead(self):
        def count(messages, timeout):
            return 113 + 19 * messages[0]["content"].count("// fixture ")
        with patch("acceptance.token_count", side_effect=count):
            messages, expected, size = fit_prompt(32768, "fixture-run", 15)
        self.assertLessEqual(size, 32768)
        self.assertLess(32768 - size, 19)
        self.assertTrue(all(value in messages[0]["content"] for value in expected.values()))


if __name__ == "__main__":
    unittest.main()
