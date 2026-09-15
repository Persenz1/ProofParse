"""Regression cases for actual data-loss and review-state bugs (no OCR model required)."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from proofparse.models.document import Block, Document
from proofparse.parsers.mineru_parser import MinerUParser
from proofparse.normalize.filtering import apply_filtering
from proofparse.normalize.markdown import build_markdown
from proofparse.normalize.tables import render_table
from proofparse.formula.compare import verdict
from proofparse.review.apply import apply_to_document, paper_status
from proofparse.review.collect import collect
from proofparse.review.review import export_worklist, run_review
from proofparse.review.agent import FileVLM


class CoreTests(unittest.TestCase):
    def test_delimiters_must_stay_in_same_scope(self):
        from proofparse.formula.qc import check_latex
        self.assertTrue(check_latex(r'\begin{array}{ll}{\left(0}&{1\right)}\end{array}'))
        self.assertTrue(check_latex(r'\begin{array}{ll}\left(0&1\right)\end{array}'))
        self.assertEqual(check_latex(r'\left(\begin{array}{ll}0&1\\2&3\end{array}\right)'),[])

    def test_orphan_equation_number_and_correction(self):
        from proofparse.normalize.coverage import check_orphan_equation_numbers
        from proofparse.review.collect import _collect_from_qc
        number = Block('paragraph', '(4)', page=0, bbox=[906,640,928,652], block_id='eq4')
        warnings = check_orphan_equation_numbers([number])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]['bbox'][0], 0)
        equation = Block('equation', 'x=y', page=0, bbox=[60,639,300,653])
        self.assertEqual(check_orphan_equation_numbers([number,equation]), [])
        self.dump('document.json', {'blocks':[number.to_dict() | {'in_markdown':True}]})
        item = _collect_from_qc('paper', {'warnings':warnings})[0]
        latex = r'\delta W_{\mathrm{in}}=-M\delta\alpha\tag{4}'
        self.assertEqual(apply_to_document(self.paper,item,{'choice':'custom','confidence':1,'corrected_latex':latex}), 'applied')
        saved = json.loads((self.paper/'document.json').read_text())['blocks'][0]
        self.assertEqual(saved['type'], 'equation')
        from proofparse.review.apply import _load_document
        doc, _ = _load_document(self.paper)
        self.assertIn('$$\n'+latex+'\n$$', build_markdown(doc, doc.blocks))

    def test_figure_caption_below_image(self):
        figure = Block('figure','',extra={'asset':'images/a.png','caption':'Fig. 1. Example.'})
        md = build_markdown(Document(),[figure],delivery=True)
        self.assertLess(md.index('![原图]'),md.index('Fig. 1.'))

    def setUp(self):
        root = os.environ.get("PROOFPARSE_TEST_TMP")
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.paper = self.root / "paper"
        self.paper.mkdir()
        (self.paper / "crop.png").write_bytes(b"fixture")

    def dump(self, name, value):
        (self.paper / name).write_text(json.dumps(value), encoding="utf-8")

    def fixture(self, content="x+1"):
        self.dump("document.json", {"pdf_sha256":"fixture", "blocks":[
            {"block_id":"header", "type":"dropped", "content":"header", "page":0},
            {"block_id":"prose", "type":"paragraph", "content":"keep me", "page":0, "in_markdown":True},
            {"block_id":"eq", "type":"equation", "content":content, "page":0, "in_markdown":True}]})
        self.dump("qc.json", {"formula_check":{"display":[{"verdict":"REVIEW", "block_id":"eq", "block_index":1,
                   "page":0, "parser":content, "formula_ocr":"x-1", "review_asset":"crop.png"}]}})

    def test_math_structure_not_similarity(self):
        for a,b in [(r"x^{12}",r"x^12"), (r"\mathbf{x}","x"),
                    (r"\begin{matrix}a&b\\c&d\end{matrix}",r"\begin{matrix}a&b&c&d\end{matrix}"),
                    ("a+b+c+d+e+f", "a+b-c+d+e+f")]:
            self.assertEqual(verdict(a,b)[0], "REVIEW")
        self.assertEqual(verdict("$$x+1$$", "x+1")[0], "PASS")

    def test_stable_id_and_long_candidate(self):
        self.fixture("x+"*300+"1")
        item=collect(self.root)[0]
        self.assertGreater(len(item.candidate_a),300)
        result=apply_to_document(self.paper,item,{"choice":"ocr", "confidence":.95})
        self.assertEqual(result,"applied")
        blocks=json.loads((self.paper/"document.json").read_text())["blocks"]
        self.assertEqual(blocks[1]["content"],"keep me")
        self.assertEqual(blocks[2]["content"],"x-1")
        self.assertEqual(apply_to_document(self.paper,item,{"choice":"parser","confidence":.95}),"skipped:stale_target")

    def test_review_hash_resume_and_open(self):
        self.fixture()
        item=collect(self.root)[0]
        path=self.root/"verdicts.json"
        path.write_text(json.dumps({item.uid:{"choice":"parser","confidence":.2,"input_hash":item.input_hash}}))
        self.assertEqual(run_review(self.root,FileVLM(path),verbose=False)["paper"]["status"],"still_open")
        self.assertEqual(len(collect(self.root)),1)
        path.write_text(json.dumps({item.uid:{"choice":"ocr","confidence":.95,"input_hash":item.input_hash}}))
        self.assertEqual(run_review(self.root,FileVLM(path),verbose=False)["paper"]["status"],"reviewed")
        self.assertFalse(collect(self.root))
        self.assertIn("x-1",(self.paper/"paper.md").read_text())
        (self.paper/"crop.png").write_bytes(b"changed crop")
        changed=collect(self.root)[0]
        with self.assertRaises(ValueError): FileVLM(path).adjudicate(changed,None)

    def test_missing_formula_check_not_pass(self):
        self.assertEqual(paper_status({"formula_check":{"error":"failed"}}),"still_open")
        self.assertEqual(paper_status({"formula_check":{"status":"not_run"}}),"still_open")

    def test_complete_adapter_and_output(self):
        parser=MinerUParser()
        records=[{"type":"text","text":"References","text_level":2},
                 {"type":"list","list_items":["[1] First", "[2] Second"]},
                 {"type":"text","text":"Appendix","text_level":2},
                 {"type":"image","image_caption":["Figure 1"],"image_footnote":["note"]},
                 {"type":"code","code_body":"for x in y:\n    f(x)"},
                 {"type":"page_footnote","text":"useful footnote"}]
        blocks=[parser._convert_block(x) for x in records]
        self.assertEqual(len(apply_filtering(blocks)[0]),len(blocks))
        doc=Document(blocks=blocks)
        md=build_markdown(doc,blocks)
        for text in ["References","[2] Second","Appendix","Figure 1","    f(x)","useful footnote"]:
            self.assertIn(text,md)

    def test_table_is_image_until_verified(self):
        html="<table><tr><td>A</td><td>B</td></tr><tr><td>1.00</td><td>-2</td></tr></table>"
        b=Block(type="table",content=html,extra={"asset":"assets/table.png"})
        self.assertNotIn("1.00",build_markdown(Document(),[b]))
        b.extra["structure_verified"]=True
        self.assertIn("| 1.00 | -2 |",build_markdown(Document(),[b]))
        self.assertNotIn("alert",render_table(html+"<script>alert(1)</script>"))
        self.assertIn("<table>",render_table("<table><tr><td>1</td><td>0</td></tr><tr><td>0</td><td>1</td></tr></table>"))

    def test_ocr_missing_results_are_error(self):
        import numpy as np
        from proofparse.formula.recognizer import FormulaOCR
        ocr=object.__new__(FormulaOCR)
        class EmptyModel:
            def batch_predict(self,*args,**kwargs): return []
        ocr.model=EmptyModel()
        with self.assertRaises(RuntimeError): ocr.recognize([np.zeros((10,10,3))])

    def test_api_resume_does_not_resubmit_saved_response(self):
        import io
        from proofparse.review.api import APIReviewer
        self.fixture()
        item=collect(self.root)[0]
        response={"choices":[{"finish_reason":"stop","message":{"content":json.dumps({item.uid:{
            "choice":"parser","confidence":.95,"input_hash":item.input_hash}})}}],"usage":{"total_tokens":10}}
        with patch.dict(os.environ,{"PROOFPARSE_REVIEW_API_KEY":"test-only"}):
            with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as call:
                api=APIReviewer(self.root,'https://example.invalid/v1','test-model',1)
                self.assertEqual(api.adjudicate(item,self.paper/'crop.png')['choice'],'parser')
                again=APIReviewer(self.root,'https://example.invalid/v1','test-model',1)
                self.assertEqual(again.adjudicate(item,self.paper/'crop.png')['choice'],'parser')
                self.assertEqual(call.call_count,1)

    def test_page_insert_and_recheck(self):
        self.fixture()
        qc=json.loads((self.paper/"qc.json").read_text())
        qc["page_review"]=[{"page":0,"review_asset":"crop.png"}]
        self.dump("qc.json",qc)
        item=next(x for x in collect(self.root) if x.kind=="page_completeness")
        result=apply_to_document(self.paper,item,{"choice":"custom","confidence":.95,
             "inserts":[{"after_block_id":"prose","type":"paragraph","content":"Missing paragraph","bbox":[1,1,50,50]}]})
        self.assertEqual(result,"applied:recheck_page")
        blocks=json.loads((self.paper/"document.json").read_text())["blocks"]
        self.assertEqual(blocks[2]["content"],"Missing paragraph")
        self.assertEqual(apply_to_document(self.paper,item,{"choice":"parser","confidence":.95}),"skipped:stale_page")

    def test_metadata_correction_requires_first_page(self):
        self.fixture()
        qc=json.loads((self.paper/"qc.json").read_text())
        qc["page_review"]=[{"page":0,"review_asset":"crop.png"}]
        self.dump("qc.json",qc)
        item=next(x for x in collect(self.root) if x.kind=="page_completeness")
        result=apply_to_document(self.paper,item,{"choice":"custom","confidence":.95,"metadata":{"title":"Actual title"}})
        self.assertEqual(result,"applied:recheck_page")
        self.assertEqual(json.loads((self.paper/"document.json").read_text())["metadata"]["title"],"Actual title")

    def test_later_table_edit_invalidates_page_confirmation(self):
        self.dump('document.json',{'blocks':[{'block_id':'t','type':'table','content':'old','page':0,
                   'extra':{'asset':'crop.png'},'in_markdown':True}]})
        self.dump('qc.json',{'page_review':[{'page':0,'review_asset':'crop.png'}],
                            'visual_review':[{'page':0,'block_id':'t','review_asset':'crop.png'}]})
        decisions={}
        for item in collect(self.root):
            decisions[item.uid]={'input_hash':item.input_hash,'confidence':.95,
                                 'choice':'parser' if item.kind=='page_completeness' else 'custom',
                                 'corrected_latex':'<table><tr><td>new</td></tr></table>'}
        path=self.root/'verdicts.json';path.write_text(json.dumps(decisions))
        summary=run_review(self.root,FileVLM(path),verbose=False)
        self.assertEqual(summary['paper']['status'],'still_open')
        self.assertEqual([i.kind for i in collect(self.root)],['page_completeness'])

    def test_caption_edit_does_not_verify_table_values(self):
        self.dump('document.json',{'blocks':[{'block_id':'t','type':'table','content':'unverified table',
                   'page':0,'extra':{'asset':'crop.png'},'in_markdown':True}]})
        self.dump('qc.json',{'visual_review':[{'page':0,'block_id':'t','review_asset':'crop.png'}]})
        item=collect(self.root)[0]
        result=apply_to_document(self.paper,item,{'choice':'custom','confidence':.95,'caption':'Table 1. Correct title.'})
        self.assertEqual(result,'applied:recheck_table')


if __name__ == "__main__": unittest.main()
