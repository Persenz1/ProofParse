"""公式双识别编排：display equation 全量复核 + math_divergence 段落的行内公式复核。

数据源：
- display equation：Document 块（content_list 空间，1000 归一化 bbox）
- inline equation：MinerU middle.json 的 span（PDF 点空间 bbox），
  只复核落在 math_divergence 警告段落内的 span

结果写回 qc.json：
- formula_check.display / formula_check.inline 全量比对记录
- math_divergence 警告若全部 span PASS，状态升级为 auto_pass
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium

from ..models.document import BLOCK_EQUATION, BLOCK_PARAGRAPH, Block
from .compare import verdict
from .recognizer import get_formula_ocr

RENDER_SCALE = 3.0


def _render_pages(pdf_path: Path, page_idxs: set[int]) -> dict[int, np.ndarray]:
    pdf = pdfium.PdfDocument(str(pdf_path))
    pages: dict[int, np.ndarray] = {}
    for i in sorted(page_idxs):
        img = pdf[i].render(scale=RENDER_SCALE).to_pil()
        pages[i] = np.array(img.convert("RGB"))
    pdf.close()
    return pages


def _page_size_pt(pdf_path: Path, page_idx: int) -> tuple[float, float]:
    pdf = pdfium.PdfDocument(str(pdf_path))
    w, h = pdf[page_idx].get_size()
    pdf.close()
    return w, h


def _crop(img: np.ndarray, x1: float, y1: float, x2: float, y2: float,
          pad: int = 4) -> np.ndarray:
    h, w = img.shape[:2]
    return img[max(0, int(y1) - pad):min(h, int(y2) + pad),
               max(0, int(x1) - pad):min(w, int(x2) + pad)]


def _load_inline_spans(middle_json: Path) -> list[dict]:
    """从 middle.json 提取全部 inline_equation span：(page, bbox_pt, content)。"""
    spans: list[dict] = []
    data = json.loads(middle_json.read_text(encoding="utf-8"))

    def walk(o, page_idx):
        if isinstance(o, dict):
            if o.get("type") == "inline_equation" and o.get("bbox") and o.get("content"):
                spans.append({"page": page_idx, "bbox": o["bbox"],
                              "content": o["content"], "score": o.get("score")})
            for v in o.values():
                walk(v, page_idx)
        elif isinstance(o, list):
            for v in o:
                walk(v, page_idx)

    for page in data.get("pdf_info", []):
        walk(page.get("para_blocks", []), page.get("page_idx"))
    return spans


def double_check(pdf_path: Path, out_dir: Path, kept_blocks: list[Block],
                 qc: dict, device: str = "cuda") -> None:
    """就地更新 qc dict。任何模型/IO 异常都不应中断主流程。"""
    stem = pdf_path.stem
    middle_candidates = sorted(
        out_dir.glob(f"_mineru_raw/**/{stem}_middle.json"))
    inline_spans = _load_inline_spans(middle_candidates[0]) if middle_candidates else []

    eq_blocks = [b for b in kept_blocks if b.type == BLOCK_EQUATION]
    math_warns = [w for w in qc["warnings"]
                  if w.get("likely_cause") == "math_divergence"]

    # 收集要渲染的页面
    pages_needed = {b.page for b in eq_blocks if b.page is not None}
    for w in math_warns:
        if w.get("page") is not None:
            pages_needed.add(w["page"])
    if not pages_needed:
        qc["formula_check"] = {"display": [], "inline": []}
        return

    ocr = get_formula_ocr(device)
    rendered = _render_pages(pdf_path, pages_needed)

    # ---- display equations 全量双识别 ----
    display_records = []
    crops, owners = [], []
    for i, b in enumerate(kept_blocks):
        if b.type != BLOCK_EQUATION or b.page is None or not b.bbox:
            continue
        img = rendered[b.page]
        ph_pt = img.shape[0] / RENDER_SCALE  # 页面高（pt）
        pw_pt = img.shape[1] / RENDER_SCALE
        x1 = b.bbox[0] / 1000 * pw_pt * RENDER_SCALE
        y1 = b.bbox[1] / 1000 * ph_pt * RENDER_SCALE
        x2 = b.bbox[2] / 1000 * pw_pt * RENDER_SCALE
        y2 = b.bbox[3] / 1000 * ph_pt * RENDER_SCALE
        crops.append(_crop(img, x1, y1, x2, y2))
        owners.append((i, b))
    latex_list = ocr.recognize(crops) if crops else []
    for (i, b), ocr_latex in zip(owners, latex_list):
        v, sim = verdict(b.content, ocr_latex)
        display_records.append({
            "block_index": i, "page": b.page, "bbox": b.bbox,
            "verdict": v, "similarity": sim,
            "parser": b.content[:300], "formula_ocr": ocr_latex[:300],
        })

    # ---- math_divergence 段落的 inline span 复核 ----
    # span bbox 是 PDF 点；段落 bbox 是 1000 归一化 —— 统一到点
    inline_records = []
    for w in math_warns:
        page = w["page"]
        pbbox = w.get("bbox")
        if pbbox is None:
            continue
        pw_pt, ph_pt = _page_size_pt(pdf_path, page)
        px1, py1 = pbbox[0] / 1000 * pw_pt, pbbox[1] / 1000 * ph_pt
        px2, py2 = pbbox[2] / 1000 * pw_pt, pbbox[3] / 1000 * ph_pt

        spans = [s for s in inline_spans if s["page"] == page
                 and px1 <= (s["bbox"][0] + s["bbox"][2]) / 2 <= px2
                 and py1 <= (s["bbox"][1] + s["bbox"][3]) / 2 <= py2]
        if not spans:
            continue
        img = rendered[page]
        crops = [_crop(img, s["bbox"][0] * RENDER_SCALE, s["bbox"][1] * RENDER_SCALE,
                       s["bbox"][2] * RENDER_SCALE, s["bbox"][3] * RENDER_SCALE)
                 for s in spans]
        latex_list = ocr.recognize(crops)
        span_results = []
        for s, ocr_latex in zip(spans, latex_list):
            v, sim = verdict(s["content"], ocr_latex)
            span_results.append({"bbox": s["bbox"], "verdict": v, "similarity": sim,
                                 "parser": s["content"][:200],
                                 "formula_ocr": ocr_latex[:200]})
            inline_records.append({"page": page, **span_results[-1]})
        w["formula_spans"] = span_results
        # 该段落全部行内公式双识别一致 -> 表示分歧，升级为 auto_pass
        if all(r["verdict"] == "PASS" for r in span_results):
            w["status"] = "auto_pass"
            w["resolution"] = "all_inline_spans_passed_double_check"

    # ---- 汇总 ----
    n_eq_review = sum(1 for r in display_records if r["verdict"] == "REVIEW")
    qc["formula_check"] = {
        "model": ocr.model_name,
        "display": display_records,
        "inline": inline_records,
        "n_display_checked": len(display_records),
        "n_display_review": n_eq_review,
        "n_inline_checked": len(inline_records),
        "n_inline_review": sum(1 for r in inline_records if r["verdict"] == "REVIEW"),
    }
    remaining = [w for w in qc["warnings"] if w.get("status") == "needs_review"]
    qc["summary"]["status"] = "needs_review" if remaining else "auto_pass"
    qc["summary"]["n_needs_review"] = len(remaining)
