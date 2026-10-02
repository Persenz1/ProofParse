"""API thinking, measurements and answer-cache compatibility; no network calls."""
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from proofparse.config import ApiConfig, Config, load
from proofparse.stages.escalate import _ask


class ApiAdjudicationTests(unittest.TestCase):
    def test_disabled_thinking_and_actual_response_metrics(self):
        task = {"task_id": "paper/block", "input_hash": "snapshot", "kind": "inline_math",
                "context_text": None, "candidates": [], "differences": [], "image": "crop.png"}
        cfg = Config(api=ApiConfig(base_url="https://example.test/v1", model="test-model"))
        raw = {"choices": [{"message": {"content": json.dumps({"paper/block": {"choice": "custom", "latex": "x"}}),
                                        "reasoning_content": ""}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12,
                         "completion_tokens_details": {"reasoning_tokens": 0}}}
        response = io.BytesIO(json.dumps(raw).encode())
        with patch.dict("os.environ", {"PROOFPARSE_API_KEY": "test-secret"}), \
             patch.object(Path, "is_file", return_value=False), \
             patch.object(Path, "read_bytes", return_value=b"crop"), \
             patch("proofparse.stages.escalate.urllib.request.urlopen", return_value=response) as request, \
             patch("proofparse.stages.escalate.write_json") as save:
            answer = _ask(cfg, task, Path("answers"), metrics_dir=Path("metrics"))
        body = json.loads(request.call_args.args[0].data)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(answer, {"choice": "custom", "latex": "x", "input_hash": "snapshot"})
        self.assertEqual(save.call_args_list[0].args[1], answer)
        metric = save.call_args_list[1].args[1]
        self.assertTrue(metric["parsed_json"])
        self.assertTrue(metric["reasoning_content_empty"])
        self.assertEqual(metric["reasoning_tokens"], 0)
        self.assertEqual(metric["usage"], raw["usage"])
        self.assertEqual(metric["finish_reason"], "stop")
        self.assertGreaterEqual(metric["seconds"], 0)
        self.assertNotIn("test-secret", json.dumps(metric))

    def test_existing_plain_answer_cache_remains_usable(self):
        answer = {"choice": "open", "input_hash": "snapshot"}
        task = {"task_id": "paper/block", "input_hash": "snapshot"}
        with patch.object(Path, "is_file", return_value=True), \
             patch("proofparse.stages.escalate.read_json", return_value=answer), \
             patch("proofparse.stages.escalate.urllib.request.urlopen") as request:
            self.assertEqual(_ask(Config(), task, Path("answers")), answer)
        request.assert_not_called()

    def test_thinking_setting_loads_from_toml(self):
        with patch.object(Path, "read_text", return_value='[escalation.api]\nthinking = "enabled"\n'):
            self.assertEqual(load(Path("config.toml")).api.thinking, "enabled")


if __name__ == "__main__":
    unittest.main()
