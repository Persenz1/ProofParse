"""Bound image residency without loading a model again or losing item order."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from proofparse.engines import mineru_mfr


class MFRChunkingTests(unittest.TestCase):
    def test_mineru_model_is_loaded_once_and_chunk_results_keep_item_order(self):
        for count, options, expected_sizes in (
                (257, {}, [128, 128, 1]),
                (7, {"input_chunk_size": 3}, [3, 3, 1])):
            with self.subTest(options=options):
                items = [{"id": f"eq{i}", "image": f"crop{i}.png"} for i in range(count)]
                loaded = []

                def load_images(chunk):
                    loaded.append([item["id"] for item in chunk])
                    return [SimpleNamespace(key=item["id"], shape=(12, 20, 3)) for item in chunk]

                recognizer = MagicMock()
                recognizer.batch_predict.side_effect = lambda boxes, crops, **kwargs: [
                    [{"latex": f"latex:{crop.key}"}] for crop in crops]
                constructor = MagicMock(return_value=recognizer)
                modules = {
                    "mineru.utils.models_download_utils": SimpleNamespace(
                        auto_download_and_get_model_root_path=lambda _: "weights"),
                    "mineru.model.mfr.pp_formulanet_plus_m.predict_formula": SimpleNamespace(
                        FormulaRecognizer=constructor),
                }
                job = {"engine": "pp_formulanet_plus_m", "task": "formula", "device": "cpu",
                       "batch_size": 8, "items": items,
                       "options": {"model": "pp_formulanet_plus_m", **options}}
                with patch.dict("sys.modules", modules), \
                        patch.object(mineru_mfr, "_load_images", side_effect=load_images):
                    outputs = mineru_mfr.run(job)

                constructor.assert_called_once_with("weights/models/MFR/pp_formulanet_plus_m", "cpu")
                self.assertEqual([len(chunk) for chunk in loaded], expected_sizes)
                self.assertEqual([key for chunk in loaded for key in chunk],
                                 [item["id"] for item in items])
                self.assertEqual(list(outputs), [item["id"] for item in items])
                self.assertEqual([value["latex"] for value in outputs.values()],
                                 [f"latex:{item['id']}" for item in items])
                self.assertEqual(recognizer.batch_predict.call_count, len(expected_sizes))
                for call in recognizer.batch_predict.call_args_list:
                    self.assertEqual(call.kwargs, {"batch_size": 8})
                    self.assertEqual(call.args[0], [[{"label": "display_formula",
                                                      "bbox": [0, 0, 19, 11], "latex": ""}]
                                                   for _ in call.args[1]])
                self.assertEqual(mineru_mfr.INFO["input_chunk_size"], options.get("input_chunk_size", 128))
                self.assertEqual(mineru_mfr.INFO["n_chunks"], len(expected_sizes))
                self.assertEqual(mineru_mfr.INFO["model"], "pp_formulanet_plus_m")
                self.assertEqual(mineru_mfr.INFO["backend"], "mineru")

    def test_paddle_loads_only_each_batch_and_keeps_partial_tail(self):
        items = [{"id": f"eq{i}", "image": f"crop{i}.png"} for i in range(5)]
        loaded = []
        active = []

        def load_images(chunk):
            active[:] = [item["id"] for item in chunk]
            loaded.append(active.copy())
            return [SimpleNamespace(key=key) for key in active]

        predictor = MagicMock()
        predictor.get_input_names.return_value = ["image"]
        predictor.get_output_names.return_value = ["result"]
        predictor.get_output_handle.return_value.copy_to_cpu.side_effect = lambda: [
            SimpleNamespace(reshape=lambda _, key=key: key) for key in active]
        inference = SimpleNamespace(Config=MagicMock(),
                                    create_predictor=MagicMock(return_value=predictor))
        identity = lambda **kwargs: kwargs["imgs"]
        processors = SimpleNamespace(
            UniMERNetImgDecode=MagicMock(return_value=identity),
            UniMERNetTestTransform=MagicMock(return_value=identity),
            LatexImageFormat=MagicMock(return_value=identity),
            ToBatch=MagicMock(return_value=lambda **kwargs: [SimpleNamespace(shape=(len(kwargs["imgs"]), 1))]),
            UniMERNetDecode=MagicMock(return_value=lambda rows: [f"latex:{key}" for key in rows]),
        )
        spec = {"PreProcess": {"transform_ops": [{"UniMERNetImgDecode": {"input_size": [384, 384]}}]},
                "PostProcess": {"character_dict": ["x"]}}
        modules = {"paddle": SimpleNamespace(inference=inference), "paddle.inference": inference,
                   "yaml": SimpleNamespace(safe_load=lambda _: spec),
                   "mineru.model.mfr.pp_formulanet_plus_m.processors": processors}
        job = {"engine": "pp_formulanet_plus_l", "task": "formula", "device": "cpu",
               "batch_size": 2, "items": items,
               "options": {"backend": "paddle", "model_dir": "local-model"}}
        with patch.dict("sys.modules", modules), \
                patch.object(Path, "read_text", return_value="mock model spec"), \
                patch.object(mineru_mfr, "_load_images", side_effect=load_images):
            outputs = mineru_mfr.run(job)

        inference.Config.assert_called_once()
        inference.create_predictor.assert_called_once()
        self.assertEqual(loaded, [["eq0", "eq1"], ["eq2", "eq3"], ["eq4"]])
        self.assertEqual(list(outputs), [item["id"] for item in items])
        self.assertEqual([value["latex"] for value in outputs.values()],
                         [f"latex:{item['id']}" for item in items])
        self.assertEqual(predictor.run.call_count, 3)
        self.assertEqual(mineru_mfr.INFO["input_chunk_size"], 2)
        self.assertEqual(mineru_mfr.INFO["n_chunks"], 3)
        self.assertEqual(mineru_mfr.INFO["backend"], "paddle")


if __name__ == "__main__":
    unittest.main()
