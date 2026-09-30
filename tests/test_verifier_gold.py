"""Gold preparation preserves saved candidates and human-owned confirmation."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.verifier_gold_template import build_gold, write_gold


class GoldTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('PROOFPARSE_TEST_TMP'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'crop.png').write_bytes(b'fixture')
        (self.root / 'paper.pdf').write_bytes(b'fixture')
        self.tasks = [{'id': 't01', 'paper': 'paper', 'page': 2, 'kind': 'display',
                       'ocr_crop': 'crop.png', 'target_bbox_1000': [10, 20, 30, 40],
                       'source_region_bbox_1000': [0, 10, 100, 50],
                       'a': r' x ^ 2 \tag{3} ', 'b': ''}]
        for name, data in [('tasks.json', self.tasks),
                           ('m.json', {'tasks': [{'id': 't01', 'latex': r' x^{2} '}]}),
                           ('l.json', {'tasks': [{'id': 'unused', 'latex': 'y'},
                                               {'id': 't01', 'latex': r'x^{2}\prime'}]})]:
            (self.root / name).write_text(json.dumps(data), encoding='utf-8')

    def build(self):
        return build_gold(self.root / 'tasks.json', self.root / 'm.json',
                          self.root / 'l.json', self.root)

    def test_raw_candidates_and_zero_based_page_are_preserved(self):
        record, = self.build()
        self.assertEqual(record['candidates'], {'A': r' x ^ 2 \tag{3} ', 'B': '',
                                                'M': r' x^{2} ', 'L': r'x^{2}\prime'})
        self.assertEqual(record['page'], 2)
        self.assertEqual(record['gold_latex'], '')
        self.assertEqual(record['gold_status'], 'draft')
        self.assertEqual(record['crop'], str((self.root / 'crop.png').resolve()))

    def test_existing_confirmed_gold_cannot_be_overwritten(self):
        out = self.root / 'gold.json'
        human_record = {'gold_status': 'confirmed', 'gold_latex': 'x'}
        write_gold([human_record], out)
        before = out.read_bytes()
        with self.assertRaises(FileExistsError):
            write_gold(self.build(), out)
        self.assertEqual(out.read_bytes(), before)

    def test_missing_saved_candidate_is_not_invented(self):
        (self.root / 'm.json').write_text('{"tasks": []}', encoding='utf-8')
        with self.assertRaises(KeyError):
            self.build()


if __name__ == '__main__':
    unittest.main()
