"""Script paths, fraction exclusions and primary matrix baselines."""
import unittest

from proofparse.formula.native import analyze, candidate_atoms
from proofparse.formula.geometry import source_roles
from test_native_constraints import glyph


def char(text, index, x, y=50, size=10):
    return glyph(text, index, x, y) | {'size_pt': size, 'font': 'Times-Roman'}


def matrix():
    left = char('(', 0, 0) | {'font': 'CMEX10', 'bbox_pt': [0, 30, 5, 75]}
    right = char(')', 5, 55) | {'font': 'CMEX10', 'bbox_pt': [55, 30, 60, 75]}
    return [left, char('a', 1, 15), char('b', 2, 35),
            char('c', 3, 15, 70), char('d', 4, 35, 70), right]


class GeometryTests(unittest.TestCase):
    def check(self, chars, latex):
        return analyze({'characters': chars}, {'parser': latex, 'formula_ocr': ''})

    def test_unique_script_mismatch_and_nested_role_paths(self):
        chars = [char('x', 0, 10), char('a', 1, 20, 54, 7), char('i', 2, 26, 50, 4.5)]
        result = self.check(chars, r'x_{a^{i}}')
        self.assertEqual([f for f in result['findings'] if f['type'] == 'script_constraint'], [])
        atoms = candidate_atoms(r'x_{a^{i}}')['atoms']
        self.assertEqual(atoms[-1]['role'], 'subscript>superscript')
        result = self.check(chars, r'x_{a_i}')
        findings = [f for f in result['findings'] if f['type'] == 'script_constraint']
        self.assertEqual([f['symbol'] for f in findings], ['i'])

    def test_size_and_baseline_thresholds_are_strict(self):
        chars = [char('x', 0, 10), char('i', 1, 20, 46, 8.5)]
        self.assertEqual(source_roles(chars)[(0, 1)], 'math')
        chars[1]['size_pt'] = 8.49
        self.assertEqual(source_roles(chars)[(0, 1)], 'superscript')
        chars[1]['origin_pt'][1] = 48.5
        self.assertIsNone(source_roles(chars)[(0, 1)])

    def test_fraction_symbols_and_repeats_do_not_get_fake_pairings(self):
        chars = [char('x', 0, 10), char('a', 1, 20, 40, 7), char('b', 2, 20, 60, 7)]
        result = self.check(chars, r'x+\frac{a}{b}')
        self.assertFalse(any(f['type'] == 'script_constraint' for f in result['findings']))
        self.assertEqual(result['candidates']['parser']['script_check']['skipped']['fraction_symbols'], 2)
        result = self.check([char('x', 0, 10), char('x', 1, 20, 46, 7)], r'x_x')
        self.assertFalse(any(f['type'] == 'script_constraint' for f in result['findings']))

    def test_missing_matrix_row_is_detected(self):
        result = self.check(matrix(), r'\begin{pmatrix}a&b\end{pmatrix}')
        finding, = [f for f in result['findings'] if f['type'] == 'matrix_constraint']
        self.assertEqual((finding['source_rows'], finding['candidate_rows']), (2, 1))

    def test_matrix_scripts_and_trailing_separator_do_not_add_rows(self):
        chars = matrix() + [char('i', 6, 21, 46, 7)]
        result = self.check(chars, r'\begin{pmatrix}a^i&b\\c&d\\\end{pmatrix}')
        self.assertFalse(any(f['type'] == 'matrix_constraint' for f in result['findings']))
        self.assertEqual(result['candidates']['parser']['matrix_check']['source_rows'], 2)

    def test_nested_multiple_and_fraction_matrices_explicitly_skip(self):
        for latex in [r'\begin{matrix}\begin{matrix}a\end{matrix}\end{matrix}',
                      r'\begin{matrix}a\end{matrix}+\begin{matrix}b\end{matrix}',
                      r'\begin{matrix}\frac{a}{b}\end{matrix}']:
            with self.subTest(latex=latex):
                result = self.check(matrix(), latex)
                self.assertEqual(result['candidates']['parser']['matrix_check']['status'], 'skipped')


if __name__ == '__main__':
    unittest.main()
