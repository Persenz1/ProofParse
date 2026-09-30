"""Multiplicity checks preserve uncertainty and exclude non-body glyphs."""
import unittest

from proofparse.formula.native import analyze, requires_review
from test_native_constraints import glyph


def characters(text):
    return [glyph(s, i, i * 6) | {'font': 'Times-Roman', 'suspicious_encoding': False}
            for i, s in enumerate(text)]


class CountTests(unittest.TestCase):
    def findings(self, chars, latex, **kwargs):
        result = analyze({'characters': chars}, latex, '', **kwargs)
        return result, [f for f in result['findings'] if f['type'] == 'count_constraint']

    def test_extra_xi_missing_parenthesis_and_zero_as_theta(self):
        for source, latex, symbols in [('S=ξ', r'\xi S=\xi', {'ξ'}),
                                       ('x(i)', 'x(i', {')'}),
                                       ('x=0', r'x=\theta', {'0', 'θ'})]:
            with self.subTest(source=source):
                result, findings = self.findings(characters(source), latex)
                self.assertEqual({f['symbol'] for f in findings}, symbols)
                self.assertEqual(result['candidates']['parser']['count_check']['status'], 'checked')

    def test_extension_delimiters_do_not_generate_false_counts(self):
        chars = characters('(x)')
        chars[0]['font'] = chars[2]['font'] = 'ABCDEF+CMEX10'
        result, findings = self.findings(chars, r'\left(x\right)')
        self.assertEqual(findings, [])
        self.assertTrue(result['candidates']['parser']['count_check']['skipped']['delimiters'])

    def test_minus_prime_and_mathematical_letters_normalize(self):
        result, findings = self.findings(characters('𝑥−１′'), r'x-1\prime')
        self.assertEqual(findings, [])

    def test_associated_number_is_excluded_from_source(self):
        chars = characters('x(9)')
        result, findings = self.findings(chars, r'x\tag{9}', numbers={
            'status': 'associated_by_layout', 'candidates': [{
                'value': '9', 'source_indices': [c['source_index'] for c in chars[1:]]}]})
        self.assertEqual(findings, [])
        self.assertEqual(result['candidates']['parser']['count_check']['skipped']['equation_number'], 3)

    def test_suspicious_encoding_and_unknown_macro_do_not_pass_silently(self):
        chars = characters('x�')
        chars[-1]['suspicious_encoding'] = True
        result, findings = self.findings(chars, 'x+y')
        self.assertEqual(findings, [])
        self.assertEqual(result['candidates']['parser']['count_check']['status'], 'unreliable')
        self.assertTrue(requires_review(result))
        result, findings = self.findings(characters('x'), r'\custom{x}')
        self.assertEqual(findings, [])
        self.assertEqual(result['candidates']['parser']['count_check']['status'], 'skipped')
        self.assertTrue(requires_review(result))

    def test_array_preamble_and_escaped_delimiters_are_not_letters(self):
        result, findings = self.findings(characters('x'), r'\left\{\begin{array}{c}x\end{array}\right.')
        self.assertEqual(findings, [])

    def test_large_operators_and_accents_are_not_counted(self):
        result, findings = self.findings(characters('∑xˆ'), r'\sum\hat{x}')
        self.assertEqual(findings, [])


if __name__ == '__main__':
    unittest.main()
