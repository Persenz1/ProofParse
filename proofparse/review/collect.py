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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

KIND_TEXT = "text_warning"
KIND_DISPLAY = "formula_display"
KIND_INLINE = "formula_inline"


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
    block_index: Optional[int] = None    # 仅 formula_display
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def uid(self) -> str:
        return f"{self.paper}::{'/'.join(map(str, self.ref))}"


def _collect_from_qc(paper: str, qc: dict) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for i, w in enumerate(qc.get("warnings", [])):
        if w.get("status") != "needs_review":
            continue
        items.append(ReviewItem(
            paper=paper, kind=KIND_TEXT, ref=("warnings", i),
            page=w.get("page"), bbox=w.get("bbox"),
            candidate_a=w.get("parser_text", ""),
            candidate_b=w.get("missing_text", ""),
            label_a="parser", label_b="pdf_text_layer",
            likely_cause=w.get("likely_cause", ""),
            review_asset=w.get("review_asset"),
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
                extra={"similarity": r.get("similarity")},
            ))
    return items


def _enrich_text_candidate(paper_dir: Path, item: ReviewItem) -> None:
    """text_warning 的 parser_text 是被 qc 截断的前缀，用它裁决会冤枉解析器。

    从 document.json 找回该段落的完整内容替换候选 A（按页 + 前缀匹配）。
    """
    if item.kind != KIND_TEXT or not item.candidate_a:
        return
    doc_path = paper_dir / "document.json"
    if not doc_path.exists():
        return
    try:
        data = json.loads(doc_path.read_text(encoding="utf-8"))
    except Exception:
        return
    prefix = re.sub(r"\s+", "", item.candidate_a)[:40]
    if not prefix:
        return
    for b in data.get("blocks", []):
        if b.get("page") != item.page:
            continue
        if re.sub(r"\s+", "", b.get("content") or "").startswith(prefix):
            item.candidate_a = b["content"]
            return


def collect(output_root: Path, skip_done: bool = True) -> list[ReviewItem]:
    """扫描 output_root 下所有论文目录，返回待裁决清单。

    skip_done=True 时跳过已有 final_verdict 的条目（幂等重跑）。
    """
    output_root = Path(output_root)
    items: list[ReviewItem] = []
    for qc_path in sorted(output_root.glob("*/qc.json")):
        paper = qc_path.parent.name
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
        for it in _collect_from_qc(paper, qc):
            if skip_done:
                entry = get_entry(qc, it.ref)
                fv = entry.get("final_verdict")
                if fv and fv.get("status") == "resolved":
                    continue  # 已成功裁决的跳过；error 状态的重裁
            _enrich_text_candidate(qc_path.parent, it)
            items.append(it)
    return items


def get_entry(qc: dict, ref: tuple) -> dict:
    entry = qc
    for k in ref:
        entry = entry[k]
    return entry
