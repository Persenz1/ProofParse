"""PP-DocLayoutV3 layout detection in an isolated PaddleX worker.

PaddleX 3.7.2 returns ``boxes`` in model reading order. Coordinates and
polygons are in input-image pixels, converted here to displayed-page points.
The postprocessor's ordering is preserved; no geometric reading-order sort
or caption association is added.
"""
from __future__ import annotations

from pathlib import Path

from .. import ir

INFO: dict = {}

_KINDS = {
    "abstract": ir.TEXT,
    "algorithm": ir.ALGORITHM,
    "aside_text": ir.FURNITURE,
    "chart": ir.FIGURE,
    "content": ir.TEXT,
    "display_formula": ir.DISPLAY_MATH,
    "doc_title": ir.TITLE,
    "figure_title": ir.CAPTION,
    "footer": ir.FURNITURE,
    "footer_image": ir.FURNITURE,
    "footnote": ir.FOOTNOTE,
    "formula_number": ir.TEXT,
    "header": ir.FURNITURE,
    "header_image": ir.FURNITURE,
    "image": ir.FIGURE,
    "inline_formula": ir.INLINE_MATH,
    "number": ir.FURNITURE,
    "paragraph_title": ir.HEADING,
    "reference": ir.HEADING,
    "reference_content": ir.REFERENCE,
    "seal": ir.FIGURE,
    "table": ir.TABLE,
    "text": ir.TEXT,
    "vertical_text": ir.TEXT,
    "vision_footnote": ir.CAPTION,
}


def convert(result: dict, scale: float) -> dict:
    """PaddleX result -> regions; preserve the detector's independent math boxes."""
    boxes = result["boxes"]
    # With skipped labels, numeric orders omit figures/captions. The complete
    # list still has the model order, so use its sequence for every region.
    use_sequence = any(box.get("order") is None for box in boxes)
    regions = []
    for index, box in enumerate(boxes):
        label = box["label"]
        model_order = box.get("order")
        meta = {"orig_type": label, "score": float(box["score"]),
                "class_id": int(box["cls_id"]),
                "model_order": float(model_order) if model_order is not None else None}
        polygon = box.get("polygon_points")
        if polygon is not None:
            meta["polygon_pt"] = [[float(x) / scale, float(y) / scale] for x, y in polygon]
        if label == "formula_number":
            meta["formula_number"] = True
        region = {"bbox": [float(v) / scale for v in box["coordinate"]],
                  "kind": _KINDS.get(label, ir.OTHER),
                  "order": float(index + 1 if use_sequence else model_order), "meta": meta}
        if region["kind"] in (ir.TITLE, ir.HEADING):
            region["level"] = 1 if region["kind"] == ir.TITLE else 2
        regions.append(region)

    for region in regions:
        if region["kind"] != ir.INLINE_MATH:
            continue
        x0, y0, x1, y1 = region["bbox"]
        enclosing = [(index, owner) for index, owner in enumerate(regions)
                     if owner["kind"] in ir.PROSE_KINDS
                     and owner["bbox"][0] <= x0 and owner["bbox"][1] <= y0
                     and owner["bbox"][2] >= x1 and owner["bbox"][3] >= y1]
        if enclosing:
            index, _ = min(enclosing, key=lambda pair: (pair[1]["bbox"][2] - pair[1]["bbox"][0])
                           * (pair[1]["bbox"][3] - pair[1]["bbox"][1]))
            region["parent"] = index
        else:
            region["kind"] = ir.OTHER
            region["meta"]["orphan_inline"] = True
    return {"regions": regions}


def run(job: dict) -> dict:
    if job["task"] != "layout":
        raise ValueError(f"unsupported task {job['task']}")
    import paddle
    import paddlex

    options = job["options"]
    model_name = "PP-DocLayoutV3"
    model_dir = str(Path(options["model_dir"]).resolve())
    device = job["device"]
    if device == "auto":
        device = "gpu:0" if paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() else "cpu"
    elif device.startswith("cuda"):
        device = device.replace("cuda", "gpu", 1)
    model = paddlex.create_model(model_name=model_name, model_dir=model_dir, device=device)
    predict_options = {"layout_shape_mode": options.get("layout_shape_mode", "auto"),
                       "skip_order_labels": options.get("skip_order_labels", [])}
    for key in ("threshold", "layout_nms", "layout_unclip_ratio", "layout_merge_bboxes_mode",
                "filter_overlap_boxes"):
        if key in options:
            predict_options[key] = options[key]
    INFO.update(paddlex_version=paddlex.__version__, paddle_version=paddle.__version__,
                model_name=model_name, model_dir=model_dir, device=device,
                batch_size=job["batch_size"], predict_options=predict_options)
    predictions = model.predict([item["image"] for item in job["items"]],
                                batch_size=job["batch_size"], **predict_options)
    return {item["id"]: convert(result, item["scale"])
            for item, result in zip(job["items"], predictions)}
