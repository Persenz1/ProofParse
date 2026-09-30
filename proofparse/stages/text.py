"""Text stage: prose from the PDF text layer, inline math located by glyphs.

Every visible glyph is assigned to at most one block (the smallest region
containing its centre). Inside prose blocks, runs of math glyphs become
INLINE_MATH children and the parent text gets one INLINE_SLOT per child.
Engine inline-math proposals are merged in by glyph overlap and provenance
is recorded, so the benchmark can measure each detector separately.

Pages without a usable text layer fall back to the layout engine's text,
with its $...$ spans turned into children the same way.
"""
from __future__ import annotations

import re
import unicodedata

from .. import engines, ir
from ..formula.syntax import math_spans
from ..ir import Block, Candidate, Document
from ..preprocess.native import is_math_font

CLAIMING_KINDS = ir.PROSE_KINDS | {ir.DISPLAY_MATH, ir.FIGURE, ir.TABLE, ir.CODE, ir.ALGORITHM,
                                   ir.FURNITURE, ir.OTHER}
_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
_CONNECTORS = set("=+-−<>()[]{}|/,.:;'′*·^_~!") | set("0123456789")
_TRAILING = set(".,;:")
_OPERATOR_NAMES = {"sin", "cos", "tan", "log", "ln", "exp", "max", "min", "sup", "inf", "lim",
                   "det", "tr", "arg", "Pr", "argmax", "argmin", "diag", "rank", "sgn", "mod"}
_PAIRS = {")": "(", "]": "[", "}": "{"}


def _visible(c: dict) -> bool:
    return c["render_type"] != 3 and c["opacity"] > 0 and not c["text"].isspace()


def _center(c: dict) -> tuple[float, float]:
    x0, y0, x1, y1 = c["bbox_pt"]
    return (x0 + x1) / 2, (y0 + y1) / 2


def _inside(point, box, pad=1.0) -> bool:
    return box[0] - pad <= point[0] <= box[2] + pad and box[1] - pad <= point[1] <= box[3] + pad


def _area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def assign_glyphs(blocks: list[Block], chars: list[dict]) -> tuple[dict[str, list[dict]], list[dict]]:
    """Map each visible glyph to the smallest claiming block containing it."""
    owners = sorted((b for b in blocks if b.kind in CLAIMING_KINDS and b.parent is None),
                    key=lambda b: _area(b.bbox))
    owned: dict[str, list[dict]] = {b.id: [] for b in owners}
    unassigned = []
    for c in chars:
        if not _visible(c):
            continue
        point = _center(c)
        owner = next((b for b in owners if _inside(point, b.bbox)), None)
        (owned[owner.id].append(c) if owner else unassigned.append(c))
    return owned, unassigned


# ------------------------------------------------------------------ lines

def build_lines(chars: list[dict]) -> list[list[dict]]:
    """Group glyphs into text lines; scripts attach to the line they sit on."""
    if not chars:
        return []
    sizes = sorted(c["size_pt"] for c in chars)
    body = sizes[len(sizes) // 2]
    primary = sorted((c for c in chars if c["size_pt"] >= 0.8 * body), key=lambda c: c["origin_pt"][1])
    secondary = [c for c in chars if c["size_pt"] < 0.8 * body]
    lines: list[dict] = []
    for c in primary:
        y = c["origin_pt"][1]
        line = next((l for l in lines if abs(l["baseline"] - y) <= 0.3 * max(l["size"], c["size_pt"])), None)
        if line is None:
            lines.append({"baseline": y, "size": c["size_pt"], "chars": [c]})
        else:
            line["chars"].append(c)
    for c in secondary:
        cy = _center(c)[1]
        best = min(lines, key=lambda l: abs(l["baseline"] - 0.3 * l["size"] - cy), default=None)
        if best is None or abs(best["baseline"] - 0.3 * best["size"] - cy) > 1.2 * best["size"]:
            lines.append({"baseline": c["origin_pt"][1], "size": c["size_pt"], "chars": [c]})
        else:
            best["chars"].append(c)
    lines.sort(key=lambda l: l["baseline"])
    return [sorted(l["chars"], key=lambda c: c["bbox_pt"][0]) for l in lines]


def _gap(a: dict, b: dict) -> float:
    return b["bbox_pt"][0] - a["bbox_pt"][2]


def _is_seed(c: dict) -> bool:
    t = c["text"]
    if is_math_font(c["font"]):
        return True
    if len(t) != 1:
        return False
    cp = ord(t)
    return (0x2200 <= cp <= 0x22FF or 0x2190 <= cp <= 0x21FF or 0x27C0 <= cp <= 0x27EF
            or 0x2A00 <= cp <= 0x2AFF or 0x1D400 <= cp <= 0x1D7FF or 0x0391 <= cp <= 0x03C9
            or t in "∑∏∫√∞∂∇±×÷≤≥≠≈≡∈∉⊂⊆∪∩∀∃→←↦⟨⟩‖")


def math_runs(line: list[dict], body_size: float) -> list[tuple[int, int]]:
    """Index ranges [start, end) of inline math within an x-sorted line."""
    n = len(line)
    seed = [_is_seed(c) for c in line]
    small = [c["size_pt"] < 0.8 * body_size for c in line]
    member = list(seed)

    def joinable(i: int) -> bool:
        c = line[i]
        return c["text"] in _CONNECTORS or small[i] or seed[i]

    def close(i: int, j: int) -> bool:  # gap between neighbours small enough to be one expression
        return _gap(line[i], line[j]) < 0.6 * max(line[i]["size_pt"], line[j]["size_pt"])

    changed = True
    while changed:
        changed = False
        for i in range(n):
            if member[i]:
                continue
            left = i > 0 and member[i - 1] and close(i - 1, i)
            right = i + 1 < n and member[i + 1] and close(i, i + 1)
            if (left or right) and joinable(i):
                member[i] = changed = True
            elif left and right and line[i]["text"].isalpha():  # \mathbf{x}, \mathrm{T} between math
                member[i] = changed = True
    # operator names set in text fonts directly before math: "log p", "max_i"
    i = 0
    while i < n:
        if member[i] or not line[i]["text"].isalpha():
            i += 1
            continue
        j = i + 1
        while (j < n and line[j]["text"].isalpha() and not member[j]
               and _gap(line[j - 1], line[j]) <= 0.15 * line[j]["size_pt"]):
            j += 1
        word = "".join(c["text"] for c in line[i:j])
        starts_word = i == 0 or not line[i - 1]["text"].isalpha() or _gap(line[i - 1], line[i]) > 0.15 * line[i]["size_pt"]
        if word in _OPERATOR_NAMES and starts_word and j < n and member[j] and close(j - 1, j):
            for k in range(i, j):
                member[k] = True
        i = j
    runs, i = [], 0
    while i < n:
        if not member[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and member[j + 1] and _gap(line[j], line[j + 1]) < 1.0 * line[j]["size_pt"]:
            j += 1
        runs.append([i, j + 1])
        i = j + 1
    trimmed = []
    for start, end in runs:
        while end > start and line[end - 1]["text"] in _TRAILING and not seed[end - 1]:
            end -= 1
        depth: dict[str, int] = {}
        for k in range(start, end):
            t = line[k]["text"]
            if t in "([{":
                depth[t] = depth.get(t, 0) + 1
            elif t in _PAIRS:
                depth[_PAIRS[t]] = depth.get(_PAIRS[t], 0) - 1
        while end > start and line[end - 1]["text"] in _PAIRS and depth.get(_PAIRS[line[end - 1]["text"]], 0) < 0:
            depth[_PAIRS[line[end - 1]["text"]]] += 1
            end -= 1
        while end > start and line[start]["text"] in "([{" and depth.get(line[start]["text"], 0) > 0:
            depth[line[start]["text"]] -= 1
            start += 1
        if end > start and any(seed[k] for k in range(start, end)):
            trimmed.append((start, end))
    return trimmed


def _clean(text: str) -> str:
    text = "".join(_LIGATURES.get(ch, ch) for ch in text.replace(ir.INLINE_SLOT, ""))
    return unicodedata.normalize("NFC", text)


def compose(lines: list[list[dict]], runs_per_line: list[list[tuple[int, int]]]) -> tuple[str, list[list[dict]]]:
    """Return prose with slots, plus the glyph list of each slot in order."""
    out: list[str] = []
    slots: list[list[dict]] = []
    for li, line in enumerate(lines):
        pieces: list[str] = []
        runs = {start: end for start, end in runs_per_line[li]}
        i, prev = 0, None
        while i < len(line):
            c = line[i]
            if prev is not None and _gap(prev, c) > 0.2 * c["size_pt"]:
                pieces.append(" ")
            if i in runs:
                slots.append(line[i:runs[i]])
                pieces.append(ir.INLINE_SLOT)
                prev, i = line[runs[i] - 1], runs[i]
                continue
            pieces.append(_clean(c["text"]))
            prev, i = c, i + 1
        text = "".join(pieces).strip()
        if not text:
            continue
        if out and out[-1].endswith("-") and text[:1].islower() and not out[-1].endswith(" -"):
            out[-1] = out[-1][:-1] + text  # hyphenation at line end
        else:
            out.append(text)
    return " ".join(out), slots


def _bbox(chars: list[dict]) -> list[float]:
    return [round(min(c["bbox_pt"][0] for c in chars), 2), round(min(c["bbox_pt"][1] for c in chars), 2),
            round(max(c["bbox_pt"][2] for c in chars), 2), round(max(c["bbox_pt"][3] for c in chars), 2)]


def _mark_proposals(lines: list[list[dict]], runs: list[list[tuple[int, int]]],
                    proposals: list[Block]) -> tuple[list[list[tuple[int, int]]], dict]:
    """Merge engine proposals into glyph runs; return runs and provenance per run."""
    provenance: dict[tuple[int, int, int], set] = {}
    merged = []
    for li, line in enumerate(lines):
        member = [None] * len(line)
        for start, end in runs[li]:
            for k in range(start, end):
                member[k] = "native"
        for p in proposals:
            hits = [k for k, c in enumerate(line) if _inside(_center(c), p.bbox, 0.5)]
            for k in hits:
                member[k] = "both" if member[k] in ("native", "both") else "engine"
        spans, k = [], 0
        while k < len(line):
            if member[k] is None:
                k += 1
                continue
            j = k
            while j + 1 < len(line) and member[j + 1] is not None and _gap(line[j], line[j + 1]) < line[j]["size_pt"]:
                j += 1
            spans.append((k, j + 1))
            provenance[(li, k, j + 1)] = {member[x] for x in range(k, j + 1)}
            k = j + 1
        merged.append(spans)
    return merged, provenance


def _engine_candidate(proposals: list[Block], box: list[float]) -> Candidate | None:
    def iou(a, b):
        inter = _area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])
        union = _area(a) + _area(b) - inter
        return inter / union if union else 0.0
    best = max(proposals, key=lambda p: iou(p.bbox, box), default=None)
    if best is not None and iou(best.bbox, box) >= 0.5 and best.candidates:
        return best.candidates[0]
    return None


def text_from_layer(block: Block, chars: list[dict], proposals: list[Block], body_size: float) -> list[Block]:
    lines = build_lines(chars)
    runs = [math_runs(line, body_size) for line in lines]
    runs, provenance = _mark_proposals(lines, runs, proposals)
    text, slots = compose(lines, runs)
    by_start = {}
    for (li, s, e), prov in provenance.items():
        by_start[id(lines[li][s])] = prov
    children = []
    for k, glyphs in enumerate(slots):
        box = _bbox(glyphs)
        child = Block(id=f"{block.id}.m{k:02d}", page=block.page, bbox=box, kind=ir.INLINE_MATH,
                      order=block.order, parent=block.id, source="text_layer",
                      extra={"detected_by": sorted(by_start.get(id(glyphs[0]), {"native"})),
                             "native_text": "".join(c["text"] for c in glyphs),
                             "glyphs": [c["source_index"] for c in glyphs]})
        cand = _engine_candidate(proposals, box)
        if cand:
            child.candidates.append(cand)
        children.append(child)
    block.text = text
    block.inline = [c.id for c in children]
    block.extra["text_source"] = "text_layer"
    return children


def text_from_engine(block: Block, proposals: list[Block]) -> list[Block]:
    """Fallback for pages without a usable text layer: engine markdown with $math$."""
    cand = next((c for c in block.candidates if c.format in ("markdown", "text")), None)
    raw = (cand.content if cand else "").replace(ir.INLINE_SLOT, "")
    spans, balanced = math_spans(raw) if cand and cand.format == "markdown" else ([], True)
    if not balanced:
        spans = []
    pieces, children, cursor = [], [], 0
    for k, span in enumerate(spans):
        pieces.append(raw[cursor:span.start])
        pieces.append(ir.INLINE_SLOT)
        latex = raw[span.body_start:span.body_end]
        proposal = proposals[k] if k < len(proposals) else None
        child = Block(id=f"{block.id}.m{k:02d}", page=block.page,
                      bbox=proposal.bbox if proposal else list(block.bbox), kind=ir.INLINE_MATH,
                      order=block.order, parent=block.id, source=cand.engine,
                      extra={"detected_by": ["engine"], "bbox_from": "proposal" if proposal else "parent"})
        child.candidates.append(Candidate(engine=cand.engine, family=engines.family(cand.engine, "formula"),
                                          content=latex, format="latex"))
        children.append(child)
        cursor = span.end
    pieces.append(raw[cursor:])
    block.text = re.sub(r"\s+", " ", "".join(pieces)).strip()
    block.inline = [c.id for c in children]
    block.extra["text_source"] = f"engine:{cand.engine}" if cand else "none"
    return children


def run(doc: Document, page_chars: dict[int, list[dict]]) -> dict:
    """Rebuild prose and inline math for every page. Returns page diagnostics."""
    proposals = [b for b in doc.blocks if b.kind == ir.INLINE_MATH and b.extra.get("proposal")]
    doc.blocks = [b for b in doc.blocks if not (b.kind == ir.INLINE_MATH)]
    new_children: list[Block] = []
    diagnostics = {}
    for page in doc.pages:
        blocks = [b for b in doc.blocks if b.page == page.index]
        layer_ok = page.text_layer.get("status") in ("good", "degraded")
        chars = page_chars.get(page.index, [])
        owned, unassigned = assign_glyphs(blocks, chars) if layer_ok else ({}, [])
        body_size = page.text_layer.get("body_size") or 10.0
        for b in blocks:
            if b.kind in (ir.CODE, ir.ALGORITHM) and layer_ok and owned.get(b.id):
                b.text = "\n".join(compose([line], [[]])[0] for line in build_lines(owned[b.id]))
                b.extra["text_source"] = "text_layer"
                continue
            if b.kind not in ir.PROSE_KINDS:
                continue
            mine = [p for p in proposals if p.parent == b.id]
            if layer_ok and owned.get(b.id):
                new_children += text_from_layer(b, owned[b.id], mine, body_size)
            else:
                new_children += text_from_engine(b, mine)
        diagnostics[page.index] = {
            "text_layer": page.text_layer.get("status"),
            "unassigned_glyphs": len(unassigned),
            "unassigned_text": "".join(c["text"] for c in unassigned)[:500],
        }
        page.text_layer["unassigned_glyphs"] = len(unassigned)
    doc.blocks += new_children
    return diagnostics
