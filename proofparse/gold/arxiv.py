"""Build formula gold data from arXiv LaTeX sources.

For each paper the source is compiled twice with pdfLaTeX: once unchanged
(clean.pdf, the benchmark input) and once with every math segment wrapped in
a colour-stack push/pop that encodes the segment id (marked.pdf). Colour
specials do not move glyphs, so glyph positions in marked.pdf locate each
formula in clean.pdf exactly; the builder verifies that claim per page.

Per formula the gold record keeps the source LaTeX, a macro-expanded form,
every rendered occurrence (page, bbox in points, glyph list) and equation
numbers found on the formula's rows. Nothing here is hand-labelled.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from ..ir import write_json
from ..preprocess.native import is_math_font
from . import macros as macro_mod
from .texscan import MathSegment, includes, marker_positions, scan

COLOR_BASE = 40
_DIV = COLOR_BASE + 1

PREAMBLE_HOOK = r"""
%% --- ProofParse gold markers (instrumented copy only) ---
\makeatletter
\ifdefined\pdfcolorstackinit
  \chardef\pp@stack=\pdfcolorstackinit page direct{0 g 0 G}\relax
  \protected\def\ppB#1{\pdfcolorstack\pp@stack push{#1}}
  \protected\def\ppE{\pdfcolorstack\pp@stack pop}
\else
  \errmessage{ProofParse gold markers need pdfTeX}
\fi
\makeatother
"""


def color_of(n: int) -> tuple[float, float, float]:
    n += 1
    digits = (n // COLOR_BASE**2 % COLOR_BASE, n // COLOR_BASE % COLOR_BASE, n % COLOR_BASE)
    return tuple((d + 1) / _DIV for d in digits)


def color_operator(n: int) -> str:
    rgb = " ".join(f"{v:.4f}" for v in color_of(n))
    return f"{rgb} rg {rgb} RG"


def decode_color(rgb) -> int | None:
    if rgb is None or len(rgb) != 3:
        return None
    digits = []
    for v in rgb:
        x = float(v) * _DIV
        d = round(x) - 1
        if abs(x - round(x)) > 0.08 or not 0 <= d < COLOR_BASE:
            return None
        digits.append(d)
    n = digits[0] * COLOR_BASE**2 + digits[1] * COLOR_BASE + digits[2] - 1
    return n if n >= 0 else None


# ------------------------------------------------------------------ source

def find_main(source: Path, meta: dict) -> Path | None:
    readme = source / "00README.json"
    if readme.is_file():
        data = json.loads(readme.read_text(encoding="utf-8"))
        for entry in data.get("sources", []):
            if entry.get("usage") == "toplevel" and (source / entry["filename"]).is_file():
                return source / entry["filename"]
    if meta.get("main_tex") and (source / meta["main_tex"]).is_file():
        return source / meta["main_tex"]
    mains = [p for p in source.rglob("*.tex")
             if re.search(r"\\documentclass", _read(p)) and re.search(r"\\begin\s*\{document\}", _read(p))]
    if len(mains) == 1:
        return mains[0]
    named = [p for p in mains if p.stem in ("main", "ms", "paper", "article")]
    return named[0] if len(named) == 1 else None


def compiler_of(source: Path) -> str:
    readme = source / "00README.json"
    if readme.is_file():
        data = json.loads(readme.read_text(encoding="utf-8"))
        return (data.get("process") or {}).get("compiler", "pdflatex")
    return "pdflatex"


def _read(path: Path) -> str:
    # surrogateescape round-trips non-UTF-8 bytes unchanged
    return path.read_bytes().decode("utf-8", errors="surrogateescape")


def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8", errors="surrogateescape"))


def _resolve(root: Path, base: Path, name: str) -> Path | None:
    for folder in (base, root):
        for candidate in (folder / name, folder / (name + ".tex")):
            if candidate.is_file():
                return candidate
    return None


def body_files(main: Path, root: Path) -> list[Path]:
    """Main file plus every file it includes from its document body, recursively."""
    order, seen = [], set()

    def visit(path: Path, body_only: bool):
        if path in seen:
            return
        seen.add(path)
        order.append(path)
        for name in includes(_read(path), body_only=body_only):
            child = _resolve(root, path.parent, name)
            if child:
                visit(child, False)

    visit(main, True)
    return order


def instrument(files: list[Path], main: Path, root: Path) -> tuple[dict[Path, str], list[dict]]:
    """Return rewritten file texts and one record per math segment."""
    rewritten, records = {}, []
    for path in files:
        text = _read(path)
        segments: list[MathSegment] = scan(text, body_only=(path == main))
        inserts = []
        for seg in segments:
            n = len(records)
            open_at, close_at = marker_positions(text, seg)
            # math bodies end at $, \), \], \end or }, so \ppE never runs into a letter
            inserts += [(open_at, 1, r"\ppB{" + color_operator(n) + "}"), (close_at, 0, r"\ppE ")]
            records.append({"id": n, "file": path.relative_to(root).as_posix(), "line": seg.line,
                            "delim": seg.delim, "env": seg.env, "display": seg.display,
                            "context": list(seg.context),
                            "latex_source": text[seg.body_start:seg.body_end]})
        # closing marker before an opening one at the same offset (adjacent segments)
        for pos, _, marker in sorted(inserts, key=lambda t: (t[0], t[1]), reverse=True):
            text = text[:pos] + marker + text[pos:]
        if path == main:
            m = re.search(r"\\begin\s*\{document\}", text)
            if not m:
                raise ValueError(f"{path}: no \\begin{{document}}")
            text = text[:m.start()] + PREAMBLE_HOOK + text[m.start():]
        rewritten[path] = text
    return rewritten, records


# ------------------------------------------------------------------ compile

def compile_tex(main: Path, compiler: str = "pdflatex", runs: int = 3,
                timeout: int = 600) -> tuple[Path | None, str]:
    cwd, stem = main.parent, main.stem
    log = []

    def tex():
        proc = subprocess.run([compiler, "-interaction=nonstopmode", "-file-line-error",
                               "-no-shell-escape", main.name], cwd=cwd, capture_output=True,
                              timeout=timeout)
        log.append(proc.stdout.decode("utf-8", errors="replace")[-4000:])

    tex()
    text = _read(main)
    if not (cwd / f"{stem}.bbl").exists() and re.search(r"\\bibliography\s*\{", text):
        subprocess.run(["bibtex", stem], cwd=cwd, capture_output=True, timeout=timeout)
    for _ in range(runs - 1):
        tex()
        tex_log = cwd / f"{stem}.log"
        if tex_log.exists() and not re.search(r"Rerun to get|undefined references|Label\(s\) may have changed",
                                              tex_log.read_text(encoding="utf-8", errors="replace")):
            break
    pdf = cwd / f"{stem}.pdf"
    return (pdf if pdf.is_file() else None), log[-1] if log else ""


# ------------------------------------------------------------------ extract

def _glyph_positions(doc) -> list[list[tuple]]:
    pages = []
    for page in doc:
        rows = []
        for span in page.get_texttrace():
            for codepoint, _, origin, _ in span["chars"]:
                rows.append((codepoint, round(origin[0], 1), round(origin[1], 1)))
        pages.append(rows)
    return pages


def _split_numbers(glyphs: list[dict]) -> tuple[list[dict], list[str]]:
    """Separate equation numbers placed on a display's rows from the body."""
    lines: list[list[dict]] = []
    for g in sorted(glyphs, key=lambda g: g["origin"][1]):
        line = next((l for l in lines if abs(l[0]["origin"][1] - g["origin"][1]) <= 0.4 * l[0]["size"]), None)
        (line.append(g) if line else lines.append([g]))
    body, numbers = [], []
    for line in lines:
        line.sort(key=lambda g: g["bbox"][0])
        cut_right, cut_left = len(line), 0
        for k in range(len(line) - 1, 0, -1):
            if line[k]["bbox"][0] - line[k - 1]["bbox"][2] > 1.5 * line[k]["size"]:
                cut_right = k
                break
        for k in range(1, len(line)):
            if line[k]["bbox"][0] - line[k - 1]["bbox"][2] > 1.5 * line[k]["size"]:
                cut_left = k
                break
        for part, keep in ((line[cut_right:], line[:cut_right]), (line[:cut_left], line[cut_left:])):
            text = "".join(g["text"] for g in part)
            if part and re.fullmatch(r"\(\s*[\w.\-′']+\s*\)", text):
                numbers.append(text)
                line = keep
        body.extend(line)
    return body, numbers


def extract(marked_pdf: Path) -> tuple[dict[int, list[dict]], list[dict]]:
    """Return occurrences per segment id and per-page coverage info."""
    import pymupdf
    occurrences: dict[int, dict[int, dict]] = {}
    pages = []
    with pymupdf.open(marked_pdf) as doc:
        for page in doc:
            rot = page.rotation_matrix
            uncovered = 0
            for span in page.get_texttrace():
                n = decode_color(span.get("color"))
                for codepoint, _, origin, bbox in span["chars"]:
                    if n is None:
                        if is_math_font(span["font"]) and span["type"] != 3:
                            uncovered += 1
                        continue
                    r = pymupdf.Rect(bbox) * rot
                    o = pymupdf.Point(origin) * rot
                    occ = occurrences.setdefault(n, {}).setdefault(page.number, {"glyphs": [], "rules": []})
                    occ["glyphs"].append({"text": chr(codepoint) if 0 <= codepoint < 0x110000 else "\ufffd",
                                          "bbox": [round(v, 2) for v in r], "origin": [round(o.x, 2), round(o.y, 2)],
                                          "size": round(span["size"], 2), "font": span["font"]})
            for drawing in page.get_drawings():
                n = decode_color(drawing.get("fill")) if drawing.get("fill") else None
                if n is None and drawing.get("color"):
                    n = decode_color(drawing.get("color"))
                if n is None:
                    continue
                r = drawing["rect"] * rot
                occurrences.setdefault(n, {}).setdefault(page.number, {"glyphs": [], "rules": []})["rules"].append(
                    [round(v, 2) for v in r])
            pages.append({"page": page.number, "width": round(page.rect.width, 2),
                          "height": round(page.rect.height, 2), "uncovered_math_glyphs": uncovered})
    result = {}
    for n, by_page in occurrences.items():
        result[n] = [{"page": p, **occ} for p, occ in sorted(by_page.items())]
    return result, pages


def _union(boxes):
    return [round(min(b[0] for b in boxes), 2), round(min(b[1] for b in boxes), 2),
            round(max(b[2] for b in boxes), 2), round(max(b[3] for b in boxes), 2)]


_STRIP = re.compile(r"\\(?:label|nonumber|notag)\b\s*(?:\{[^{}]*\})?")


def build_paper(paper_dir: Path, out_dir: Path | None = None, *, runs: int = 3,
                timeout: int = 600, log=print) -> dict:
    paper_dir = Path(paper_dir)
    out_dir = Path(out_dir or paper_dir / "gold")
    meta_path = paper_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    source = paper_dir / "source"
    summary = {"paper": meta.get("id", paper_dir.name), "status": "skipped"}
    main = find_main(source, meta)
    compiler = compiler_of(source)
    if main is None:
        return summary | {"reason": "main .tex not identified"}
    if compiler != "pdflatex":
        return summary | {"reason": f"compiler {compiler} not supported (pdfTeX colour stack required)"}

    if out_dir.exists():
        shutil.rmtree(out_dir)
    clean_root, marked_root = out_dir / "clean_src", out_dir / "marked_src"
    shutil.copytree(source, clean_root)
    shutil.copytree(source, marked_root)
    rel_main = main.relative_to(source)

    files = body_files(marked_root / rel_main, marked_root)
    rewritten, records = instrument(files, marked_root / rel_main, marked_root)
    for path, text in rewritten.items():
        _write(path, text)

    clean_pdf, clean_log = compile_tex(clean_root / rel_main, compiler, runs, timeout)
    marked_pdf, marked_log = compile_tex(marked_root / rel_main, compiler, runs, timeout)
    if clean_pdf is None or marked_pdf is None:
        (out_dir / "compile_log.txt").write_text(f"--- clean\n{clean_log}\n--- marked\n{marked_log}",
                                                 encoding="utf-8")
        return summary | {"status": "failed", "reason": "compile failed",
                          "clean_pdf": bool(clean_pdf), "marked_pdf": bool(marked_pdf)}
    shutil.copy2(clean_pdf, out_dir / "clean.pdf")
    shutil.copy2(marked_pdf, out_dir / "marked.pdf")

    import pymupdf
    with pymupdf.open(out_dir / "clean.pdf") as a, pymupdf.open(out_dir / "marked.pdf") as b:
        clean_pos, marked_pos = _glyph_positions(a), _glyph_positions(b)
    shifted = [i for i in range(max(len(clean_pos), len(marked_pos)))
               if i >= len(clean_pos) or i >= len(marked_pos) or clean_pos[i] != marked_pos[i]]

    all_source = "\n".join(_read(p) for p in marked_root.rglob("*") if p.suffix in (".tex", ".sty"))
    defs, unsupported = macro_mod.collect(all_source.replace(PREAMBLE_HOOK, ""))
    occurrences, pages = extract(out_dir / "marked.pdf")
    formulas = []
    for rec in records:
        latex = _STRIP.sub("", rec["latex_source"]).strip()
        expanded, complete = macro_mod.expand(latex, defs)
        occ_out = []
        for occ in occurrences.get(rec["id"], []):
            glyphs, numbers = (_split_numbers(occ["glyphs"]) if rec["display"] else (occ["glyphs"], []))
            boxes = [g["bbox"] for g in glyphs] + occ["rules"]
            if not boxes:
                continue
            occ_out.append({"page": occ["page"], "bbox_pt": _union(boxes), "numbers": numbers,
                            "n_rules": len(occ["rules"]), "layout_verified": occ["page"] not in shifted,
                            "glyphs": [[g["text"], g["bbox"], g["origin"]] for g in glyphs]})
        label = re.search(r"\\label\s*\{([^}]*)\}", rec["latex_source"])
        formulas.append({**rec, "latex": latex, "latex_expanded": expanded.strip(),
                         "expansion_complete": complete,
                         "unsupported_macros": macro_mod.used_unsupported(expanded, unsupported),
                         "label": label.group(1) if label else None,
                         "status": "ok" if occ_out else "not_rendered", "occurrences": occ_out})
    gold = {"schema": 1, "paper": summary["paper"], "meta": meta, "main": rel_main.as_posix(),
            "compiler": compiler, "pdf": "clean.pdf", "layout_shifted_pages": shifted,
            "pages": pages, "formulas": formulas}
    write_json(out_dir / "gold.json", gold)
    n_ok = sum(f["status"] == "ok" for f in formulas)
    summary = summary | {"status": "ok", "n_formulas": len(formulas), "n_rendered": n_ok,
                         "n_display": sum(f["display"] and f["status"] == "ok" for f in formulas),
                         "layout_shifted_pages": len(shifted),
                         "uncovered_math_glyphs": sum(p["uncovered_math_glyphs"] for p in pages)}
    log(f"[gold] {summary['paper']}: {n_ok}/{len(formulas)} rendered, "
        f"{summary['n_display']} display, {len(shifted)} shifted pages, "
        f"{summary['uncovered_math_glyphs']} uncovered math glyphs")
    return summary


def build_all(root: Path, *, only: list[str] | None = None, log=print) -> list[dict]:
    results = []
    for paper_dir in sorted(p for p in Path(root).iterdir() if (p / "source").is_dir()):
        if only and paper_dir.name not in only:
            continue
        try:
            results.append(build_paper(paper_dir, log=log))
        except Exception as exc:  # one broken source must not stop the batch
            results.append({"paper": paper_dir.name, "status": "failed", "reason": f"{type(exc).__name__}: {exc}"})
            log(f"[gold] {paper_dir.name}: failed: {exc}")
    write_json(Path(root) / "gold_summary.json", results)
    return results
