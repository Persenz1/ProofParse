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
            source=b.get("source", ""), extra=b.get("extra") or {}, block_id=b.get("block_id", ""),
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
        b_dict["type"] = b_obj.type
        b_dict["extra"] = b_obj.extra
    data = json.loads((paper_dir / "document.json").read_text(encoding="utf-8"))
    data["blocks"] = block_dicts
    data["metadata"] = vars(doc.metadata)
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
    if choice == "open": return "skipped:open"
    if verdict.get("confidence", 0) < APPLY_CONFIDENCE: return "skipped:low_confidence"
    doc, block_dicts = _load_document(paper_dir)
    by_id = {b.block_id: i for i, b in enumerate(doc.blocks)}
    if item.kind == "page_completeness":
        expected = item.extra["blocks"]
        current = [b for b in doc.blocks if b.page == item.page]
        if [(b.block_id, b.content) for b in current] != [(b["block_id"], b["content"]) for b in expected]:
            return "skipped:stale_page"
        if choice == "parser": return "confirmed"
        if choice != "custom": return "skipped:page_requires_edits"
        edits, inserts = verdict.get("edits", []), verdict.get("inserts", [])
        metadata = verdict.get("metadata", {})
        if not edits and not inserts and not metadata: return "skipped:no_edits"
        if metadata:
            old = json.loads((paper_dir / "document.json").read_text(encoding="utf-8")).get("metadata", {})
            if item.page != 0 or old != item.extra.get("metadata"):
                return "skipped:stale_metadata"
            for key,value in metadata.items():
                valid = ((key in ("title","doi") and isinstance(value,str))
                         or (key == "year" and isinstance(value,int))
                         or (key == "authors" and isinstance(value,list) and all(isinstance(a,str) for a in value)))
                if not valid: return "skipped:invalid_metadata"
        seen = set()
        for edit in edits:
            idx = by_id.get(edit.get("block_id"))
            if idx is None or idx in seen: return "skipped:invalid_edit_target"
            seen.add(idx)
            block = doc.blocks[idx]
            if block.page != item.page or block.content != edit.get("old_content"):
                return "skipped:stale_edit"
            if block.type not in ("paragraph", "heading", "title", "equation", "list", "code"):
                return "skipped:use_visual_task"
            if not isinstance(edit.get("content"), str) or not edit["content"].strip():
                return "skipped:empty_edit"
            if edit.get("type", block.type) not in ("paragraph","heading","title","equation","list","code"):
                return "skipped:invalid_reclassification"
            if "after_block_id" in edit:
                anchor = edit["after_block_id"]
                if anchor is not None and (anchor == block.block_id or anchor not in by_id or doc.blocks[by_id[anchor]].page != item.page):
                    return "skipped:invalid_move_anchor"
        for insert in inserts:
            anchor = insert.get("after_block_id")
            if anchor is not None and (anchor not in by_id or doc.blocks[by_id[anchor]].page != item.page):
                return "skipped:invalid_anchor"
            if insert.get("type") not in ("paragraph", "heading", "equation", "list", "code", "figure", "table"):
                return "skipped:invalid_insert_type"
            bb = insert.get("bbox")
            if (not isinstance(bb, list) or len(bb) != 4 or not all(isinstance(x, (int, float)) and 0 <= x <= 1000 for x in bb)
                    or bb[0] >= bb[2] or bb[1] >= bb[3] or not isinstance(insert.get("content"), str)
                    or (not insert["content"].strip() and insert["type"] not in ("figure", "table"))):
                return "skipped:invalid_insert"
        for key,value in metadata.items(): setattr(doc.metadata,key,value)
        for edit in edits:
            block = doc.blocks[by_id[edit["block_id"]]]
            block.content = edit["content"]
            block.type = edit.get("type",block.type)
        for edit in edits:
            if "after_block_id" not in edit: continue
            index = next(i for i,b in enumerate(doc.blocks) if b.block_id == edit["block_id"])
            block, raw = doc.blocks.pop(index), block_dicts.pop(index)
            anchor = edit["after_block_id"]
            pos = (next(i+1 for i,b in enumerate(doc.blocks) if b.block_id == anchor) if anchor
                   else next((i for i,b in enumerate(doc.blocks) if b.page is not None and b.page >= item.page),len(doc.blocks)))
            doc.blocks.insert(pos,block)
            block_dicts.insert(pos,raw)
        import uuid
        # 逆序插入，使同一 anchor 下按提供顺序排列。
        for insert in reversed(inserts):
            anchor = insert.get("after_block_id")
            pos = next((i+1 for i,b in enumerate(doc.blocks) if b.block_id == anchor), None) if anchor else None
            if pos is None: pos = next((i for i,b in enumerate(doc.blocks) if b.page is not None and b.page >= item.page),len(doc.blocks))
            block = Block(type=insert["type"], content=insert["content"], page=item.page,
                          bbox=insert["bbox"], block_id="insert_"+uuid.uuid4().hex[:12], source="visual_review")
            if block.type in ("figure", "table"):
                from ..pdf.render import render_crop
                rel = f"assets/{block.block_id}.png"
                render_crop(paper_dir / doc.source_pdf, item.page, block.bbox, paper_dir / rel)
                block.extra = {"asset":rel, "caption":insert.get("caption", ""), "structure_verified":False}
            doc.blocks.insert(pos, block)
            block_dicts.insert(pos, block.to_dict() | {"in_markdown": True})
        _save_document(paper_dir, doc, block_dicts)
        return "applied:recheck_page"

    idx = by_id.get(item.block_id)
    if idx is None: return "skipped:block_id_missing"
    block = doc.blocks[idx]
    if block.content != item.extra.get("target_content", block.content): return "skipped:stale_target"
    if item.kind == "visual" and verdict.get("crop_bbox") is not None:
        bb = verdict["crop_bbox"]
        if (choice != "custom" or not isinstance(bb,list) or len(bb) != 4
                or not all(isinstance(x,(int,float)) and 0 <= x <= 1000 for x in bb)
                or bb[0] >= bb[2] or bb[1] >= bb[3]):
            return "skipped:invalid_crop"
        from ..pdf.render import render_crop
        rel = f"assets/{block.block_id}_recrop.png"
        render_crop(paper_dir / doc.source_pdf, item.page, bb, paper_dir / rel)
        block.extra["asset"] = rel
        block.extra["structure_verified"] = False
        block_dicts[idx]["bbox"] = bb
        _save_document(paper_dir, doc, block_dicts)
        return "applied:recheck_crop"
    if choice == "parser":
        if item.kind == "visual" and block.type == "table":
            if not block.content: return "skipped:no_table_structure"
            block.extra["structure_verified"] = True
            _save_document(paper_dir, doc, block_dicts)
            return "applied"
        return "confirmed"
    corrected = item.candidate_b if choice == "ocr" else verdict.get("corrected_latex")
    if not isinstance(corrected, str) or not corrected.strip(): return "skipped:no_corrected_text"
    if item.kind == KIND_INLINE:
        if not item.candidate_a: return "skipped:empty_span"
        matches = list(_flex_pattern(item.candidate_a).finditer(block.content))
        if len(matches) != 1: return "skipped:ambiguous_span"
        m = matches[0]
        block.content = block.content[:m.start()] + corrected + block.content[m.end():]
    elif item.kind == "visual":
        if block.type != "table": return "skipped:recrop_required"
        block.content = corrected
        block.extra["structure_verified"] = True
    else:
        if block.content != item.candidate_a: return "skipped:candidate_not_full_target"
        block.content = corrected
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
    data = json.loads((paper_dir / "document.json").read_text(encoding="utf-8"))
    visuals = {x.get("block_id"):x for x in qc.get("visual_review", [])}
    for b in data["blocks"]:
        if b["type"] in ("figure", "table", "unknown"):
            entry = visuals.get(b.get("block_id"))
            if entry is None:
                entry = {"block_id":b.get("block_id"), "page":b.get("page")}
                qc.setdefault("visual_review", []).append(entry)
            entry.update(bbox=b.get("bbox"), review_asset=b.get("extra", {}).get("asset"))

    for item, verdict, error in results:
        entry = get_entry(qc, item.ref)
        fv: dict = {"reviewed_at": now, "layer": "multimodal"}
        if error:
            fv.update({"status": "error", "error": error})
        else:
            fv.update({
                "status": "resolved" if verdict.get("application") in ("applied", "confirmed") else "open",
                "application": verdict.get("application"),
                "input_hash": verdict.get("input_hash", item.input_hash),
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
    fc = qc.get("formula_check") or {}
    if fc.get("error") or fc.get("status") == "not_run":
        return "still_open"
    for section in ("page_review", "visual_review"):
        pending.extend(x.get("final_verdict") for x in qc.get(section, []))
    for w in qc.get("warnings", []):
        if w.get("status") == "needs_review" and w.get("type") != "unassigned_source":
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
        if fv.get("confidence", 0) < APPLY_CONFIDENCE:
            return "still_open"
    return "reviewed"
