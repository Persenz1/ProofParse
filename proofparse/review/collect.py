"""收集终审清单：扫描 output_root/*/qc.json，挑出需要多模态裁决的条目。

三类条目：
- text_warning     qc["warnings"][i]，status == "needs_review"
                   双候选：missing_text（PDF 文字层）/ parser_text（解析器）
- formula_display  qc["formula_check"]["display"][i]，verdict == "REVIEW"
                   双候选：parser / formula_ocr；有 block_index 可直接定位块
- formula_inline   qc["formula_check"]["inline"][i]，verdict == "REVIEW"
                   双候选：parser / formula_ocr；按 page+parser 候选定位段落块

每个 ReviewItem 携带 ref（写回 qc.json 的路径），保证裁决结果能精确落回原条目。
"""
from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

KIND_TEXT = "text_warning"
KIND_DISPLAY = "formula_display"
KIND_INLINE = "formula_inline"
KIND_PAGE = "page_completeness"
KIND_VISUAL = "visual"


@dataclass
class ReviewItem:
    paper: str                 # 论文目录名
    kind: str                  # KIND_*
    ref: tuple                 # 写回路径，如 ("warnings", 3) / ("formula_check", "display", 2)
    page: Optional[int]
    bbox: Optional[list]
    candidate_a: str           # parser 侧
    candidate_b: str           # 另一侧（ocr / 文字层）
    label_a: str = "parser"
    label_b: str = "ocr"
    likely_cause: str = ""
    review_asset: Optional[str] = None   # 相对论文目录
    block_index: Optional[int] = None    # legacy
    block_id: str | None = None
    input_hash: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def uid(self) -> str:
        return f"{self.paper}::{'/'.join(map(str, self.ref))}"


def _collect_from_qc(paper: str, qc: dict) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for i, w in enumerate(qc.get("warnings", [])):
        if w.get("status") != "needs_review" or w.get("type") == "unassigned_source":
            continue
        items.append(ReviewItem(
            paper=paper, kind=KIND_DISPLAY if w.get("type") == "latex_sanity" else KIND_TEXT, ref=("warnings", i),
            page=w.get("page"), bbox=w.get("bbox"),
            candidate_a=w.get("parser_text", ""),
            candidate_b=w.get("missing_text", ""),
            label_a="parser", label_b="pdf_text_layer",
            likely_cause=w.get("likely_cause", ""),
            review_asset=w.get("review_asset"),
            block_id=w.get("block_id"),
            extra={"warning_id": w.get("id", ""), "similarity": w.get("similarity")},
        ))
    fc = qc.get("formula_check") or {}
    for kind_key, kind in (("display", KIND_DISPLAY), ("inline", KIND_INLINE)):
        for i, r in enumerate(fc.get(kind_key, [])):
            if r.get("verdict") != "REVIEW":
                continue
            items.append(ReviewItem(
                paper=paper, kind=kind, ref=("formula_check", kind_key, i),
                page=r.get("page"), bbox=r.get("bbox"),
                candidate_a=r.get("parser", ""),
                candidate_b=r.get("formula_ocr", ""),
                label_a="parser", label_b="formula_ocr",
                review_asset=r.get("review_asset"),
                block_index=r.get("block_index"),
                block_id=r.get("block_id"),
                extra={"similarity": r.get("similarity")},
            ))
    return items


def collect(output_root: Path, skip_done: bool = True) -> list[ReviewItem]:
    items = []
    for qc_path in sorted(Path(output_root).glob("*/qc.json")):
        paper_dir = qc_path.parent
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
        doc = json.loads((paper_dir / "document.json").read_text(encoding="utf-8"))
        blocks = {b.get("block_id"): b for b in doc["blocks"]}
        paper_items = _collect_from_qc(paper_dir.name, qc)
        for section, kind in (("page_review", KIND_PAGE), ("visual_review", KIND_VISUAL)):
            for i, entry in enumerate(qc.get(section, [])):
                block = blocks.get(entry.get("block_id"), {})
                paper_items.append(ReviewItem(
                    paper=paper_dir.name, kind=kind, ref=(section, i),
                    page=entry.get("page"), bbox=entry.get("bbox"),
                    candidate_a=block.get("content", ""), candidate_b="",
                    review_asset=entry.get("review_asset"), block_id=entry.get("block_id"),
                    extra={"type": block.get("type"), "caption": block.get("extra", {}).get("caption", "")}))
        for it in paper_items:
            if it.kind == KIND_PAGE:
                if it.page == 0:
                    it.extra["metadata"] = doc.get("metadata", {})
                it.extra["unassigned_source"] = [w.get("missing_text") for w in qc.get("warnings", []) if w.get("type") == "unassigned_source" and w.get("page") == it.page]
                # 上游会跨页合并段落，并在下一页留下空块；给审阅者相邻上下文，避免重复补写。
                previous = [b for b in doc["blocks"] if b.get("page") == it.page-1 and b["type"] in ("paragraph", "list")]
                following = [b for b in doc["blocks"] if b.get("page") == it.page+1 and b["type"] in ("paragraph", "list")]
                it.extra["boundary_context"] = [{k:b.get(k) for k in ("block_id", "page", "content")}
                                                for b in previous[-1:] + following[:1]]
                it.extra["blocks"] = [
                    {k: b.get(k) for k in ("block_id", "type", "content", "bbox", "in_markdown")}
                    | {"caption": b.get("extra", {}).get("caption", ""), "footnote": b.get("extra", {}).get("footnote", "")}
                    for b in doc["blocks"] if b.get("page") == it.page]
            block = blocks.get(it.block_id)
            if block:
                it.extra["target_content"] = block.get("content", "")
            asset = paper_dir / it.review_asset if it.review_asset else None
            evidence = {"pdf": doc.get("pdf_sha256"), "kind": it.kind, "page": it.page,
                        "a": it.candidate_a, "b": it.candidate_b, "block": it.block_id,
                        "extra": it.extra, "bbox": it.bbox,
                        "image": hashlib.sha256(asset.read_bytes()).hexdigest() if asset and asset.is_file() else None}
            it.input_hash = hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            fv = get_entry(qc, it.ref).get("final_verdict") or {}
            if skip_done and fv.get("status") == "resolved" and fv.get("input_hash") == it.input_hash:
                continue
            items.append(it)
    return items


def get_entry(qc: dict, ref: tuple) -> dict:
    entry = qc
    for k in ref:
        entry = entry[k]
    return entry
