"""Regressions for formula comparison and destructive review corrections."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from proofparse.formula.compare import compare_latex, verdict
from proofparse.formula.syntax import math_spans
from proofparse.review.agent import FileVLM
from proofparse.review.apply import apply_to_document
from proofparse.review.collect import collect
from proofparse.review.patches import equation_patch, inline_patch, prose_patch


class FormulaTests(unittest.TestCase):
    def test_notation_agreement_preserves_control_word_boundaries(self):
        for a, b in [(r"x ^ 2 + y_i", r"x^{2}+y_{i}"),
                     (r"\alpha x \leq y", r"\alpha x\le y"),
                     (r"\[x^{\alpha}\]", r"x^\alpha")]:
            with self.subTest(a=a): self.assertEqual(verdict(a, b)[0], "PASS")
        self.assertEqual(verdict(r"\alpha x", r"\alphax")[0], "REVIEW")

    def test_real_structure_and_text_differences_stay_open(self):
        for a, b in [(r"x^{12}", "x^12"), (r"\mathbf{x}", "x"),
                     (r"\text{a b}", r"\text{ab}"), (r"\operatorname{a b}", r"\operatorname{ab}"),
                     (r"\begin{matrix}a&b\\c&d\end{matrix}", r"\begin{matrix}a&b&c&d\end{matrix}"),
                     ("x% comment\n+y", "x% comment +y")]:
            with self.subTest(a=a): self.assertEqual(verdict(a, b)[0], "REVIEW")

    def test_layout_and_number_differences_are_separate(self):
        comparison = compare_latex(r"\dfrac{x}{y}\tag{A.1}", r"\frac{x}{y}")
        self.assertEqual(comparison["body_relation"], "layout")
        self.assertEqual(comparison["number_relation"], "missing_ocr")
        self.assertEqual(compare_latex(r"x^2\tag{1}", r"x^{2}\tag{2}")["body_relation"], "notation")
        diff = compare_latex("x+y", "x-y")["differences"]
        self.assertEqual(diff, [{"a_tokens": [1, 2], "b_tokens": [1, 2], "a": ["+"], "b": ["-"]}])

    def test_number_preserved_and_intentional_correction_explicit(self):
        self.assertEqual(equation_patch(r"x\tag{4}", "$$y$$"), (r"y\tag{4}", None))
        self.assertEqual(equation_patch("(S12a)", "x"), (r"x\tag{S12a}", None))
        self.assertEqual(equation_patch(r"x\tag{4}", r"y\tag{5}")[1], "protected_equation_number")
        self.assertIsNone(equation_patch(r"x\tag{4}", r"y\tag{5}",
                          {"old": [r"\tag{4}"], "new": [r"\tag{5}"]})[1])
        self.assertEqual(equation_patch(r"x\tag{4}", r"\begin{aligned}y\end{aligned}")[1],
                         "protected_equation_number")

    def test_inline_replacement_never_matches_prose_or_subexpressions(self):
        self.assertEqual(inline_patch("x denotes $x$.", "x", "$y$"), ("x denotes $y$.", None))
        self.assertEqual(inline_patch("Compare $xy$ and $x$.", "x", "z"), ("Compare $xy$ and $z$.", None))
        self.assertEqual(inline_patch("$x$ and $x$", "x", "y")[1], "ambiguous_span")
        self.assertEqual(inline_patch(r"Cost \$5; use \(x\).", "x", "y"),
                         (r"Cost \$5; use \(y\).", None))

    def test_prose_protects_math_and_escaped_delimiters(self):
        self.assertIsNone(prose_patch("Use $x^2$.", "Now use $x^{2}$."))
        for new in (r"Use \$x^2\$.", "Use x^2.", "Use $x_2$.", "Use $x^2."):
            self.assertIsNotNone(prose_patch("Use $x^2$.", new))
        self.assertEqual(len(math_spans(r"`$code$` and \$5 and $x$")[0]), 1)

    def test_explicit_math_edit_can_repair_broken_delimiters(self):
        self.assertIsNone(prose_patch(r"Use \$x^2\$ and $z$.", "Use $y^2$ and $z$.",
                          [{"old": r"\$x^2\$", "new": "$y^2$"}]))
        self.assertEqual(prose_patch("Use $x$ and $z$.", "Use $y$ and $w$.",
                         [{"old": "$x$", "new": "$y$"}]), "protected_inline_math")


class ReviewPatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("PROOFPARSE_TEST_TMP"))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.paper = self.root / "paper"
        self.paper.mkdir()
        (self.paper / "crop.png").write_bytes(b"fixture")

    def dump(self, name, data):
        (self.paper / name).write_text(json.dumps(data), encoding="utf-8")

    def fixture(self, blocks):
        self.dump("document.json", {"pdf_sha256": "fixture", "parse_id": "first", "blocks": blocks})
        self.dump("qc.json", {"page_review": [{"page": 0, "review_asset": "crop.png"}]})

    def test_page_patch_preserves_number_and_rejects_math_loss_atomically(self):
        self.fixture([{"block_id": "eq", "type": "equation", "content": r"x\tag{4}", "page": 0, "in_markdown": True},
                      {"block_id": "p", "type": "paragraph", "content": "Use $x$.", "page": 0, "in_markdown": True}])
        item = collect(self.root)[0]
        path = self.paper / "document.json"
        before = path.read_bytes()
        edits = [{"block_id": "eq", "old_content": r"x\tag{4}", "content": "y"},
                 {"block_id": "p", "old_content": "Use $x$.", "content": "Use x."}]
        result = apply_to_document(self.paper, item, {"choice": "custom", "confidence": 1, "edits": edits})
        self.assertEqual(result, "skipped:protected_inline_math")
        self.assertEqual(before, path.read_bytes())
        result = apply_to_document(self.paper, item, {"choice": "custom", "confidence": 1, "edits": edits[:1]})
        self.assertEqual(result, "applied:recheck_page")
        self.assertEqual(json.loads(path.read_text())["blocks"][0]["content"], r"y\tag{4}")

    def test_insert_rejects_same_or_adjacent_page_merged_text(self):
        sentence = "This missing-looking sentence was already merged into the previous paragraph."
        self.fixture([{"block_id": "previous", "type": "paragraph", "content": "Earlier prose. " + sentence,
                       "page": 1, "in_markdown": True}])
        item = collect(self.root)[0]
        result = apply_to_document(self.paper, item, {"choice": "custom", "confidence": 1,
                  "inserts": [{"after_block_id": None, "type": "paragraph", "content": sentence, "bbox": [1, 1, 50, 50]}]})
        self.assertEqual(result, "skipped:duplicate_insert")

    def test_issue_survives_reorder_but_crop_change_rejects_old_verdict(self):
        self.fixture([])
        self.dump("qc.json", {"page_review": [{"page": 0, "review_asset": "crop.png"},
                                               {"page": 1, "review_asset": "crop.png"}]})
        first = {i.page: i for i in collect(self.root)}
        qc = json.loads((self.paper / "qc.json").read_text())
        qc["page_review"].reverse()
        self.dump("qc.json", qc)
        second = {i.page: i for i in collect(self.root)}
        self.assertEqual(first[0].uid, second[0].uid)
        self.assertEqual(first[0].input_hash, second[0].input_hash)
        self.assertNotEqual(first[0].ref, second[0].ref)
        verdict_path = self.root / "verdicts.json"
        verdict_path.write_text(json.dumps({first[0].uid: {"choice": "parser", "confidence": 1,
                                                         "input_hash": first[0].input_hash}}))
        (self.paper / "crop.png").write_bytes(b"new crop")
        changed = next(i for i in collect(self.root) if i.page == 0)
        self.assertEqual(first[0].uid, changed.uid)
        with self.assertRaises(ValueError): FileVLM(verdict_path).adjudicate(changed, None)

    def test_comparison_refresh_reuses_candidates_without_ocr(self):
        self.fixture([{"block_id": "eq", "type": "equation", "content": "x^2", "page": 0}])
        self.dump("qc.json", {"formula_check": {"display": [{"block_id": "eq", "page": 0,
                    "parser": "x^2", "formula_ocr": "x^{2}", "verdict": "REVIEW"}]}})
        self.assertEqual(collect(self.root), [])
        qc = json.loads((self.paper / "qc.json").read_text())
        self.assertEqual(qc["formula_check"]["n_display_review"], 0)
        self.assertEqual(qc["formula_check"]["display"][0]["parser"], "x^2")

    def test_export_does_not_replace_broken_latex_with_image(self):
        from proofparse.export import export_paper
        self.fixture([{"block_id": "eq", "type": "equation", "content": r"x^{", "page": 0,
                       "in_markdown": True}])
        destination = self.root / "delivery"
        with self.assertRaisesRegex(ValueError, "eq"): export_paper(self.paper, destination)
        self.assertFalse(destination.exists())


if __name__ == "__main__": unittest.main()
