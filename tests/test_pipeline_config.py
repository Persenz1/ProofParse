"""Resuming after model changes must rerun the dependent stages."""
import unittest
from pathlib import Path
from unittest.mock import patch

from proofparse import pipeline
from proofparse.config import Config, EngineConfig
from proofparse.ir import Document, Page
from proofparse.engines.runner import RunInfo


class PipelineConfigTests(unittest.TestCase):
    def test_model_change_resumes_recognition_and_downstream_stages(self):
        cfg = Config(formula=["first"])
        doc = Document(stages={stage: {"status": "done"} for stage in pipeline.STAGES})
        for stage in ("layout", "recognize", "reconcile"):
            doc.stages[stage]["config_key"] = pipeline.stage_config_key(stage, cfg)
        paper = pipeline.Paper("paper", Path("output/test-pipeline-config"), doc)
        calls = []

        def stage(name):
            def apply(papers, cfg, work, log):
                calls.append(name)
                for p in papers:
                    p.mark(name)
            return apply

        with patch.object(paper, "save"), patch.dict(pipeline._RUN,
                {name: stage(name) for name in pipeline.STAGES}):
            pipeline.run([paper], cfg, Path("output"), log=lambda _: None)
            self.assertEqual(calls, [])
            cfg.formula = ["second"]
            pipeline.run([paper], cfg, Path("output"), log=lambda _: None)
        self.assertEqual(calls, ["recognize", "reconcile", "assemble"])

    def test_layout_settings_change_invalidates_layout(self):
        cfg = Config(engines={"mineru_pipeline": EngineConfig("mineru_pipeline")})
        key = pipeline.stage_config_key("layout", cfg)
        cfg.engines["mineru_pipeline"].options["page_scale"] = 2.0
        self.assertNotEqual(key, pipeline.stage_config_key("layout", cfg))

    def test_page_local_inline_parents_stay_on_their_own_page(self):
        cfg = Config(layout="pp_doclayout_v3")
        doc = Document(pages=[Page(0, 200, 300), Page(1, 200, 300)])
        paper = pipeline.Paper("paper", Path("output/test-layout"), doc)
        page_output = {"regions": [
            {"bbox": [10, 10, 90, 30], "kind": "text", "order": 1},
            {"bbox": [40, 15, 50, 25], "kind": "inline_math", "order": 2, "parent": 0}]}
        result = {f"paper/p{page:03d}": page_output for page in (0, 1)}
        with patch.object(pipeline, "render_page", return_value=Path("output/page.png")), \
             patch.object(pipeline, "run_engine", return_value=(result,
                 RunInfo("pp_doclayout_v3", "layout", 2, 0))):
            pipeline.stage_layout([paper], cfg, Path("output/work"), lambda _: None)
        children = [block for block in doc.blocks if block.kind == "inline_math"]
        self.assertEqual([(block.page, block.parent) for block in children],
                         [(0, "p000b000"), (1, "p001b000")])


if __name__ == "__main__":
    unittest.main()
