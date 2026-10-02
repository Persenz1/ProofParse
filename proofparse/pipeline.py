"""Stage-major orchestration over a batch of papers.

Each stage runs for every paper before the next stage starts, so each model
is loaded once per batch. Stage completion is stored in document.json;
re-running resumes where the batch stopped and a re-run stage invalidates
the stages after it for that paper.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import time
import traceback
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from . import engines
from .config import Config
from .engines.runner import run_engine
from .ir import Document, Page
from .preprocess import native
from .preprocess.render import render_page
from .stages import assemble, layout, reconcile, recognize, text

STAGES = ("preprocess", "layout", "text", "recognize", "reconcile", "assemble")


@dataclass
class Paper:
    key: str
    dir: Path
    doc: Document

    @property
    def source_pdf(self) -> Path:
        return self.dir / "source.pdf"

    @property
    def document_path(self) -> Path:
        return self.dir / "document.json"

    def save(self) -> None:
        self.doc.save(self.document_path)

    def done(self, stage: str) -> bool:
        return self.doc.stages.get(stage, {}).get("status") == "done"

    def mark(self, stage: str, **info) -> None:
        self.doc.stages[stage] = {"status": "done", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), **info}
        for later in STAGES[STAGES.index(stage) + 1:]:
            self.doc.stages.pop(later, None)

    def page_chars(self) -> dict[int, list[dict]]:
        return {p.index: native.load_page(self.dir / "native", p.index)["characters"] for p in self.doc.pages}


def paper_key(pdf: Path) -> str:
    stem = unicodedata.normalize("NFKC", pdf.stem)
    key = re.sub(r"[^\w.\-]+", "_", stem, flags=re.ASCII).strip("._")
    return key or "paper"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def open_papers(inputs: list[Path], out: Path, *, force: bool = False) -> list[Paper]:
    papers, seen = [], {}
    for pdf in inputs:
        key = paper_key(pdf)
        if key in seen:
            raise ValueError(f"{pdf} and {seen[key]} map to the same output name {key!r}")
        seen[key] = pdf
        folder = out / key
        digest = sha256(pdf)
        doc_path = folder / "document.json"
        if doc_path.is_file() and not force:
            doc = Document.load(doc_path)
            if doc.source.get("sha256") != digest:
                raise ValueError(f"{folder} holds a different PDF with the same name; use another output "
                                 "directory or --force")
        else:
            if folder.exists():
                shutil.rmtree(folder)
            folder.mkdir(parents=True)
            shutil.copy2(pdf, folder / "source.pdf")
            doc = Document(source={"path": str(pdf), "sha256": digest})
        papers.append(Paper(key, folder, doc))
    return papers


def load_papers(out: Path) -> list[Paper]:
    return [Paper(p.parent.name, p.parent, Document.load(p)) for p in sorted(Path(out).glob("*/document.json"))]


# ------------------------------------------------------------------ stages

def stage_preprocess(papers, cfg, work, log):
    for paper in papers:
        pages = native.extract(paper.source_pdf, paper.dir / "native")
        paper.doc.pages = [Page(index=p["index"], width=p["width"], height=p["height"],
                                rotation=p["rotation"], text_layer=p["text_layer"]) for p in pages]
        paper.doc.source["n_pages"] = len(pages)
        statuses = {}
        for p in pages:
            statuses[p["text_layer"]["status"]] = statuses.get(p["text_layer"]["status"], 0) + 1
        paper.mark("preprocess", text_layer=statuses)


def stage_layout(papers, cfg, work, log):
    spec = engines.get(cfg.layout)
    if "page_parse" in spec.tasks:
        items = [{"id": p.key, "pdf": str(p.source_pdf)} for p in papers]
        outputs, info = run_engine(cfg, cfg.layout, "page_parse", items, work, log=log)
    elif "layout" in spec.tasks:
        scale = float(cfg.engine(cfg.layout).options.get("page_scale", 1.5))
        items, owners = [], {}
        for paper in papers:
            for page in paper.doc.pages:
                item_id = f"{paper.key}/p{page.index:03d}"
                image = render_page(paper.source_pdf, page.index,
                                    paper.dir / "pages" / f"p{page.index:03d}.png", scale)
                items.append({"id": item_id, "image": str(image), "scale": scale})
                owners[item_id] = (paper.key, page.index)
        page_outputs, info = run_engine(cfg, cfg.layout, "layout", items, work, log=log)
        outputs = {paper.key: {"regions": []} for paper in papers}
        for item_id, output in page_outputs.items():
            key, page = owners[item_id]
            regions = outputs[key]["regions"]
            offset = len(regions)
            for region in output["regions"]:
                region = dict(region, page=page)
                if region.get("parent") is not None:
                    region["parent"] += offset
                regions.append(region)
    else:
        raise ValueError(f"engine {cfg.layout} does not provide layout or page_parse")
    for paper in papers:
        layout.apply_page_parse(paper.doc, cfg.layout, outputs[paper.key])
        paper.mark("layout", engine=cfg.layout, seconds=info.seconds, cached=info.n_cached > 0)


def stage_text(papers, cfg, work, log):
    for paper in papers:
        diagnostics = text.run(paper.doc, paper.page_chars())
        unassigned = sum(d["unassigned_glyphs"] for d in diagnostics.values())
        paper.mark("text", unassigned_glyphs=unassigned)


def stage_recognize(papers, cfg, work, log):
    infos = recognize.run(papers, cfg, work, log=log)
    for paper in papers:
        paper.mark("recognize", engines=[i.engine for i in infos])
    return infos


def stage_reconcile(papers, cfg, work, log):
    for paper in papers:
        counts = reconcile.run(paper.doc, paper.page_chars(), cfg.formula_order)
        paper.mark("reconcile", decisions=counts)


def stage_assemble(papers, cfg, work, log):
    for paper in papers:
        path = assemble.write_working(paper)
        rep = assemble.report(paper.doc)
        paper.mark("assemble", blocking=len(rep["blocking"]), markdown=path.name)


_RUN = {"preprocess": stage_preprocess, "layout": stage_layout, "text": stage_text,
        "recognize": stage_recognize, "reconcile": stage_reconcile, "assemble": stage_assemble}


def stage_config_key(stage: str, cfg: Config) -> str | None:
    """Only model-dependent stages need invalidation when the user changes settings."""
    if stage == "layout":
        settings = [cfg.layout, asdict(cfg.engine(cfg.layout))]
    elif stage == "recognize":
        settings = [cfg.formula, cfg.formula_fallback, cfg.render_scale,
                    [asdict(cfg.engine(name)) for name in cfg.formula_order]]
    elif stage == "reconcile":
        settings = cfg.formula_order
    else:
        return None
    import json
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16]


def run(papers: list[Paper], cfg: Config, work: Path, *, stages=STAGES, force: bool = False,
        log=print) -> dict[str, str]:
    """Run stages over papers; a failing paper is reported and skipped, not fatal."""
    failed: dict[str, str] = {}
    for stage in STAGES:
        if stage not in stages:
            continue
        config_key = stage_config_key(stage, cfg)
        todo = [p for p in papers if p.key not in failed and
                (force or not p.done(stage) or
                 (config_key is not None and
                  p.doc.stages[stage].get("config_key") != config_key))]
        if not todo:
            continue
        log(f"[stage] {stage}: {len(todo)} paper(s)")
        try:
            _RUN[stage](todo, cfg, work, log)
        except Exception as exc:
            if len(todo) == 1 or stage in ("layout", "recognize"):
                # batched engine stages fail as a whole; record for every paper in the batch
                for p in todo:
                    failed[p.key] = f"{stage}: {type(exc).__name__}: {exc}"
                    (p.dir / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
                log(f"[fail] {stage}: {exc}")
            else:
                for p in todo:  # retry one by one to isolate the broken paper
                    try:
                        _RUN[stage]([p], cfg, work, log)
                    except Exception as one:
                        failed[p.key] = f"{stage}: {type(one).__name__}: {one}"
                        (p.dir / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
                        log(f"[fail] {p.key} {stage}: {one}")
        for p in todo:
            if p.key in failed:
                p.doc.stages[stage] = {"status": "failed", "error": failed[p.key]}
            elif config_key is not None:
                p.doc.stages[stage]["config_key"] = config_key
            p.save()
    return failed
