"""裁决结果写回 qc.json，并把确认的正确答案应用到 <name>.md。

应用策略（保守）：
- choice=parser：确认解析器正确，md 无需改动；
- choice=ocr/custom 且 confidence >= 阈值：替换 document.json 中对应块内容后重建 md；
- 其余（低置信 / 裁决失败）：不改 md，条目标记为 still_open 交给人工。

定位规则：
- formula_display：qc 条目带 block_index，直接定位 document.json 块；
- formula_inline：按 page + parser 候选（空白柔性匹配）定位段落块并替换首个命中；
- text_warning：parser_text 是段落前缀，按页 + 前缀匹配定位，
  choice=ocr 时用 missing_text 换前缀，choice=custom 时用 corrected_latex 换前缀。
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..models.document import Block, Document, Metadata
from ..normalize.markdown import build_markdown
from .collect import KIND_DISPLAY, KIND_INLINE, KIND_TEXT, ReviewItem, get_entry

APPLY_CONFIDENCE = 0.7


def _flex_pattern(candidate: str) -> re.Pattern:
    """候选串 -> 正则：非空白字符转义，原有空白匹配套 \\s*。"""
    parts = [re.escape(tok) for tok in re.split(r"\s+", candidate.strip()) if tok]
    return re.compile(r"\s*".join(parts))


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _load_document(paper_dir: Path) -> tuple[Document, list[dict]]:
    data = json.loads((paper_dir / "document.json").read_text(encoding="utf-8"))
    md = data.get("metadata") or {}
    doc = Document(
        metadata=Metadata(**{k: md.get(k) for k in ("title", "authors", "year", "doi")}),
        source_pdf=data.get("source_pdf", ""),
        parser=data.get("parser") or {},
    )
    for b in data.get("blocks", []):
        doc.blocks.append(Block(
            type=b["type"], content=b.get("content", ""), page=b.get("page"),
            bbox=b.get("bbox"), level=b.get("level", 0),
            source=b.get("source", ""), extra=b.get("extra") or {},
        ))
    return doc, data["blocks"]


def _save_document(paper_dir: Path, doc: Document, block_dicts: list[dict]) -> None:
    """同步块内容回 dict 列表并落盘（保留 in_markdown 等附加字段）。

    首次修改前把当前 document.json 备份为 document.json.bak（一次性，
    不覆盖已有备份），保证终审改动永远可回滚。
    """
    bak = paper_dir / "document.json.bak"
    if not bak.exists():
        shutil.copy2(paper_dir / "document.json", bak)
    for b_dict, b_obj in zip(block_dicts, doc.blocks):
        b_dict["content"] = b_obj.content
    data = json.loads((paper_dir / "document.json").read_text(encoding="utf-8"))
    data["blocks"] = block_dicts
    (paper_dir / "document.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def rebuild_markdown(paper_dir: Path) -> Path:
    """用 document.json 当前块内容重建 <name>.md（只输出 in_markdown 块）。"""
    paper_dir = Path(paper_dir)
    doc, block_dicts = _load_document(paper_dir)
    kept = [b for b, d in zip(doc.blocks, block_dicts) if d.get("in_markdown")]
    md_path = paper_dir / f"{paper_dir.name}.md"
    md_path.write_text(build_markdown(doc, kept), encoding="utf-8")
    return md_path


def apply_to_document(paper_dir: Path, item: ReviewItem, verdict: dict) -> str:
    """把裁决应用到 document.json 块内容。返回 applied / confirmed / skipped:<原因>。"""
    choice = verdict["choice"]
    if choice == "parser":
        return "confirmed"  # 解析器本就正确，无需改动

    corrected = verdict.get("corrected_latex")
    if choice == "ocr":
        corrected = item.candidate_b
    if not corrected:
        return "skipped:no_corrected_text"
    if verdict.get("confidence", 0.0) < APPLY_CONFIDENCE:
        return f"skipped:confidence<{APPLY_CONFIDENCE}"

    doc, block_dicts = _load_document(paper_dir)

    if item.kind == KIND_DISPLAY:
        idx = item.block_index
        if idx is None or idx >= len(doc.blocks):
            return "skipped:block_index_missing"
        doc.blocks[idx].content = corrected.strip()
    elif item.kind == KIND_INLINE:
        pat = _flex_pattern(item.candidate_a)
        hit = False
        for b in doc.blocks:
            if b.page != item.page or not b.content:
                continue
            if pat.search(b.content):
                b.content = pat.sub(lambda m: corrected, b.content, count=1)
                hit = True
                break
        if not hit:
            return "skipped:span_not_found"
    else:  # KIND_TEXT：段落前缀替换
        prefix = item.candidate_a.strip()
        pat = _flex_pattern(prefix)
        hit = False
        for b in doc.blocks:
            if b.page != item.page or not b.content:
                continue
            if _norm(b.content).startswith(_norm(prefix)[:40]):
                b.content = pat.sub(lambda m: corrected, b.content, count=1)
                hit = True
                break
        if not hit:
            return "skipped:paragraph_not_found"

    _save_document(paper_dir, doc, block_dicts)
    return "applied"


def write_verdicts(paper_dir: Path, results: list[tuple[ReviewItem, Optional[dict], Optional[str]]]) -> dict:
    """把裁决写回 qc.json（每条加 final_verdict），并同步警告内嵌的 formula_spans。

    results: (item, verdict or None, error or None)
    返回更新后的 qc dict。
    """
    paper_dir = Path(paper_dir)
    qc_path = paper_dir / "qc.json"
    qc = json.loads(qc_path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for item, verdict, error in results:
        entry = get_entry(qc, item.ref)
        fv: dict = {"reviewed_at": now, "layer": "multimodal"}
        if error:
            fv.update({"status": "error", "error": error})
        else:
            fv.update({
                "status": "resolved" if verdict["choice"] in ("parser", "ocr", "custom") else "open",
                **{k: verdict[k] for k in ("choice", "corrected_latex", "confidence", "reason", "model")},
            })
        entry["final_verdict"] = fv

        # inline 裁决同步到 warnings[*].formula_spans 中同 page+bbox 的条目
        if item.kind == KIND_INLINE and verdict:
            for w in qc.get("warnings", []):
                if w.get("page") != item.page:
                    continue
                for s in w.get("formula_spans", []):
                    if s.get("verdict") == "REVIEW" and s.get("bbox") == item.bbox:
                        s["final_verdict"] = fv

    qc_path.write_text(json.dumps(qc, ensure_ascii=False, indent=2), encoding="utf-8")
    return qc


def paper_status(qc: dict) -> str:
    """auto_pass / reviewed / still_open。"""
    pending = []
    for w in qc.get("warnings", []):
        if w.get("status") == "needs_review":
            pending.append(w.get("final_verdict"))
    fc = qc.get("formula_check") or {}
    for kind in ("display", "inline"):
        for r in fc.get(kind, []):
            if r.get("verdict") == "REVIEW":
                pending.append(r.get("final_verdict"))
    if not pending:
        return "auto_pass"
    for fv in pending:
        if not fv or fv.get("status") != "resolved":
            return "still_open"
        if fv.get("choice") not in ("parser", "ocr", "custom"):
            return "still_open"
        if fv.get("choice") != "parser" and fv.get("confidence", 0) < APPLY_CONFIDENCE:
            return "still_open"
    return "reviewed"
