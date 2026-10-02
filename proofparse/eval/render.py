"""Canonical TeX rendering equivalence, not fidelity to the source PDF.

Each pair shares a page and the same Computer Modern fonts. Compare all PDF
glyphs, font sizes, relative origins and drawing paths with 0.05-point
tolerance. Unknown macros or failed compilation are skipped, not scored as
incorrect. Work files stay in the caller-provided directory.
"""
from __future__ import annotations

import subprocess
import shutil
import re
from pathlib import Path

import pymupdf

from ..formula.lint import check_latex
from ..formula.syntax import split_equation, unwrap_math

PDFLATEX = Path(shutil.which("pdflatex") or r"C:\texlive\2026\bin\windows\pdflatex.exe")
TOLERANCE_PT = 0.05
_SP_TO_PDF_PT = 72 / (72.27 * 65536)


def _body(latex):
    body, _ = split_equation(unwrap_math(latex))
    wrapped = re.fullmatch(r"\\begin\{(align\*?|equation\*?)\}(.*)\\end\{\1\}",
                           body.strip(), re.DOTALL)
    return wrapped[2] if wrapped else body

_TEMPLATE = r"""\documentclass[10pt]{article}
\usepackage[paperwidth=1000pt,paperheight=2000pt,margin=20pt]{geometry}
\usepackage{amsmath,amssymb,bm}
\pagestyle{empty}
\newwrite\formulaPositions
\immediate\openout\formulaPositions=pair.pos
\newcommand{\formulamark}[1]{\par\noindent\pdfsavepos
\write\formulaPositions{#1=\the\pdflastxpos,\the\pdflastypos}\par}
\begin{document}
\formulamark{pred}
\begin{equation*}\begin{aligned}
@PRED@
\end{aligned}\end{equation*}
\vspace{36pt}
\formulamark{gold}
\begin{equation*}\begin{aligned}
@GOLD@
\end{aligned}\end{equation*}
\end{document}
"""


def _geometry(spans, drawings):
    glyphs = [(span["font"], char[0], char[1], span["type"], span["opacity"],
               span["size"], char[2][0], char[2][1])
              for span in spans for char in span["chars"]]
    if not glyphs and not drawings:
        raise ValueError("formula produced no glyphs or drawing paths")
    origin_x = min([g[6] for g in glyphs] + [d["rect"].x0 for d in drawings])
    origin_y = min([g[7] for g in glyphs] + [d["rect"].y0 for d in drawings])
    glyphs = sorted(g[:6] + (g[6] - origin_x, g[7] - origin_y) for g in glyphs)
    paths = []
    for drawing in drawings:
        commands = []
        for item in drawing["items"]:
            parameters = []
            for value in item[1:]:
                if isinstance(value, pymupdf.Point):
                    parameters.extend((value.x - origin_x, value.y - origin_y))
                elif isinstance(value, pymupdf.Rect):
                    parameters.extend((value.x0 - origin_x, value.y0 - origin_y,
                                       value.x1 - origin_x, value.y1 - origin_y))
                elif isinstance(value, pymupdf.Quad):
                    for point in value:
                        parameters.extend((point.x - origin_x, point.y - origin_y))
                elif isinstance(value, (int, float)):
                    parameters.append(value)
                else:
                    raise ValueError(f"unsupported PDF drawing parameter: {type(value).__name__}")
            commands.append((item[0], tuple(parameters)))
        style = (drawing["type"], drawing.get("width") or 0,
                 tuple(drawing.get("color") or ()), tuple(drawing.get("fill") or ()),
                 drawing.get("stroke_opacity", 1), drawing.get("fill_opacity", 1),
                 bool(drawing.get("closePath")))
        paths.append((style, tuple(commands)))
    return glyphs, sorted(paths)


def _difference(pred, gold):
    pred_glyphs, pred_paths = pred
    gold_glyphs, gold_paths = gold
    if len(pred_glyphs) != len(gold_glyphs):
        return "glyph_count_mismatch"
    for a, b in zip(pred_glyphs, gold_glyphs):
        if a[:5] != b[:5]:
            return "glyph_or_font_mismatch"
        if abs(a[5] - b[5]) > TOLERANCE_PT:
            return "font_size_mismatch"
        if max(abs(a[6] - b[6]), abs(a[7] - b[7])) > TOLERANCE_PT:
            return "glyph_geometry_mismatch"
    if len(pred_paths) != len(gold_paths):
        return "drawing_count_mismatch"
    for (a_style, a_commands), (b_style, b_commands) in zip(pred_paths, gold_paths):
        if a_style[0] != b_style[0] or a_style[2:] != b_style[2:]:
            return "drawing_style_mismatch"
        if abs(a_style[1] - b_style[1]) > TOLERANCE_PT or len(a_commands) != len(b_commands):
            return "drawing_geometry_mismatch"
        for (a_op, a_values), (b_op, b_values) in zip(a_commands, b_commands):
            if a_op != b_op or len(a_values) != len(b_values):
                return "drawing_geometry_mismatch"
            if any(abs(a - b) > TOLERANCE_PT for a, b in zip(a_values, b_values)):
                return "drawing_geometry_mismatch"
    return None


def compare(pred: str, gold: str, work: Path) -> dict:
    """Return {status, equivalent, reason}; compile each pair with shell escape off."""
    for name, latex in (("pred", pred), ("gold", gold)):
        problems = check_latex(latex)
        if problems:
            return {"status": "invalid" if name == "pred" else "skipped",
                    "equivalent": False if name == "pred" else None,
                    "reason": f"{name}_structure: {', '.join(problems)}"}
        if not latex.strip():
            return {"status": "skipped", "equivalent": None, "reason": f"{name} is empty"}
    if not PDFLATEX.is_file():
        return {"status": "skipped", "equivalent": None, "reason": f"pdflatex missing: {PDFLATEX}"}
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    source = _TEMPLATE.replace("@PRED@", _body(pred)).replace("@GOLD@", _body(gold))
    (work / "pair.tex").write_text(source, encoding="utf-8")
    try:
        process = subprocess.run([str(PDFLATEX), "-no-shell-escape", "-interaction=nonstopmode",
                                  "-halt-on-error", "-file-line-error", "pair.tex"],
                                 cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "skipped", "equivalent": None, "reason": f"pdflatex: {exc}"}
    if process.returncode:
        lines = process.stdout.splitlines()
        failure = next((i for i, line in enumerate(lines)
                        if line.startswith("!") or "pair.tex:" in line), max(0, len(lines) - 8))
        return {"status": "skipped", "equivalent": None,
                "reason": "TeX compilation failed: " + " ".join(lines[failure:failure + 5])}
    try:
        positions = dict(line.split("=", 1) for line in (work / "pair.pos").read_text().splitlines())
        with pymupdf.open(work / "pair.pdf") as pdf:
            if len(pdf) != 1:
                raise ValueError("formula pair did not fit on one page")
            page = pdf[0]
            gold_top = page.rect.height - int(positions["gold"].split(",")[1]) * _SP_TO_PDF_PT
            spans = page.get_texttrace()
            drawings = page.get_drawings()
            # Texttrace can combine the same font across both formulas in one
            # span. Partition the individual glyphs, not that span's union box.
            pred_spans = [dict(s, chars=[c for c in s["chars"] if c[3][3] < gold_top]) for s in spans]
            gold_spans = [dict(s, chars=[c for c in s["chars"] if c[3][1] >= gold_top]) for s in spans]
            predicted = _geometry(pred_spans,
                                  [d for d in drawings if d["rect"].y1 < gold_top])
            reference = _geometry(gold_spans,
                                  [d for d in drawings if d["rect"].y0 >= gold_top])
            if any(c[3][1] < gold_top <= c[3][3] for s in spans for c in s["chars"]):
                raise ValueError("a PDF glyph span crossed the formula boundary")
            if any(d["rect"].y0 < gold_top <= d["rect"].y1 for d in drawings):
                raise ValueError("a PDF drawing crossed the formula boundary")
        difference = _difference(predicted, reference)
        return {"status": "compared", "equivalent": difference is None,
                "reason": difference or "canonical_render_equal", "tolerance_pt": TOLERANCE_PT,
                "pred_glyphs": len(predicted[0]), "gold_glyphs": len(reference[0])}
    except (OSError, ValueError, KeyError) as exc:
        return {"status": "skipped", "equivalent": None, "reason": f"PDF comparison unavailable: {exc}"}
