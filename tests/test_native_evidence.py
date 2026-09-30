"""Coordinate and font preservation checks using an in-memory PDF."""
import unittest
import json
import os
import tempfile
from pathlib import Path

try:
    import pymupdf
except ImportError:
    pymupdf = None

from proofparse.pdf.native import page_characters, region_evidence


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
            x0, y0, x1, y1 = letter["bbox_pt"]
            target = [x0/300*1000, y0/200*1000, x1/300*1000, y1/200*1000]
            region = region_evidence(chars, (300, 200), [0, 0, 1000, 1000], target)
            self.assertEqual([c["text"] for c in region["characters"] if c["in_target"]], ["F"])
            self.assertTrue(all("glyph_id" in c for c in region["characters"]))

    def test_no_text_does_not_imply_correct_formula(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            result = region_evidence(page_characters(page), (page.rect.width, page.rect.height),
                                     [0, 0, 1000, 1000], [0, 0, 1000, 1000])
            self.assertEqual(result["status"], "no_text_in_region")
            self.assertEqual(result["characters"], [])

    def test_agreed_ocr_with_missing_bold_is_reviewed_and_can_be_resolved(self):
        from proofparse.review.collect import collect
        from proofparse.review.apply import paper_status
        from proofparse.review.review import run_review
        from proofparse.review.agent import FileVLM
        with tempfile.TemporaryDirectory(dir=os.environ.get('PROOFPARSE_TEST_TMP')) as temp:
            root = Path(temp)
            folder = root / 'paper'
            folder.mkdir()
            with pymupdf.open() as pdf:
                page = pdf.new_page(width=200, height=300)
                page.insert_text((30, 60), 'F', fontname='hebi')
                page.insert_text((160, 60), '(9)')
                pdf.save(folder / 'source.pdf')
            bbox = [140, 150, 210, 215]
            content = r'F\tag{9}'
            document = {'source_pdf': 'source.pdf', 'blocks': [
                {'block_id': 'eq', 'type': 'equation', 'content': content,
                 'page': 0, 'bbox': bbox, 'in_markdown': True}]}
            qc = {'formula_check': {'display': [{'block_id': 'eq', 'page': 0, 'bbox': bbox,
                  'parser': content, 'formula_ocr': content, 'verdict': 'PASS'}]}}
            (folder / 'document.json').write_text(json.dumps(document), encoding='utf-8')
            (folder / 'qc.json').write_text(json.dumps(qc), encoding='utf-8')
            item, = collect(root)
            self.assertEqual(item.issue_type, 'formula_native_constraint')
            self.assertTrue((folder / item.review_asset).is_file())
            current = json.loads((folder / 'qc.json').read_text(encoding='utf-8'))
            self.assertEqual(paper_status(current), 'still_open')
            again, = collect(root)
            self.assertEqual(item.input_hash, again.input_hash)
            verdict_path = root / 'verdicts.json'
            verdict_path.write_text(json.dumps({item.uid: {
                'choice': 'custom', 'confidence': 1, 'input_hash': item.input_hash,
                'corrected_latex': r'\mathbf{F}\tag{9}', 'reason': 'test correction'}}), encoding='utf-8')
            result = run_review(root, FileVLM(verdict_path), verbose=False)
            self.assertEqual(result['paper']['n_applied'], 1)
            self.assertEqual(collect(root), [])

    def test_glyph_mapping_changes_affected_hash_but_not_issue_identity(self):
        from proofparse.review.collect import collect
        from proofparse.review.native import confirm_glyph
        with tempfile.TemporaryDirectory(dir=os.environ.get('PROOFPARSE_TEST_TMP')) as temp:
            root = Path(temp)
            folder = root / 'paper'
            folder.mkdir()
            with pymupdf.open() as pdf:
                page = pdf.new_page(width=200, height=300)
                page.insert_text((30, 60), 'K')
                page.insert_text((30, 120), 'F')
                pdf.save(folder / 'source.pdf')
            blocks, records = [], []
            for char, bbox in [('K', [140, 150, 220, 215]), ('F', [140, 350, 220, 415])]:
                blocks.append({'block_id': char, 'type': 'equation', 'content': char, 'page': 0,
                               'bbox': bbox, 'in_markdown': True})
                records.append({'block_id': char, 'page': 0, 'bbox': bbox, 'parser': char,
                                'formula_ocr': r'\mathcal{' + char + '}', 'verdict': 'REVIEW'})
            (folder / 'document.json').write_text(json.dumps({'source_pdf': 'source.pdf', 'blocks': blocks}), encoding='utf-8')
            (folder / 'qc.json').write_text(json.dumps({'formula_check': {'display': records}}), encoding='utf-8')
            before = {it.block_id: it for it in collect(root)}
            with pymupdf.open(folder / 'source.pdf') as pdf:
                glyph = next(c for c in page_characters(pdf[0]) if c['text'] == 'K')
            confirm_glyph(folder / 'source.pdf', folder / 'native_glyphs.json', 0,
                          glyph['source_index'], 'K', ['calligraphic'])
            after = {it.block_id: it for it in collect(root)}
            self.assertEqual(before['K'].uid, after['K'].uid)
            self.assertNotEqual(before['K'].input_hash, after['K'].input_hash)
            self.assertEqual(before['F'].input_hash, after['F'].input_hash)


if __name__ == "__main__":
    unittest.main()
