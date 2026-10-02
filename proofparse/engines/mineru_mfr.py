"""Formula recognizers bundled with MinerU: UniMERNet and PP-FormulaNet+.

Runs inside an environment that has MinerU installed. PP-FormulaNet+ L is
not bundled; it runs through Paddle inference with MinerU's pre/post
processing (options.model_dir must point at the exported inference model).
Keep the Paddle backend in its own environment: importing Paddle and PyTorch
CUDA in one process has produced cuDNN conflicts on the test machine.
"""
from __future__ import annotations

from pathlib import Path

INFO: dict = {}

_MINERU_WEIGHTS = {
    "unimernet_small": ("models/MFR/unimernet_hf_small_2503", "unimernet"),
    "pp_formulanet_plus_m": ("models/MFR/pp_formulanet_plus_m", "pp_formulanet"),
}


def _device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _load_images(items):
    import numpy as np
    from PIL import Image
    crops = []
    for item in items:
        with Image.open(item["image"]) as image:
            crops.append(np.array(image.convert("RGB")))
    return crops


def _run_mineru(model: str, items, device: str, batch_size: int,
                input_chunk_size: int = 128) -> list[str]:
    from mineru.utils.models_download_utils import auto_download_and_get_model_root_path
    rel, kind = _MINERU_WEIGHTS[model]
    weights = f"{auto_download_and_get_model_root_path(rel)}/{rel}"
    if kind == "unimernet":
        from mineru.model.mfr.unimernet.Unimernet import UnimernetModel
        recognizer = UnimernetModel(weights, device)
    else:
        from mineru.model.mfr.pp_formulanet_plus_m.predict_formula import FormulaRecognizer
        recognizer = FormulaRecognizer(weights, device)
    INFO.update(weights=weights, input_chunk_size=input_chunk_size, n_chunks=0)
    latex = []
    # MinerU preprocesses and moves its entire input to the GPU before grouping
    # forward calls, so bound that input independently of the forward batch size.
    for offset in range(0, len(items), input_chunk_size):
        crops = _load_images(items[offset:offset + input_chunk_size])
        # Each crop is one full-image formula in MinerU's detection batch API.
        boxes = [[{"label": "display_formula", "bbox": [0, 0, c.shape[1] - 1, c.shape[0] - 1], "latex": ""}]
                 for c in crops]
        results = recognizer.batch_predict(boxes, crops, batch_size=batch_size)
        latex.extend(r[0]["latex"] if r else "" for r in results)
        INFO["n_chunks"] += 1
        del crops
    return latex


def _run_paddle(model_dir: Path, items, batch_size: int) -> list[str]:
    import paddle.inference
    import yaml
    from mineru.model.mfr.pp_formulanet_plus_m.processors import (
        LatexImageFormat, ToBatch, UniMERNetDecode, UniMERNetImgDecode, UniMERNetTestTransform)
    spec = yaml.safe_load((model_dir / "inference.yml").read_text(encoding="utf-8"))
    shape = next(op["UniMERNetImgDecode"]["input_size"] for op in spec["PreProcess"]["transform_ops"]
                 if "UniMERNetImgDecode" in op)
    config = paddle.inference.Config(str(model_dir / "inference.json"), str(model_dir / "inference.pdiparams"))
    config.enable_use_gpu(100, 0)
    config.disable_mkldnn()
    config.disable_glog_info()
    config.enable_new_ir(True)
    config.enable_new_executor()
    predictor = paddle.inference.create_predictor(config)
    transforms = [UniMERNetImgDecode(input_size=tuple(shape)), UniMERNetTestTransform(),
                  LatexImageFormat(), ToBatch()]
    decoder = UniMERNetDecode(character_list=spec["PostProcess"]["character_dict"])
    INFO.update(model_dir=str(model_dir), input_chunk_size=batch_size, n_chunks=0)
    latex = []
    for offset in range(0, len(items), batch_size):
        batch = _load_images(items[offset:offset + batch_size])
        for transform in transforms:
            batch = transform(imgs=batch)
        handle = predictor.get_input_handle(predictor.get_input_names()[0])
        handle.reshape(batch[0].shape)
        handle.copy_from_cpu(batch[0])
        predictor.run()
        prediction = predictor.get_output_handle(predictor.get_output_names()[0]).copy_to_cpu()
        latex.extend(decoder([row.reshape([-1]) for row in prediction]))
        INFO["n_chunks"] += 1
    return latex


def run(job: dict) -> dict:
    if job["task"] != "formula":
        raise ValueError(f"unsupported task {job['task']}")
    options = job["options"]
    items = job["items"]
    if options.get("backend") == "paddle":
        if not options.get("model_dir"):
            raise ValueError(f"{job['engine']}: set engines.{job['engine']}.model_dir in the config")
        latex = _run_paddle(Path(options["model_dir"]), items, job["batch_size"])
    else:
        latex = _run_mineru(options["model"], items, _device(job["device"]), job["batch_size"],
                            int(options.get("input_chunk_size", 128)))
    if len(latex) != len(items):
        raise RuntimeError(f"model returned {len(latex)} results for {len(items)} crops")
    INFO.update(model=options.get("model"), backend=options.get("backend", "mineru"))
    return {item["id"]: {"latex": text} for item, text in zip(items, latex)}
