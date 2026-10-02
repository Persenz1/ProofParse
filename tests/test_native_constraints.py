"""Targeted regressions for native glyph constraints (no models or API)."""
import unittest

from proofparse import ir
from proofparse.formula.native import candidate_atoms, apply_glyph_map, analyze, number_candidates
from proofparse.ir import Block, Candidate, Document, Page
from proofparse.stages import assemble, reconcile


def glyph(text, index, x, y=50, *, bold=False, font=1):
    return {'text': text, 'source_index': [0, index], 'font_xref': font, 'glyph_id': ord(text),
            'font_flags': 16 if bold else 0, 'bbox_pt': [x, y-8, x+5, y+2],
            'origin_pt': [x, y], 'size_pt': 10, 'render_type': 0, 'opacity': 1,
            'in_target': True}


class NativeConstraintTests(unittest.TestCase):
    def test_font_scopes_and_repeated_symbol_ambiguity(self):
        chars = [glyph('F', 0, 10, bold=True), glyph('F', 1, 40)]
        result = analyze({'characters': chars}, {'parser': r'F+F', 'formula_ocr': r'\mathbf{F}+F'})
        findings = result['findings']
        self.assertEqual([(f['candidate'], f['symbol']) for f in findings], [('parser', 'F')])
        self.assertTrue(all(a['status'] == 'ambiguous' for a in
                            result['candidates']['formula_ocr']['alignment'] if a['text'] == 'F'))
        atoms = candidate_atoms(r'\mathbf{F}_i+\mathcal{K}+\alpha\tag{2}')
        self.assertEqual(atoms['numbers'], ['2'])
        self.assertEqual([a['text'] for a in atoms['atoms']], ['F', 'i', '+', 'K', '+', 'α'])
        self.assertEqual(atoms['atoms'][1]['styles'], [])

    def test_unknown_macro_and_missing_symbol_do_not_prove_font_error(self):
        chars = [glyph('F', 0, 10, bold=True)]
        result = analyze({'characters': chars}, {'parser': r'\custom F', 'formula_ocr': 'G'})
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['candidates']['parser']['unsupported_commands'], [r'\custom'])

    def test_mapping_is_specific_to_font_resource_and_glyph(self):
        chars = [glyph('K', 0, 10), glyph('K', 1, 30, font=2)]
        mapped = apply_glyph_map(chars, [{'font_xref': 1, 'glyph_id': ord('K'), 'text': 'K',
                                         'styles': ['calligraphic'], 'source': {'page': 0}}])
        self.assertNotIn('mapped_styles', mapped[1])
        result = analyze({'characters': mapped}, {'parser': 'K+K', 'formula_ocr': r'\mathcal{K}+K'})
        self.assertEqual(len(result['findings']), 1)
        self.assertEqual(result['findings'][0]['style'], 'calligraphic')

    def test_number_ownership_and_body_parentheses(self):
        chars = [glyph(c, i, 100+i*5) for i, c in enumerate('(9)')]
        target = [10, 38, 70, 54]
        self.assertEqual(number_candidates(chars, target)['candidates'][0]['value'], '9')
        self.assertEqual(number_candidates(chars, target, [[75, 38, 90, 54]])['status'], 'unresolved')
        self.assertEqual(number_candidates(chars, [90, 38, 130, 54])['status'], 'unresolved')
        prose = [glyph(c, i, 100+i*5) for i, c in enumerate('Eq.(9)')]
        self.assertEqual(number_candidates(prose, target)['status'], 'unresolved')
        # Two isolated labels are ambiguous, never silently pick the nearer one.
        chars += [glyph(c, i+4, -30+i*5) for i, c in enumerate('(8)')]
        self.assertEqual(number_candidates(chars, target)['status'], 'ambiguous')

    def test_missing_number_is_separate_from_body_font_and_prose(self):
        chars = [glyph(c, i, i*5) for i, c in enumerate('q1(Fig.3')]
        result = analyze({'characters': chars}, {'parser': r'q_1', 'formula_ocr': r'q_1'}, numbers={
            'status': 'associated_by_layout', 'candidates': [{'value': '9'}]})
        self.assertEqual([f['type'] for f in result['findings']],
                         ['math_prose_boundary'])

    def test_associated_display_number_is_restored_and_wrong_explicit_tag_is_rejected(self):
        for latex, status in [('x=1', ir.ACCEPTED), (r'x=1 \tag{8}', ir.CONFLICT)]:
            with self.subTest(latex=latex):
                chars = [glyph(c, i, 10 + i * 5) for i, c in enumerate('x=1')]
                chars += [glyph(c, i + 3, 100 + i * 5) for i, c in enumerate('(9)')]
                chars = [c | {'font': 'CMR10', 'suspicious_encoding': False} for c in chars]
                block = Block('eq1', 0, [10, 38, 70, 54], ir.DISPLAY_MATH,
                              candidates=[Candidate('a', 'family_a', latex),
                                          Candidate('b', 'family_b', latex)])
                doc = Document(pages=[Page(0, 200, 100, text_layer={'status': 'good'})],
                               blocks=[block])
                reconcile.run(doc, {0: chars}, ['a', 'b'])
                self.assertEqual(block.decision.status, status)
                association = block.decision.evidence['number_association']
                self.assertEqual(association['status'], 'associated_by_layout')
                self.assertEqual(association['candidates'][0]['value'], '9')
                if status == ir.ACCEPTED:
                    self.assertEqual(block.decision.evidence['rejected'], {})
                    self.assertEqual(assemble.blocking(doc), [])
                    self.assertIn('$$\nx=1 \\tag{9}\n$$', assemble.build_markdown(doc, delivery=True))
                else:
                    for name in ('a', 'b'):
                        finding, = block.decision.evidence['rejected'][name]
                        self.assertEqual(finding['type'], 'number_constraint')
                        self.assertEqual(finding['candidate_numbers'], ['8'])
                        self.assertEqual(finding['source_number'], '9')

    def test_invisible_text_cannot_supply_font_constraints(self):
        char = glyph('F', 0, 0, bold=True)
        char['render_type'] = 3
        self.assertEqual(analyze({'characters': [char]}, {'parser': 'F', 'formula_ocr': 'F'})['findings'], [])


if __name__ == '__main__':
    unittest.main()
