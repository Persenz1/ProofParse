"""Whitelist tables cannot infer arbitrary font identities or subset GID slots."""
import importlib.util
import unittest

from proofparse.formula.fonttables import font_table
from proofparse.formula.native import apply_glyph_map, analyze
from proofparse.pdf.fontnames import embedded_glyph_names
from test_native_constraints import glyph


class FontTableTests(unittest.TestCase):
    def test_whitelist_styles_and_subset_size_suffixes(self):
        for family, styles in {
            'CMSY': ['calligraphic'], 'CMBSY': ['calligraphic', 'bold'],
            'MSBM': ['double_struck'], 'EUSM': ['script'], 'EUSB': ['script', 'bold'],
            'RSFS': ['script'], 'EUFM': ['fraktur'], 'EUFB': ['fraktur', 'bold'],
            'CMMIB': ['bold', 'italic'], 'CMBX': ['bold'], 'CMMI': ['italic'],
        }.items():
            with self.subTest(family=family):
                char = glyph('K', 0, 10) | {'font': 'ABCDEF+' + family + '10'}
                mapping = font_table(char)
                self.assertEqual(mapping['mapped_text'], 'K')
                self.assertEqual(mapping['mapped_styles'], styles)
                self.assertEqual(mapping['mapping_source'], 'font_table')

    def test_oml_greek_slots_and_oms_minus(self):
        char = glyph('�', 0, 10) | {'font': 'CMMI10', 'suspicious_encoding': True,
                                  'font_charcode': 0x18}
        self.assertEqual(font_table(char)['mapped_text'], 'ξ')
        char['font_charcode'] = 0x0F
        self.assertEqual(font_table(char)['mapped_text'], 'ϵ')
        char.update(font='CMSY10', font_charcode=0)
        self.assertEqual(font_table(char)['mapped_text'], '−')

    def test_glyph_id_is_not_a_character_code_and_unknown_fonts_are_ignored(self):
        char = glyph('�', 0, 10) | {'font': 'CMMI10', 'glyph_id': 0x18,
                                  'suspicious_encoding': True}
        self.assertIsNone(font_table(char))
        self.assertIsNone(font_table(glyph('K', 0, 10) | {'font': 'AdvP4C4E74'}))

    def test_confirmed_mapping_wins_and_conflict_is_review_evidence(self):
        char = glyph('K', 0, 10) | {'font': 'CMSY10'}
        confirmed = [{'font_xref': 1, 'glyph_id': ord('K'), 'text': 'B',
                      'styles': [], 'source': {'page': 0}}]
        mapped = apply_glyph_map([char], confirmed)
        self.assertEqual(mapped[0]['mapped_text'], 'B')
        self.assertEqual(mapped[0]['mapping_source'], 'confirmed')
        result = analyze({'characters': mapped}, 'B', 'B')
        self.assertIn('glyph_mapping_conflict', [f['type'] for f in result['findings']])

    def test_white_font_calligraphy_creates_a_constraint_without_rewriting(self):
        mapped = apply_glyph_map([glyph('K', 0, 10) | {'font': 'CMSY10'}], [])
        result = analyze({'characters': mapped}, 'K', r'\mathcal{K}')
        fonts = [f for f in result['findings'] if f['type'] == 'font_constraint']
        self.assertEqual([f['candidate'] for f in fonts], ['parser'])

    def test_missing_fonttools_has_explicit_degradation(self):
        if importlib.util.find_spec('fontTools') is not None:
            self.skipTest('fontTools is installed')
        status, names = embedded_glyph_names(None, 1)
        self.assertEqual(status['status'], 'skipped')
        self.assertEqual(names, [])

    @unittest.skipIf(importlib.util.find_spec('fontTools') is None, 'optional fontnames extra is not installed')
    def test_embedded_cff_glyph_order_by_gid(self):
        from io import BytesIO
        from fontTools.fontBuilder import FontBuilder
        from fontTools.pens.t2CharStringPen import T2CharStringPen
        builder = FontBuilder(1000, isTTF=False)
        builder.setupGlyphOrder(['.notdef', 'B'])
        builder.setupCharacterMap({ord('B'): 'B'})
        builder.setupHorizontalMetrics({'.notdef': (600, 0), 'B': (600, 0)})
        builder.setupHorizontalHeader(ascent=800, descent=-200)
        pen = T2CharStringPen(600, None)
        builder.setupCFF('Test', {}, {name: pen.getCharString() for name in ['.notdef', 'B']}, {})
        stream = BytesIO()
        builder.font['CFF '].cff.compile(stream, builder.font)
        class Document:
            def extract_font(self, xref):
                return 'Test', 'cff', 'Type1', stream.getvalue()
        status, names = embedded_glyph_names(Document(), 1)
        self.assertEqual(status['status'], 'available')
        self.assertEqual(names[1], 'B')


if __name__ == '__main__':
    unittest.main()
