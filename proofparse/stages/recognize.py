"""Recognition stage: crop regions from the source PDF and collect candidates.

Crops come from our own render of the source page, never from an engine's
intermediate images, so every recogniser sees the same pixels. Engines run
once per stage over all papers (see runner.py).
"""
from __future__ import annotations

from pathlib import Path

from .. import engines, ir
from ..config import Config
from ..engines.runner import RunInfo, run_engine
from ..formula.output import content as formula_content
from ..ir import Candidate
from ..preprocess.render import crop_fragments, crop_regions
from . import reconcile

MATH_PAD_PT = 1.5
# Keep accent/overline space vertically; adjacent prose begins immediately
# beside inline glyphs, so keep the horizontal margin below a PDF point.
INLINE_PAD_PT = (0.25, 1.5)
ASSET_PAD_PT = 2.0


def render_crops(paper, scale: float) -> dict[str, Path]:
    """Math crops for recognisers and image assets for figures/tables."""
    doc = paper.doc
    jobs, fragments = [], []
    for b in doc.blocks:
        if b.kind in ir.MATH_KINDS:
            pad = 0.0 if b.extra.get("crop_regions") else (
                INLINE_PAD_PT if b.kind == ir.INLINE_MATH else MATH_PAD_PT)
            job = (b, paper.dir / "crops" / f"{b.id}.png", pad)
            (fragments if b.extra.get("crop_regions") else jobs).append(job)
        elif b.kind in (ir.FIGURE, ir.TABLE, ir.ALGORITHM):
            jobs.append((b, paper.dir / "assets" / f"{b.id}.png", ASSET_PAD_PT))
    crop_regions(paper.source_pdf, [(b.page, b.bbox, path, pad) for b, path, pad in jobs], scale)
    crop_fragments(paper.source_pdf, [(b.page, b.extra["crop_regions"], b.extra["crop_baselines"], path, pad)
                                     for b, path, pad in fragments], scale)
    crops = {}
    for b, path, _ in jobs + fragments:
        if b.kind in ir.MATH_KINDS:
            crops[b.id] = path
        else:
            b.asset = path.relative_to(paper.dir).as_posix()
    return crops


def run(papers, cfg: Config, work: Path, log=print) -> list[RunInfo]:
    items, owners = [], {}
    recognizers = {name for name, spec in engines.REGISTRY.items() if "formula" in spec.tasks}
    for paper in papers:
        for block in paper.doc.blocks:
            if block.kind in ir.MATH_KINDS:
                block.candidates = [c for c in block.candidates if c.engine not in recognizers]
        crops = render_crops(paper, cfg.render_scale)
        for b in paper.doc.blocks:
            if b.id in crops:
                item_id = f"{paper.key}/{b.id}"
                items.append({"id": item_id, "image": str(crops[b.id]),
                              "kind": "inline" if b.kind == ir.INLINE_MATH else "display"})
                owners[item_id] = b
    infos = []
    page_chars = None
    for name in cfg.formula_order:
        if "formula" not in engines.get(name).tasks:
            continue  # page_parse engines already contributed during layout
        selected = items
        if name in cfg.formula_fallback:
            if page_chars is None:
                page_chars = {paper.key: paper.page_chars() for paper in papers}
            for paper in papers:
                reconcile.run(paper.doc, page_chars[paper.key], cfg.formula_order)
            selected = [item for item in items if not owners[item["id"]].decision or
                        owners[item["id"]].decision.status not in ir.FINAL_STATES]
            if not selected:
                continue
        outputs, info = run_engine(cfg, name, "formula", selected, work, log=log)
        fam = engines.family(name, "formula")
        for item_id, output in outputs.items():
            latex, error = formula_content(output)
            owners[item_id].set_candidate(Candidate(engine=name, family=fam,
                                                    content=latex, format="latex",
                                                    meta={k: v for k, v in output.items() if k != "latex"}
                                                         | {"output_error": error}))
        infos.append(info)
    return infos
