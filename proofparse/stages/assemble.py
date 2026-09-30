"""Assemble the IR into Markdown.

The working view (<paper>.md in the paper directory) carries block ids and
marks every unresolved item. The delivery export writes only Markdown and
images and refuses to ship unresolved formulas unless explicitly allowed;
a formula screenshot is never a substitute for its transcription.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .. import ir
from ..formula.syntax import split_equation
from ..ir import Block, Document
from ..tables import render_table


def _value(block: Block) -> str:
    if block.decision and block.decision.value:
        return block.decision.value
    return next((c.content for c in block.candidates if c.content.strip()), "")


def is_final(block: Block) -> bool:
    return bool(block.decision and block.decision.status in ir.FINAL_STATES)


def blocking(doc: Document) -> list[Block]:
    """Items that must be resolved before delivery."""
    return [b for b in doc.blocks if b.kind in ir.MATH_KINDS and not is_final(b)]


def _number(block: Block) -> str | None:
    assoc = (block.decision.evidence.get("number_association") if block.decision else None) or {}
    if assoc.get("status") == "associated_by_layout":
        return assoc["candidates"][0]["value"]
    return None


def display_latex(block: Block) -> str:
    latex = _value(block).strip()
    body, tags = split_equation(latex)
    number = _number(block)
    if not tags and number:
        latex = f"{body} \\tag{{{number}}}"
    return latex


def prose(doc: Document, block: Block, *, mark: bool) -> str:
    text = block.text if (block.text or block.inline) else _value(block)
    children = iter(doc.children(block))
    out = []
    for piece in text.split(ir.INLINE_SLOT):
        out.append(piece)
        child = next(children, None)
        if child is None:
            continue
        latex = _value(child).strip() or "\\text{?}"
        flag = "" if (is_final(child) or not mark) else f"<!--unresolved {child.id}-->"
        out.append(f"${latex}${flag}")
    return "".join(out).strip()


def _ordered(doc: Document) -> list[Block]:
    """Reading order with captions/footnotes placed after their figure or table."""
    top = [b for b in doc.reading_order() if b.kind != ir.FURNITURE]
    attached: dict[str, list[Block]] = {}
    for b in top:
        owner = b.links.get("caption_of") or b.links.get("footnote_of")
        if owner:
            attached.setdefault(owner, []).append(b)
    result = []
    for b in top:
        if b.links.get("caption_of") or b.links.get("footnote_of"):
            continue
        result.append(b)
        result.extend(attached.get(b.id, []))
    return result


def build_markdown(doc: Document, *, delivery: bool = False, image_dir: str = "assets") -> str:
    lines: list[str] = []
    title = next((b for b in doc.blocks if b.kind == ir.TITLE), None)
    if title:
        lines += ["---", "title: " + json.dumps(prose(doc, title, mark=False), ensure_ascii=False), "---", ""]
    mark = not delivery
    for b in _ordered(doc):
        if mark:
            lines.append(f"<!-- {b.id} p{b.page + 1} {b.kind} -->")
        if b.kind == ir.TITLE:
            lines += [f"# {prose(doc, b, mark=mark)}", ""]
        elif b.kind == ir.HEADING:
            lines += ["#" * min(6, max(2, b.level or 2)) + " " + prose(doc, b, mark=mark), ""]
        elif b.kind == ir.DISPLAY_MATH:
            flag = "" if (is_final(b) or not mark) else f"<!--unresolved {b.id}-->"
            lines += ["$$", display_latex(b), "$$" + flag, ""]
        elif b.kind in (ir.FIGURE, ir.TABLE, ir.ALGORITHM):
            if b.kind == ir.TABLE and is_final(b) and b.decision.value:
                lines += [render_table(b.decision.value), ""]
            elif b.asset:
                name = Path(b.asset).name
                lines += [f"![{b.kind}]({image_dir}/{name})", ""]
        elif b.kind in (ir.CODE,):
            code = b.text or _value(b)
            fence = "`" * max(3, 1 + max((len(m) for m in re.findall(r"`+", code)), default=0))
            lines += [fence, code, fence, ""]
        else:
            text = prose(doc, b, mark=mark)
            if text:
                lines += [text, ""]
    return "\n".join(lines).rstrip() + "\n"


def report(doc: Document) -> dict:
    counts: dict[str, dict[str, int]] = {}
    for b in doc.blocks:
        status = b.decision.status if b.decision else "none"
        counts.setdefault(b.kind, {}).setdefault(status, 0)
        counts[b.kind][status] += 1
    return {
        "counts": counts,
        "blocking": [{"id": b.id, "kind": b.kind, "page": b.page,
                      "status": b.decision.status if b.decision else "none",
                      "rule": b.decision.rule if b.decision else ""} for b in blocking(doc)],
        "pages_with_unassigned_text": [p.index for p in doc.pages
                                       if p.text_layer.get("unassigned_glyphs", 0) > 0],
        "ocr_only_pages": [p.index for p in doc.pages if p.text_layer.get("status") not in ("good", "degraded")],
    }


def write_working(paper) -> Path:
    path = paper.dir / f"{paper.key}.md"
    path.write_text(build_markdown(paper.doc), encoding="utf-8")
    return path


def export(paper, out_root: Path, *, allow_unresolved: bool = False) -> Path:
    pending = blocking(paper.doc)
    if pending and not allow_unresolved:
        raise ValueError(f"{paper.key}: {len(pending)} formulas unresolved "
                         f"(e.g. {', '.join(b.id for b in pending[:5])}); resolve them or pass --allow-unresolved")
    target = Path(out_root) / paper.key
    images = target / "images"
    if target.exists():
        shutil.rmtree(target)
    images.mkdir(parents=True)
    for b in paper.doc.blocks:
        if b.asset and b.kind in (ir.FIGURE, ir.TABLE, ir.ALGORITHM):
            shutil.copy2(paper.dir / b.asset, images / Path(b.asset).name)
    md = target / f"{paper.key}.md"
    md.write_text(build_markdown(paper.doc, delivery=True, image_dir="images"), encoding="utf-8")
    return md
