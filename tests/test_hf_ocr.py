"""Output-format checks for VLM adapters; no models or GPU required."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from proofparse import engines
from proofparse.engines.hf_ocr import INFO, normalize_formula, run


class FormulaOutputTests(unittest.TestCase):
    def test_complete_formula_wrappers(self):
        for raw in (r"$$x^{2}+y$$", r"\[x^{2}+y\]", r"\(x^{2}+y\)",
                    "$x^{2}+y$", "```latex\n$x^{2}+y$\n```", "~~~tex\nx^{2}+y\n~~~"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_formula(raw), ("x^{2}+y", None))

    def test_never_selects_one_formula_from_text_or_multiple_formulas(self):
        for raw in ("The formula is $x$", "$x$ and $y$", r"\[x\]\[y\]",
                    "$$x$$\n\n$$y$$", "```latex\nx\n```\nExplanation", "Here is x=2",
                    "x=2 is the formula", r"\[x", "```latex\nx", "识别结果：x=2"):
            with self.subTest(raw=raw):
                latex, error = normalize_formula(raw)
                self.assertEqual(latex, "")
                self.assertIsNotNone(error)
        self.assertEqual(normalize_formula("x=1\ny=2"), ("", "multiple_unwrapped_formulas"))

    def test_text_arguments_and_aligned_equations_are_preserved(self):
        raw = r"\[\begin{aligned}x&=1\\y&=2\text{ if $z$ is positive}\end{aligned}\]"
        self.assertEqual(normalize_formula(raw), (raw[2:-2], None))
        self.assertEqual(normalize_formula(r"\frac{a}{b} + \mathrm{ABC}"),
                         (r"\frac{a}{b} + \mathrm{ABC}", None))
        raw = r"\[\overline{CNOT}_{A,B}=\bigotimes_{i=1}^{90}CNOT[A_i\to B_i]\]"
        self.assertEqual(normalize_formula(raw), (raw[2:-2], None))

    def test_malformed_latex_is_not_a_candidate(self):
        self.assertEqual(normalize_formula(r"\frac{a"), ("", "invalid_latex:brace_mismatch(1vs0)"))
        self.assertEqual(normalize_formula(""), ("", "empty_output"))

    def test_local_model_dir_required_before_importing_model_libraries(self):
        with self.assertRaisesRegex(ValueError, "existing local model directory"):
            run({"engine": "xiaomi_ocr", "task": "formula", "options": {"model_dir": "missing-local-model"}})

    def test_shared_backbone_is_not_independent_consensus(self):
        self.assertEqual(engines.family("xiaomi_ocr", "formula"), engines.family("ovis_ocr", "formula"))
        self.assertNotEqual(engines.family("xiaomi_ocr", "formula"), engines.family("paddleocr_vl", "formula"))

    def test_worker_preserves_raw_and_moves_floating_inputs_to_model_dtype(self):
        class Features(dict):
            def to(self, **kwargs):
                self.move = kwargs
                return self

        source = MagicMock(size=(640, 100))
        source.__enter__.return_value = source
        image = source.convert.return_value
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True),
                                bfloat16="bfloat16", float32="float32",
                                inference_mode=MagicMock())
        features = Features(input_ids=SimpleNamespace(shape=(1, 7)),
                            image_grid_thw=[SimpleNamespace(tolist=lambda: [1, 8, 20])])
        processor = MagicMock()
        processor.tokenizer.eos_token_id = 248046
        processor.image_processor.patch_size = 16
        processor.apply_chat_template.return_value = features
        processor.batch_decode.return_value = [" $x^{2}$\n"]
        generated = MagicMock()
        generated.__getitem__.return_value.shape = (1, 4)
        model = MagicMock()
        model.to.return_value = model
        model.eval.return_value = model
        model.generate.return_value = generated
        loader = SimpleNamespace(AutoProcessor=MagicMock(), AutoModelForImageTextToText=MagicMock())
        loader.AutoProcessor.from_pretrained.return_value = processor
        loader.AutoModelForImageTextToText.from_pretrained.return_value = model
        model_dir = str(Path(__file__).resolve().parents[1])
        job = {"engine": "xiaomi_ocr", "task": "formula", "options": {"model_dir": model_dir},
               "batch_size": 1, "device": "auto", "items": [{"id": "eq1", "image": "crop.png"}]}
        with patch.dict("sys.modules", {"torch": torch, "transformers": loader}), \
                patch("PIL.Image.open", return_value=source), patch("builtins.print"):
            outputs = run(job)
        self.assertEqual(outputs["eq1"], {"latex": "x^{2}", "raw": " $x^{2}$\n", "output_error": None})
        self.assertEqual(features.move, {"device": "cuda", "dtype": "bfloat16"})
        self.assertTrue(loader.AutoProcessor.from_pretrained.call_args.kwargs["local_files_only"])
        self.assertTrue(loader.AutoModelForImageTextToText.from_pretrained.call_args.kwargs["local_files_only"])
        self.assertFalse(model.generate.call_args.kwargs["do_sample"])
        self.assertEqual(model.generate.call_args.kwargs["eos_token_id"], 248046)
        self.assertEqual(processor.apply_chat_template.call_args.kwargs["processor_kwargs"],
                         {"images_kwargs": {"size": {"shortest_edge": 65536, "longest_edge": 1048576}}})
        self.assertEqual(INFO["items"][0]["processed_size"], [320, 128])
        image.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
