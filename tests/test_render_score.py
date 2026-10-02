"""Three real TeX-rendering comparisons; no OCR or GPU."""
import unittest
from pathlib import Path

from proofparse.eval.render import PDFLATEX, compare

_WORK = Path(__file__).resolve().parents[1] / "output/test-render-score"


@unittest.skipUnless(PDFLATEX.is_file(), "TeX Live pdflatex is unavailable")
class RenderScoreTests(unittest.TestCase):
    def test_grouped_accent_is_equivalent(self):
        result = compare(r"\bar g", r"\bar{g}", _WORK / "accent")
        self.assertEqual(result["status"], "compared", result)
        self.assertTrue(result["equivalent"], result)

    def test_subscript_symbol_difference_is_preserved(self):
        result = compare(r"x_1", r"x_2", _WORK / "subscript")
        self.assertEqual(result["status"], "compared", result)
        self.assertFalse(result["equivalent"], result)

    def test_bold_upright_and_bold_math_fonts_are_different(self):
        result = compare(r"\mathbf{x}", r"\boldsymbol{x}", _WORK / "bold-font")
        self.assertEqual(result["status"], "compared", result)
        self.assertFalse(result["equivalent"], result)
        self.assertEqual(result["reason"], "glyph_or_font_mismatch")

    def test_shared_font_span_and_outer_alignment_environment(self):
        result = compare(r"\begin{align*}a&=b\\c&=d\end{align*}",
                         r"a&=b\\c&=d", _WORK / "shared-span")
        self.assertEqual(result["status"], "compared", result)
        self.assertTrue(result["equivalent"], result)


if __name__ == "__main__":
    unittest.main()
