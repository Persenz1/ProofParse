"""Scoring aliases preserve source notation and mathematical structure."""
import unittest

from proofparse.eval.score import same, score


class FormulaScoreTests(unittest.TestCase):
    def test_real_roman_declarations_keep_strict_scoring(self):
        gold = r"r[n]=r_{\rm SI}[n]+s_{\rm rx}[n]+\eta[n],"
        pred = r"r[n]=r_{\mathrm{S I}}[n]+s_{\mathrm{r x}}[n]+\eta[n],"
        result = score(pred, gold)
        self.assertTrue(result['loose'])
        self.assertFalse(result['strict'])
        self.assertFalse(result['layout'])
        self.assertTrue(same(r"{\rm SI}", r"\mathrm{SI}"))
        self.assertTrue(same(r"\frac{\rm SI}{x}", r"\frac{\mathrm{SI}}{x}"))

    def test_roman_declaration_scope_is_not_extended(self):
        self.assertFalse(same(r"{\rm SI+x}", r"\mathrm{SI}+x"))
        self.assertFalse(same(r"\rm SI", r"\mathrm{SI}"))
        self.assertFalse(same(r"{\rm SI}x", r"{\rm SIx}"))

    def test_comments_are_removed_without_erasing_escaped_percent(self):
        self.assertTrue(same("x+y% discarded formula\n=z", "x+y=z"))
        self.assertTrue(same("x\\\\% comment\ny", "x\\\\y"))
        self.assertTrue(same("\\alpha% comment\nx", r"\alpha x"))
        self.assertFalse(same("\\alpha% comment\nx", r"\alphax"))
        self.assertFalse(same(r"x\%", "x"))

    def test_single_atom_accent_arguments(self):
        for accent, atom in [('bar', 'g'), ('hat', r'\omega'), ('tilde', 'z'), ('dot', 'x')]:
            with self.subTest(accent=accent):
                a, b = '\\' + accent + ' ' + atom, '\\' + accent + '{' + atom + '}'
                self.assertTrue(same(a, b))
                self.assertFalse(score(a, b)['strict'])
        self.assertFalse(same(r"\bar{g+h}", r"\bar g+h"))
        self.assertFalse(same(r"\hat{\bm h}", r"\hat\bm h"))

    def test_arrow_alias_is_only_a_loose_scoring_alias(self):
        a, b = r"A_i\to B_i", r"A_i\rightarrow B_i"
        self.assertTrue(same(a, b))
        self.assertFalse(score(a, b)['strict'])

    def test_fonts_scripts_and_matrix_cells_remain_distinct(self):
        for a, b in [(r'\bm h', r'\mathbf{h}'), (r'\mathcal{B}', 'B'),
                     ('x_i', 'x^i'), ('x^{ab}', 'x^ab'),
                     (r'\begin{matrix}a&b\\c&d\end{matrix}',
                      r'\begin{matrix}a&b&c&d\end{matrix}')]:
            with self.subTest(a=a):
                self.assertFalse(same(a, b))


if __name__ == '__main__':
    unittest.main()
