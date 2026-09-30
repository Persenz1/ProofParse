"""MinerU pipeline as a page_parse engine (baseline and first layout source).

Runs the mineru CLI once for the whole batch, then converts each paper's
middle.json (PDF points, per-page reading order, caption and inline-math
spans) into regions. content_list.json is not used: it loses caption boxes
and inline math positions.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

INFO: dict = {}

_KINDS = {
    "text": "text", "abstract": "text", "index": "text", "list": "list", "ref_text": "reference",
    "interline_equation": "display_math", "image": "figure", "chart": "figure", "table": "table",
    "code": "code", "algorithm": "algorithm", "page_footnote": "footnote",
    "header": "furniture", "footer": "furniture", "page_number": "furniture", "aside_text": "furniture",
}


def _mineru_exe(options: dict) -> str:
    if options.get("mineru_exe"):
        return options["mineru_exe"]
    folder = Path(sys.executable).parent
    for candidate in (folder / "Scripts" / "mineru.exe", folder / "mineru.exe", folder / "mineru"):
        if candidate.is_file():
            return str(candidate)
    return "mineru"


def _device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _version(exe: str) -> str:
    try:
        out = subprocess.run([exe, "-v"], capture_output=True, text=True, timeout=120)
        return (out.stdout + out.stderr).strip().splitlines()[-1]
    except Exception:
        return "unknown"


def _line_text(line: dict) -> str:
    parts = []
    for span in line.get("spans", []):
        if span.get("type") == "inline_equation":
            parts.append(f"${span.get('content', '')}$")
        else:
            parts.append(span.get("content", ""))
    return "".join(parts)


def _block_text(block: dict) -> str:
    return " ".join(t for t in (_line_text(l) for l in block.get("lines", [])) if t)


def convert(middle: dict) -> dict:
    """middle.json -> {"pages": [...], "regions": [...]} in PDF points."""
    pages, regions = [], []

    def add(region):
        regions.append(region)
        return len(regions) - 1

    for page in middle["pdf_info"]:
        p = page["page_idx"]
        width, height = page["page_size"]
        pages.append({"page": p, "width": width, "height": height})
        blocks = [(b, False) for b in page.get("para_blocks", [])]
        blocks += [(b, True) for b in page.get("discarded_blocks", [])]
        for block, discarded in blocks:
            btype = block.get("type", "")
            kind = _KINDS.get(btype, "other")
            order = block.get("index", len(regions)) + (10000 if discarded else 0)
            meta = {"orig_type": btype, "score": block.get("score")}
            if btype == "title":
                level = block.get("level", 2)
                add({"page": p, "bbox": block["bbox"], "kind": "title" if level == 1 else "heading",
                     "level": level, "order": order, "content": _block_text(block), "format": "markdown",
                     "meta": meta})
                continue
            children = block.get("blocks", [])
            if children:  # image / chart / table / code groups
                body = next((c for c in children if c.get("type", "").endswith("_body")), None)
                content, fmt = None, None
                if body is not None:
                    spans = [s for l in body.get("lines", []) for s in l.get("spans", [])]
                    html = next((s.get("html") for s in spans if s.get("html")), None)
                    if html:
                        content, fmt = html, "html"
                    elif kind in ("code", "algorithm"):
                        content, fmt = "\n".join(_line_text(l) for l in body.get("lines", [])), "text"
                owner = add({"page": p, "bbox": (body or block)["bbox"], "kind": kind, "order": order,
                             "content": content, "format": fmt, "meta": meta})
                for child in children:
                    ctype = child.get("type", "")
                    role = "caption" if ctype.endswith("_caption") else "footnote" if ctype.endswith("_footnote") else None
                    if role:
                        add({"page": p, "bbox": child["bbox"], "kind": role, "order": order + 0.01 * child.get("index", 0),
                             "content": _block_text(child), "format": "markdown", "parent": owner,
                             "meta": {"orig_type": ctype, "score": child.get("score")}})
                continue
            if kind == "display_math":
                spans = [s for l in block.get("lines", []) for s in l.get("spans", [])]
                latex = " ".join(s.get("content", "") for s in spans if s.get("type") == "interline_equation")
                add({"page": p, "bbox": block["bbox"], "kind": kind, "order": order,
                     "content": latex, "format": "latex", "meta": meta})
                continue
            owner = add({"page": p, "bbox": block["bbox"], "kind": kind, "order": order,
                         "content": _block_text(block), "format": "markdown", "meta": meta})
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("type") == "inline_equation":
                        add({"page": p, "bbox": span["bbox"], "kind": "inline_math", "order": order,
                             "content": span.get("content", ""), "format": "latex", "parent": owner,
                             "meta": {"score": span.get("score")}})
    return {"pages": pages, "regions": regions}


def run(job: dict) -> dict:
    if job["task"] != "page_parse":
        raise ValueError(f"unsupported task {job['task']}")
    options = job["options"]
    exe = _mineru_exe(options)
    work = Path(job["job_dir"]) / "mineru"
    inputs, outputs = work / "input", work / "output"
    if work.exists():
        shutil.rmtree(work)
    inputs.mkdir(parents=True)
    for item in job["items"]:
        target = inputs / f"{item['id']}.pdf"
        try:
            os.link(item["pdf"], target)
        except OSError:
            shutil.copy2(item["pdf"], target)
    cmd = [exe, "-p", str(inputs), "-o", str(outputs), "-b", options.get("backend", "pipeline"),
           "-d", _device(job["device"])]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"mineru exited {proc.returncode}: {proc.stderr[-3000:]}")
    INFO.update(version=_version(exe), command=cmd)
    import json
    results = {}
    for item in job["items"]:
        found = sorted(outputs.rglob(f"{item['id']}_middle.json"))
        if not found:
            raise RuntimeError(f"mineru produced no middle.json for {item['id']}")
        result = convert(json.loads(found[0].read_text(encoding="utf-8")))
        result["raw_dir"] = str(found[0].parent)
        results[item["id"]] = result
    return results
