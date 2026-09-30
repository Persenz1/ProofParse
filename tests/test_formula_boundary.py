"""Boundary proposals preserve math numbers and leave interior prose untouched."""
import unittest

from proofparse.formula.native import analyze
from test_native_constraints import glyph


def evidence(parts):
    chars, x = [], 10
    for text, font in parts:
        for letter in text:
            chars.append(glyph(letter, len(chars), x) | {'font': font})
            x += 6
    return {'characters': chars, 'body_font': 'Prose', 'target_bbox_pt': [0, 30, x, 60],
            'page_size_pt': [200, 300]}


class BoundaryTests(unittest.TestCase):
    def findings(self, source):
        return [f for f in analyze(source, 'x', '')['findings'] if f['type'] == 'boundary_suggestion']

    def test_trailing_reference_keeps_math_one_in_same_font(self):
        source = evidence([('q', 'Math'), ('1', 'Prose'), ('<', 'Math'), ('1(Fig.3', 'Prose')])
        finding, = self.findings(source)
        self.assertEqual(finding['trim'], 'trailing')
        self.assertEqual(finding['prose_text'], '(Fig.3')
        self.assertGreater(finding['suggested_target_bbox_pt'][2], source['characters'][3]['bbox_pt'][2])
        self.assertLess(finding['suggested_target_bbox_pt'][2], source['characters'][4]['bbox_pt'][0])

    def test_leading_word_has_only_a_suggestion(self):
        source = evidence([('where ', 'Prose'), ('x', 'Math')])
        before = list(source['target_bbox_pt'])
        finding, = self.findings(source)
        self.assertEqual(finding['trim'], 'leading')
        self.assertEqual(source['target_bbox_pt'], before)

    def test_interior_if_is_reported_without_trim_coordinates(self):
        source = evidence([('x', 'Math'), ('if', 'Prose'), ('y', 'Math')])
        finding, = self.findings(source)
        self.assertEqual(finding['trim'], 'none')
        self.assertNotIn('suggested_crop_bbox_1000', finding)

    def test_missing_page_font_is_explicitly_unreliable(self):
        source = evidence([('x', 'Math')])
        del source['body_font']
        self.assertEqual(analyze(source, 'x', '')['boundary_check']['status'], 'unreliable')


if __name__ == '__main__':
    unittest.main()
