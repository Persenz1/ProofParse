"""Attach native character evidence to existing pilot tasks without OCR or APIs.

Example: python -B scripts/native_formula_pilot.py --tasks TASKS.json
         --pdf-dir INPUT --out EVIDENCE.json --ids t01 t10 t21
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proofparse.pdf.native import page_characters, region_evidence
from proofparse.formula.native import analyze, apply_glyph_map, number_candidates
from proofparse.review.native import load_glyph_map


def main():
    import pymupdf

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--glyph-maps", type=Path, help="Directory containing PAPER.json confirmed glyph maps")
    args = parser.parse_args()
    tasks = json.loads(args.tasks.read_text(encoding="utf-8"))
    if args.ids:
        missing = set(args.ids) - {t["id"] for t in tasks}
        if missing:
            parser.error(f"Unknown task IDs: {sorted(missing)}")
        tasks = [t for t in tasks if t["id"] in args.ids]
    start = time.perf_counter()
    evidence = {}
    for paper in dict.fromkeys(t["paper"] for t in tasks):
        pdf_path = args.pdf_dir / f"{paper}.pdf"
        mappings = load_glyph_map(args.glyph_maps / f"{paper}.json", pdf_path) if args.glyph_maps else []
        with pymupdf.open(pdf_path) as pdf:
            cache = {}
            for task in (t for t in tasks if t["paper"] == paper):
                index = task["page"]
                page = pdf[index]
                if index not in cache:
                    cache[index] = apply_glyph_map(page_characters(page), mappings)
                evidence[task["id"]] = {
                    **task,
                    "native_evidence": region_evidence(
                        cache[index], (page.rect.width, page.rect.height),
                        task["source_region_bbox_1000"], task["target_bbox_1000"]),
                }
                row = evidence[task["id"]]
                if task["kind"] in ("display", "inline"):
                    native = row["native_evidence"]
                    numbers = number_candidates(cache[index], native["target_bbox_pt"]) if task["kind"] == "display" else None
                    row["native_constraints"] = analyze(native, task["a"], task["b"], numbers=numbers)
    result = {
        "source_tasks": str(args.tasks.resolve()),
        "seconds": round(time.perf_counter()-start, 4),
        "timing_scope": "PDF opening and character extraction, excluding JSON output",
        "tasks": [evidence[t["id"]] for t in tasks],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps({"tasks": len(tasks), "seconds": result["seconds"],
                      "output": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
