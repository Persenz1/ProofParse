"""Checks for array alignment overflow exposed by formula recognition."""
import unittest

from proofparse.formula.lint import check_latex


class ArrayLintTests(unittest.TestCase):
    def test_six_components_do_not_fit_five_declared_columns(self):
        for declaration in ("lllll", "|l l l l l|"):
            with self.subTest(declaration=declaration):
                latex = r"\begin{array}{" + declaration + r"}a&b&c&d&e&f\end{array}"
                self.assertIn("array_column_overflow", check_latex(latex))

    def test_nested_array_counts_only_its_own_alignment_cells(self):
        legal = r"\begin{array}{cc}x&\begin{array}{cc}a&b\\c&d\end{array}\\y&z\end{array}"
        self.assertEqual(check_latex(legal), [])
        overflowing_inner = legal.replace("a&b", "a&b&e")
        self.assertIn("array_column_overflow", check_latex(overflowing_inner))

    def test_short_rows_and_escaped_ampersands_are_legal(self):
        latex = r"\begin{array}{lcr}a\&b\\c&d\\e&&f\end{array}"
        self.assertEqual(check_latex(latex), [])

    def test_complex_declarations_and_multicolumn_are_skipped(self):
        for declaration in (r"p{2cm}c", r"@{}cc", r"*{2}{c}", r"\columns"):
            with self.subTest(declaration=declaration):
                latex = r"\begin{array}{" + declaration + r"}a&b&c&d\end{array}"
                self.assertNotIn("array_column_overflow", check_latex(latex))
        latex = r"\begin{array}{cc}\multicolumn{2}{c}{x}&y&z\end{array}"
        self.assertNotIn("array_column_overflow", check_latex(latex))


if __name__ == "__main__":
    unittest.main()
