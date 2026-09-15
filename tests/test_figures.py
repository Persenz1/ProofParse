import unittest
from pathlib import Path
from unittest.mock import patch
from proofparse.models.document import Block, Document
from proofparse.normalize.figures import group_figures
from proofparse.normalize.filtering import apply_filtering


class FigureTests(unittest.TestCase):
    @patch('proofparse.normalize.figures.render_crop')
    def test_panel_title_above_body_is_retained(self, render):
        doc,middle=self.fixture()
        middle['pdf_info'][0]['para_blocks'][0]['blocks'].append(
            {'type':'image_caption','bbox':[220,70,320,85],
             'lines':[{'spans':[{'content':'(b) Projection'}]}]})
        group_figures(doc,middle,Path('source.pdf'),Path('out'))
        self.assertLessEqual(render.call_args.args[2][1],70)

    def fixture(self):
        a=Block('figure','',page=0,bbox=[100,100,200,200],block_id='a')
        b=Block('figure','',page=0,bbox=[220,100,320,200],block_id='b',extra={'caption':'Fig. 1. Two panels.'})
        middle={'pdf_info':[{'page_idx':0,'page_size':[1000,1000],'para_blocks':[
            {'type':'image','bbox':b.bbox,'blocks':[{'type':'image_caption','bbox':[80,210,350,230],
             'lines':[{'spans':[{'content':'Fig. 1. Two panels.'}]}]}]}]}]}
        return Document(blocks=[a,b]),middle

    @patch('proofparse.normalize.figures.render_crop')
    def test_complete_panels_exclude_header(self,render):
        doc,middle=self.fixture()
        doc.blocks.insert(0,Block('dropped','page header',page=0,bbox=[0,80,1000,95],block_id='h'))
        group_figures(doc,middle,Path('source.pdf'),Path('out'))
        kept,_,_=apply_filtering(doc.blocks)
        self.assertEqual([b.block_id for b in kept],['b'])
        self.assertEqual(kept[0].extra['grouped_from'],['a','b'])
        self.assertGreater(render.call_args.args[2][1],95)
        self.assertLess(render.call_args.args[2][3],210)

    @patch('proofparse.normalize.figures.render_crop')
    def test_do_not_merge_across_prose(self,render):
        doc,middle=self.fixture()
        doc.blocks.append(Block('paragraph','prose '*30,page=0,bbox=[80,180,350,205],block_id='text'))
        group_figures(doc,middle,Path('source.pdf'),Path('out'))
        render.assert_not_called()


if __name__=='__main__':unittest.main()
