"""Benchmarks on the arXiv gold set.

formula   crop every gold formula from clean.pdf, run formula engines, score
          each engine and, per engine pair, how often they agree on a wrong
          answer (the failure mode that cross-validation cannot catch).
inline    run the text-layer inline-math detector on clean.pdf and compare
          glyph sets with the gold inline formulas.

Results go to <gold_root>/bench/<name>-<timestamp>.json.
"""
from __future__ import annotations

import itertools
import time
from pathlib import Path

from .. import engines
from ..config import Config
from ..engines.runner import run_engine
from ..formula.output import content as formula_content
from ..ir import read_json, write_json
from ..preprocess.render import crop_regions
from . import score as scoring

PAD_PT = 1.5


def gold_papers(root: Path) -> list[tuple[Path, dict]]:
    return [(p.parent, read_json(p)) for p in sorted(Path(root).glob("*/gold/gold.json"))]


def usable(formula: dict) -> bool:
    """Gold we trust for recognition scoring: one rendered, layout-verified occurrence
    and a macro expansion that fully succeeded."""
    occ = formula["occurrences"]
    return (formula["status"] == "ok" and len(occ) == 1 and occ[0]["layout_verified"]
            and formula["expansion_complete"] and not formula["unsupported_macros"]
            and formula["latex_expanded"].strip() != "")


def formula_items(root: Path, *, kinds=("display", "inline"), limit: int | None = None,
                  scale: float = 3.0) -> tuple[list[dict], dict]:
    items, skipped = [], {}
    for gold_dir, gold in gold_papers(root):
        jobs = []
        for f in gold["formulas"]:
            kind = "display" if f["display"] else "inline"
            if kind not in kinds:
                continue
            if not usable(f):
                skipped[kind] = skipped.get(kind, 0) + 1
                continue
            occ = f["occurrences"][0]
            crop = Path(root) / "bench" / "crops" / f"scale-{scale}" / gold["paper"] / f"{f['id']:05d}.png"
            if not crop.is_file():
                jobs.append((occ["page"], occ["bbox_pt"], crop, PAD_PT))
            items.append({"id": f"{gold['paper']}/{f['id']:05d}", "image": str(crop), "kind": kind,
                          "gold": f["latex_expanded"], "context": f["context"], "env": f["env"]})
        crop_regions(gold_dir / "clean.pdf", jobs, scale)
    if limit:
        items = items[:limit]
    return items, skipped


def bench_formula(root: Path, cfg: Config, names: list[str], *, kinds=("display", "inline"),
                  limit: int | None = None, render_compare: bool = False, log=print) -> dict:
    items, skipped = formula_items(root, kinds=kinds, limit=limit, scale=cfg.render_scale)
    work = Path(root) / "bench" / "work"
    predictions: dict[str, dict[str, str]] = {}
    runs = {}
    for name in names:
        outputs, info = run_engine(cfg, name, "formula",
                                   [{k: it[k] for k in ("id", "image", "kind")} for it in items], work, log=log)
        predictions[name] = {i: formula_content(o)[0] for i, o in outputs.items()}
        runs[name] = {"seconds": info.seconds, "cached": info.n_cached, "peak_vram_mb": info.peak_vram_mb,
                      "family": engines.family(name, "formula")}
    rows = []
    for it in items:
        row = {"id": it["id"], "kind": it["kind"], "gold": it["gold"], "env": it["env"], "engines": {}}
        for name in names:
            pred = predictions[name].get(it["id"], "")
            row["engines"][name] = {"latex": pred, **scoring.score(pred, it["gold"])}
            if render_compare:
                from .render import compare as compare_render
                row["engines"][name]["render"] = compare_render(
                    pred, it["gold"], Path(root) / "bench" / "render" / name / it["id"].replace("/", "-"))
        rows.append(row)
    summary = {}
    for name in names:
        for kind in ("all",) + tuple(kinds):
            sel = [r for r in rows if kind == "all" or r["kind"] == kind]
            if not sel:
                continue
            s = [r["engines"][name] for r in sel]
            summary.setdefault(name, {})[kind] = {
                "n": len(sel), **{lvl: round(sum(x[lvl] for x in s) / len(s), 4) for lvl in ("strict", "layout", "loose")},
                "mean_similarity": round(sum(x["similarity"] for x in s) / len(s), 4),
                "empty": sum(x["empty"] for x in s)}
    pairs = {}
    for a, b in itertools.combinations(names, 2):
        agree = [r for r in rows if scoring.same(r["engines"][a]["latex"], r["engines"][b]["latex"])
                 and r["engines"][a]["latex"].strip()]
        wrong = [r for r in agree if not r["engines"][a]["loose"]]
        either = [r for r in rows if r["engines"][a]["loose"] or r["engines"][b]["loose"]]
        pairs[f"{a}|{b}"] = {"n": len(rows), "agree": len(agree), "agree_but_wrong": len(wrong),
                             "agreement_precision": round(1 - len(wrong) / len(agree), 4) if agree else None,
                             "either_correct": len(either),
                             "same_family": engines.family(a, "formula") == engines.family(b, "formula")}
    result = {"kind": "formula", "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "engines": runs,
              "n_items": len(items), "skipped_gold": skipped, "summary": summary, "pairs": pairs, "rows": rows}
    if render_compare:
        from collections import Counter
        result["render_summary"] = {}
        for name in names:
            values = [row["engines"][name]["render"] for row in rows]
            result["render_summary"][name] = {
                "n": len(values), "equivalent": sum(v.get("equivalent") is True for v in values),
                "status": dict(Counter(v["status"] for v in values))}
    out = Path(root) / "bench" / f"formula-{time.strftime('%Y%m%d-%H%M%S')}.json"
    write_json(out, result)
    log(format_formula_summary(result))
    log(f"[bench] details -> {out}")
    return result


def format_formula_summary(result: dict) -> str:
    lines = [f"{'engine':28} {'kind':8} {'n':>5} {'strict':>7} {'layout':>7} {'loose':>7} {'sim':>6} {'sec':>7}"]
    for name, kinds in result["summary"].items():
        for kind, s in kinds.items():
            lines.append(f"{name:28} {kind:8} {s['n']:5d} {s['strict']:7.1%} {s['layout']:7.1%} {s['loose']:7.1%} "
                         f"{s['mean_similarity']:6.3f} {result['engines'][name]['seconds']:7.1f}")
    lines.append("")
    lines.append(f"{'pair':56} {'agree':>6} {'wrong':>6} {'prec':>7} {'either':>7}")
    for pair, p in result["pairs"].items():
        prec = f"{p['agreement_precision']:.1%}" if p["agreement_precision"] is not None else "-"
        lines.append(f"{pair:56} {p['agree']:6d} {p['agree_but_wrong']:6d} {prec:>7} {p['either_correct']:7d}"
                     + ("  (same family)" if p["same_family"] else ""))
    for name, s in result.get("render_summary", {}).items():
        lines.append(f"[render] {name}: {s['equivalent']}/{s['n']} canonical equivalents; {s['status']}")
    for name, info in result["engines"].items():
        if info["cached"]:
            lines.append(f"[cache] {name}: {info['cached']} items reused; seconds report only this run")
    return "\n".join(lines)


# ------------------------------------------------------------------ inline detection

def _page_lines(page) -> list[list[dict]]:
    """Text-layer lines of a page in the glyph format used by stages.text,
    transformed like the gold glyphs (texttrace space times rotation)."""
    import pymupdf
    rot = page.rotation_matrix
    raw = page.get_text("rawdict")
    lines = []
    for block in raw["blocks"]:
        for line in block.get("lines", []):
            chars = []
            for span in line["spans"]:
                for ch in span["chars"]:
                    if ch["c"].isspace():
                        continue
                    o = pymupdf.Point(ch["origin"]) * rot
                    chars.append({"text": ch["c"], "bbox_pt": list(pymupdf.Rect(ch["bbox"]) * rot),
                                  "origin_pt": [o.x, o.y], "size_pt": span["size"], "font": span["font"]})
            if chars:
                lines.append(sorted(chars, key=lambda c: c["bbox_pt"][0]))
    return lines


def _key(page: int, origin, text: str) -> tuple:
    """Glyph identity across the two compiles: same page, origin and character."""
    return (page, round(origin[0], 1), round(origin[1], 1), text)


def bench_inline(root: Path, log=print) -> dict:
    import pymupdf
    from ..preprocess.native import is_math_font
    from ..stages.text import math_runs
    totals = {"tp": 0, "fp": 0, "fn": 0, "unknown_math_font": 0}
    per_formula = {"exact": 0, "missed": 0, "partial": 0, "n": 0}
    papers = []
    for gold_dir, gold in gold_papers(root):
        gold_glyphs, formulas = set(), []
        display_glyphs = set()
        for f in gold["formulas"]:
            for occ in f["occurrences"]:
                if not occ["layout_verified"]:
                    continue
                keys = {_key(occ["page"], o, t) for t, _, o in occ["glyphs"]}
                if f["display"]:
                    display_glyphs |= keys
                else:
                    gold_glyphs |= keys
                    formulas.append(keys)
        predicted, unknown = set(), set()
        with pymupdf.open(gold_dir / "clean.pdf") as doc:
            for page in doc:
                if page.number in gold["layout_shifted_pages"]:
                    continue
                for line in _page_lines(page):
                    sizes = sorted(c["size_pt"] for c in line)
                    for start, end in math_runs(line, sizes[len(sizes) // 2]):
                        predicted |= {_key(page.number, c["origin_pt"], c["text"]) for c in line[start:end]}
                    for c in line:
                        k = _key(page.number, c["origin_pt"], c["text"])
                        if is_math_font(c["font"]) and k not in gold_glyphs and k not in display_glyphs:
                            unknown.add(k)
        predicted -= display_glyphs
        tp = len(predicted & gold_glyphs)
        fp = len(predicted - gold_glyphs - unknown)
        fn = len(gold_glyphs - predicted)
        totals["tp"] += tp
        totals["fp"] += fp
        totals["fn"] += fn
        totals["unknown_math_font"] += len(unknown)
        for keys in formulas:
            per_formula["n"] += 1
            hit = len(keys & predicted)
            per_formula["exact" if hit == len(keys) else "missed" if hit == 0 else "partial"] += 1
        papers.append({"paper": gold["paper"], "tp": tp, "fp": fp, "fn": fn, "unknown_math_font": len(unknown)})
    precision = totals["tp"] / (totals["tp"] + totals["fp"]) if totals["tp"] + totals["fp"] else None
    recall = totals["tp"] / (totals["tp"] + totals["fn"]) if totals["tp"] + totals["fn"] else None
    result = {"kind": "inline", "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "glyphs": totals,
              "glyph_precision": precision, "glyph_recall": recall, "formulas": per_formula, "papers": papers}
    out = Path(root) / "bench" / f"inline-{time.strftime('%Y%m%d-%H%M%S')}.json"
    write_json(out, result)
    log(f"[bench] inline glyphs: precision {precision:.1%} recall {recall:.1%} "
        f"(unknown math-font glyphs excluded: {totals['unknown_math_font']}); formulas "
        f"exact {per_formula['exact']}/{per_formula['n']}, partial {per_formula['partial']}, missed {per_formula['missed']}"
        if precision is not None and recall is not None else "[bench] inline: no data")
    return result
