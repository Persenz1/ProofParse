"""Coordinate and font preservation checks using an in-memory PDF."""
import unittest

try:
    import pymupdf
except ImportError:
    pymupdf = None

from proofparse.preprocess.native import page_characters, region_evidence


@unittest.skipIf(pymupdf is None, "optional native extra is not installed")
class NativeEvidenceTests(unittest.TestCase):
    def test_rotated_page_keeps_font_baseline_and_target_membership(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=200, height=300)
            page.insert_text((30, 60), "F", fontname="hebi", fontsize=12)
            page.insert_text((140, 60), "9", fontsize=10)
            page.set_rotation(90)
            chars = page_characters(page)
            letter = next(c for c in chars if c["text"] == "F")
            self.assertIn("Bold", letter["font"])
            self.assertEqual(letter["origin_pt"], [240.0, 30.0])
            region = region_evidence(chars, [0, 0, 300, 200], letter["bbox_pt"])
            self.assertEqual([c["text"] for c in region["characters"] if c["in_target"]], ["F"])
            self.assertTrue(all("glyph_id" in c for c in region["characters"]))

    def test_no_text_does_not_imply_correct_formula(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            box = [0, 0, page.rect.width, page.rect.height]
            result = region_evidence(page_characters(page), box, box)
            self.assertEqual(result["status"], "no_text_in_region")
            self.assertEqual(result["characters"], [])


if __name__ == "__main__":
    unittest.main()
