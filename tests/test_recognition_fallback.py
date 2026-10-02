"""A costly recognizer should see only formulas the first pair cannot settle."""
import unittest
from pathlib import Path
from unittest.mock import patch

from proofparse import ir, pipeline
from proofparse.config import Config
from proofparse.engines.runner import RunInfo
from proofparse.ir import Block, Candidate, Document, Page
from proofparse.stages import recognize


class FallbackTests(unittest.TestCase):
    def test_only_conflicts_reach_fallback_and_stale_votes_are_removed(self):
        first = Block("b0", 0, [10, 10, 20, 20], ir.DISPLAY_MATH)
        second = Block("b1", 0, [30, 10, 40, 20], ir.DISPLAY_MATH,
                       candidates=[Candidate("xiaomi_ocr", "qwen3.5-ocr", "z")])
        doc = Document(pages=[Page(0, 200, 300)], blocks=[first, second])
        paper = pipeline.Paper("paper", Path("output/fallback-test"), doc)
        cfg = Config(formula=["pp_formulanet_plus_m", "paddleocr_vl"],
                     formula_fallback=["xiaomi_ocr"])
        calls = []

        def run(cfg, name, task, items, work, **kwargs):
            calls.append((name, [item["id"] for item in items]))
            values = {"pp_formulanet_plus_m": ["x", "y"], "paddleocr_vl": ["x", "z"],
                      "xiaomi_ocr": ["y"]}[name]
            return ({item["id"]: {"latex": value} for item, value in zip(items, values)},
                    RunInfo(name, task, len(items), 0))

        with patch.object(paper, "page_chars", return_value={0: []}), \
             patch.object(recognize, "render_crops", return_value={"b0": Path("a.png"), "b1": Path("b.png")}), \
             patch.object(recognize, "run_engine", side_effect=run):
            recognize.run([paper], cfg, Path("output/work"), log=lambda _: None)
        self.assertEqual(calls[-1], ("xiaomi_ocr", ["paper/b1"]))
        self.assertIsNone(first.candidate("xiaomi_ocr"))
        self.assertEqual(second.candidate("xiaomi_ocr").content, "y")


if __name__ == "__main__":
    unittest.main()
