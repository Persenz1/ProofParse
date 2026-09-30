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
from ..ir import Candidate
from ..preprocess.render import crop_regions

MATH_PAD_PT = 1.5
ASSET_PAD_PT = 2.0


def render_crops(paper, scale: float) -> dict[str, Path]:
    """Math crops for recognisers and image assets for figures/tables."""
    doc = paper.doc
    jobs = []
    for b in doc.blocks:
        if b.kind in ir.MATH_KINDS:
            jobs.append((b, paper.dir / "crops" / f"{b.id}.png", MATH_PAD_PT))
        elif b.kind in (ir.FIGURE, ir.TABLE, ir.ALGORITHM):
            jobs.append((b, paper.dir / "assets" / f"{b.id}.png", ASSET_PAD_PT))
    crop_regions(paper.source_pdf, [(b.page, b.bbox, path, pad) for b, path, pad in jobs], scale)
    crops = {}
    for b, path, _ in jobs:
        if b.kind in ir.MATH_KINDS:
            crops[b.id] = path
        else:
            b.asset = path.relative_to(paper.dir).as_posix()
    return crops


def run(papers, cfg: Config, work: Path, log=print) -> list[RunInfo]:
    items, owners = [], {}
    for paper in papers:
        crops = render_crops(paper, cfg.render_scale)
        for b in paper.doc.blocks:
            if b.id in crops:
                item_id = f"{paper.key}/{b.id}"
                items.append({"id": item_id, "image": str(crops[b.id]),
                              "kind": "inline" if b.kind == ir.INLINE_MATH else "display"})
                owners[item_id] = b
    infos = []
    for name in cfg.formula:
        if "formula" not in engines.get(name).tasks:
            continue  # page_parse engines already contributed during layout
        outputs, info = run_engine(cfg, name, "formula", items, work, log=log)
        fam = engines.family(name, "formula")
        for item_id, output in outputs.items():
            owners[item_id].set_candidate(Candidate(engine=name, family=fam,
                                                    content=output.get("latex", ""), format="latex"))
        infos.append(info)
    return infos
