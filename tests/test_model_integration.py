"""Regression checks for model comparisons; no recognizers or GPU required."""
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from proofparse import ir
from proofparse.engines.runner import item_key
from proofparse.eval import bench
from proofparse.ir import Block, Candidate
from proofparse.preprocess.native import page_objects
from proofparse.stages.reconcile import decide_formula


class ModelIntegrationTests(unittest.TestCase):
    def test_image_objects_use_displayed_page_coordinates(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=200, height=300)
            image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 10), False)
            image.clear_with(255)
            page.insert_image(pymupdf.Rect(20, 40, 60, 60), stream=image.tobytes("png"))
            for rotation, expected in ((0, [20, 40, 60, 60]), (90, [240, 20, 260, 60])):
                with self.subTest(rotation=rotation):
                    page.set_rotation(rotation)
                    self.assertEqual(page_objects(page)["images"], [expected])

    def test_inference_settings_invalidate_cached_predictions(self):
        item = {"id": "first", "kind": "display"}
        settings = {"python": "recognizer/python.exe", "device": "cpu", "batch_size": 1}
        original = item_key("recognizer", "formula", {}, item, **settings)
        self.assertEqual(original, item_key("recognizer", "formula", {},
                                           item | {"id": "second"}, **settings))
        for changed in ({"python": "other/python.exe"}, {"device": "cuda"}, {"batch_size": 2}):
            with self.subTest(changed=changed):
                self.assertNotEqual(original, item_key("recognizer", "formula", {}, item,
                                                       **(settings | changed)))

    def test_removed_model_does_not_confirm_current_candidate(self):
        block = Block("p000b000", 0, [0, 0, 10, 10], ir.DISPLAY_MATH,
                      candidates=[Candidate("current", "current-family", "x"),
                                  Candidate("removed", "removed-family", "x")])
        decision = decide_formula(block, ["current"])
        self.assertEqual(decision.status, ir.UNVERIFIED)
        self.assertEqual(decision.evidence["groups"], [["current"]])

    def test_configured_page_parser_formula_candidate_is_kept(self):
        block = Block("p000b000", 0, [0, 0, 10, 10], ir.DISPLAY_MATH,
                      candidates=[Candidate("mineru_pipeline", "unimernet", "x"),
                                  Candidate("pp_formulanet_plus_m", "pp-formulanet", "x")])
        decision = decide_formula(block, ["mineru_pipeline", "pp_formulanet_plus_m"])
        self.assertEqual(decision.status, ir.ACCEPTED)
        self.assertEqual(decision.rule, "unanimous:pp-formulanet+unimernet")

    def test_changed_render_scale_renders_new_crops(self):
        gold = {"paper": "paper", "formulas": [{"id": 1, "display": True, "status": "ok",
                "expansion_complete": True, "unsupported_macros": [], "latex_expanded": "x",
                "context": "", "env": "equation", "occurrences": [
                    {"page": 0, "bbox_pt": [10, 10, 20, 20], "layout_verified": True}]}]}
        generated = set()
        rendered = []

        def render(pdf, jobs, scale):
            rendered.extend((str(path), scale) for _, _, path, _ in jobs)
            generated.update(str(path) for _, _, path, _ in jobs)

        with patch.object(bench, "gold_papers", return_value=[(Path("gold"), gold)]), \
             patch.object(bench, "crop_regions", side_effect=render), \
             patch.object(Path, "is_file", autospec=True, side_effect=lambda path: str(path) in generated):
            first, _ = bench.formula_items(Path("output"), scale=3.0)
            again, _ = bench.formula_items(Path("output"), scale=3.0)
            changed, _ = bench.formula_items(Path("output"), scale=2.0)
        self.assertEqual(first[0]["image"], again[0]["image"])
        self.assertNotEqual(first[0]["image"], changed[0]["image"])
        self.assertEqual([scale for _, scale in rendered], [3.0, 2.0])


if __name__ == "__main__":
    unittest.main()
