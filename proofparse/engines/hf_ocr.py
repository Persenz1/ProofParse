"""Local Transformers formula adapters for Xiaomi-OCR-0, OvisOCR2 and PaddleOCR-VL.

One model is loaded per worker; crops are processed individually for 8 GB GPUs.
The model's decoded response is retained as ``raw`` even when it cannot safely
be used as one formula. ``options.prompt`` and the pixel/token limits can be
varied in the benchmark without changing the adapter.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import time

from ..formula.output import normalize_formula

INFO: dict = {}

# Official model cards / Xiaomi's pipeline/twostage_img2md.py. Ovis publishes
# a page prompt rather than a region-specific formula prompt; retain it here
# as the reproducible initial baseline, even when the input is a formula crop.
PROFILES = {
    "xiaomi_ocr": {
        "prompt": "Identify the formula in the image and represent it using LATEX format.",
        "prompt_source": "https://github.com/SeerRay-Lab/Xiaomi-OCR-0/blob/main/pipeline/twostage_img2md.py",
        "min_pixels": 65536,
        "max_pixels": 1048576,
        "max_new_tokens": 2048,
    },
    "paddleocr_vl": {
        "prompt": "Formula Recognition:",
        "prompt_source": "https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/blob/main/README.md",
        "min_pixels": 112896,
        "max_pixels": 1280 * 28 * 28,
        "max_new_tokens": 2048,
    },
    "ovis_ocr": {
        "prompt": (
            '\nExtract all readable content from the image in natural human reading order '
            'and output the result as a single Markdown document. For charts or images, '
            'represent them using an HTML image tag: <img src="images/bbox_{left}_{top}_{right}_{bottom}.jpg" />, '
            'where left, top, right, bottom are bounding box coordinates scaled to [0, 1000). '
            'Format formulas as LaTeX. Format tables as HTML: <table>...</table>. '
            'Transcribe all other text as standard Markdown. Preserve the original text '
            'without translation or paraphrasing.'
        ),
        "prompt_source": "https://huggingface.co/ATH-MaaS/OvisOCR2/blob/main/README.md",
        "min_pixels": 448 * 448,
        "max_pixels": 1048576,
        "max_new_tokens": 2048,
    },
}

def _versions() -> dict[str, str | None]:
    packages = {}
    for name in ("torch", "transformers", "torchvision", "pillow"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return packages


def run(job: dict) -> dict:
    if job["task"] != "formula":
        raise ValueError(f"unsupported task {job['task']}")
    options = {**PROFILES[job["engine"]], **job["options"]}
    if not options.get("model_dir") or not Path(options["model_dir"]).is_dir():
        raise ValueError(f"{job['engine']}: options.model_dir must be an existing local model directory")
    model_dir = str(Path(options["model_dir"]).resolve())
    if job["batch_size"] != 1:
        raise ValueError(f"{job['engine']}: set batch_size = 1 for individual crop inference")

    import torch
    from PIL import Image
    from transformers import AutoModelForImageTextToText, AutoProcessor

    device = job["device"]
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
    attention = options.get("attn_implementation", "sdpa")
    max_new_tokens = int(options["max_new_tokens"])
    image_size = {"shortest_edge": int(options["min_pixels"]),
                  "longest_edge": int(options["max_pixels"])}
    INFO.clear()
    INFO.update(model_dir=model_dir, device=device, dtype=str(dtype), batch_size=1,
                prompt=options["prompt"], prompt_source=options["prompt_source"],
                prompt_overridden="prompt" in job["options"],
                image_size=image_size, max_new_tokens=max_new_tokens,
                attn_implementation=attention, do_sample=False, num_beams=1,
                local_files_only=True, versions=_versions(), items=[])
    processor = AutoProcessor.from_pretrained(model_dir, local_files_only=True)
    # Ovis' text config names <|endoftext|>, while its chat tokenizer ends
    # responses with <|im_end|>. Use the tokenizer's response terminator.
    eos_token_id = processor.tokenizer.eos_token_id
    INFO["eos_token_id"] = eos_token_id
    model = AutoModelForImageTextToText.from_pretrained(
        model_dir, local_files_only=True, dtype=dtype, attn_implementation=attention,
    ).to(device).eval()
    patch_size = int(processor.image_processor.patch_size)
    outputs = {}
    for item in job["items"]:
        started = time.perf_counter()
        with Image.open(item["image"]) as source:
            source_size = list(source.size)
            image = source.convert("RGB")
        messages = [{"role": "user", "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": options["prompt"]},
        ]}]
        inputs = processor.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True,
            return_dict=True, return_tensors="pt",
            **({"enable_thinking": False} if job["engine"] != "paddleocr_vl" else {}),
            processor_kwargs={"images_kwargs": {"size": image_size}},
        ).to(device=device, dtype=dtype)
        image.close()
        input_tokens = inputs["input_ids"].shape[-1]
        grid = inputs["image_grid_thw"][0].tolist()
        with torch.inference_mode():
            generated = model.generate(**inputs, max_new_tokens=max_new_tokens,
                                       do_sample=False, num_beams=1, use_cache=True,
                                       eos_token_id=eos_token_id)
        new_tokens = generated[:, input_tokens:]
        raw = processor.batch_decode(new_tokens, skip_special_tokens=True,
                                     clean_up_tokenization_spaces=False)[0]
        latex, error = normalize_formula(raw)
        if new_tokens.shape[-1] >= max_new_tokens:
            latex, error = "", "token_limit_reached"
        outputs[item["id"]] = {"latex": latex, "raw": raw, "output_error": error}
        INFO["items"].append({
            "id": item["id"], "source_size": source_size,
            "processed_size": [grid[2] * patch_size, grid[1] * patch_size],
            "image_grid_thw": grid, "input_tokens": input_tokens,
            "generated_tokens": new_tokens.shape[-1], "output_error": error,
            "seconds": round(time.perf_counter() - started, 3),
        })
        print(f"[{job['engine']}] {item['id']}: {new_tokens.shape[-1]} tokens, "
              f"{INFO['items'][-1]['seconds']:.3f}s, {error or 'formula'}", flush=True)
    return outputs
