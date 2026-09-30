"""Layout stage: engine regions -> IR blocks.

Region content that a page_parse engine produced alongside its layout
(MinerU's LaTeX, table HTML, OCR text) is kept as a candidate from that
engine; it is evidence, not the answer. Inline-math regions are kept as
detection proposals for the text stage, which owns inline math.
"""
from __future__ import annotations

from .. import engines, ir
from ..ir import Block, Candidate, Document

_CONTENT_FAMILY = {ir.DISPLAY_MATH: "formula", ir.INLINE_MATH: "formula", ir.TABLE: "table"}


def blocks_from_regions(doc: Document, engine: str, regions: list[dict]) -> list[Block]:
    ordered = sorted(range(len(regions)), key=lambda i: (regions[i]["page"], regions[i]["order"]))
    ids: dict[int, str] = {}
    per_page: dict[int, int] = {}
    blocks = []
    for i in ordered:
        r = regions[i]
        if r["kind"] == ir.INLINE_MATH:
            continue
        n = per_page.get(r["page"], 0)
        per_page[r["page"]] = n + 1
        ids[i] = f"p{r['page']:03d}b{n:03d}"
    for rank, i in enumerate(ordered):
        r = regions[i]
        kind = r["kind"] if r["kind"] in ir.KINDS else ir.OTHER
        parent = ids.get(r.get("parent")) if r.get("parent") is not None else None
        if kind == ir.INLINE_MATH:
            if parent is None:
                continue
            siblings = sum(1 for b in blocks if b.parent == parent)
            block_id = f"{parent}.e{siblings:02d}"
        else:
            block_id = ids[i]
        block = Block(id=block_id, page=r["page"], bbox=[round(v, 2) for v in r["bbox"]], kind=kind,
                      order=float(rank), level=r.get("level", 0), source=engine,
                      extra={"engine_meta": r.get("meta", {})})
        if kind == ir.INLINE_MATH:
            block.parent = parent
            block.extra["proposal"] = True  # replaced by the text stage
        elif kind in (ir.CAPTION, ir.FOOTNOTE) and parent:
            block.links[f"{kind}_of"] = parent
        if r.get("content"):
            fam = engines.family(engine, _CONTENT_FAMILY.get(kind, "text"))
            block.candidates.append(Candidate(engine=engine, family=fam, content=r["content"],
                                              format=r.get("format") or "text"))
        blocks.append(block)
    return blocks


def apply_page_parse(doc: Document, engine: str, output: dict) -> None:
    doc.blocks = blocks_from_regions(doc, engine, output["regions"])
    sizes = {p["page"]: (p["width"], p["height"]) for p in output.get("pages", [])}
    mismatched = [p.index for p in doc.pages if p.index in sizes and
                  (abs(sizes[p.index][0] - p.width) > 1 or abs(sizes[p.index][1] - p.height) > 1)]
    if mismatched:
        raise ValueError(f"{engine} page sizes differ from the PDF on pages {mismatched[:5]}; "
                         "coordinates would not line up")
    doc.metadata["layout_engine"] = engine
    doc.metadata["layout_raw_dir"] = output.get("raw_dir")
