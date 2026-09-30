"""Reconcile candidates into decisions.

A formula is accepted only when candidates from at least two independent
model families agree after conservative normalisation, pass the structural
lint, and do not contradict the glyphs in the PDF text layer. Everything
else is left for escalation with its evidence attached. The acceptance rule
is recorded per block so the benchmark can measure how often each rule is
wrong; thresholds belong to measurements, not to this code.
"""
from __future__ import annotations

from .. import ir
import hashlib
import json

from ..formula import native as native_checks
from ..formula.compare import compare_latex, normalized_tokens
from ..formula.lint import check_latex
from ..formula.syntax import split_equation
from ..ir import Block, Decision, Document
from ..preprocess.native import region_evidence


def evidence_hash(block: Block) -> str:
    """Identity of what an escalation answer was based on."""
    raw = json.dumps([block.bbox, [(c.engine, c.content) for c in block.candidates]], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _body_key(latex: str) -> tuple[str, ...]:
    body, _ = split_equation(latex)
    return tuple(normalized_tokens(body, layout=True))


def _native_evidence(block: Block, page_chars: list[dict], display_boxes: list[list[float]],
                     page_width: float) -> tuple[dict, dict | None]:
    box = block.bbox
    if block.kind == ir.DISPLAY_MATH:
        region = [0, box[1] - 2, page_width, box[3] + 2]  # keep numbers on the same rows
    else:
        region = [box[0] - 1, box[1] - 1, box[2] + 1, box[3] + 1]
    evidence = region_evidence(page_chars, region, box)
    numbers = None
    if block.kind == ir.DISPLAY_MATH:
        numbers = native_checks.number_candidates(page_chars, box, display_boxes)
    return evidence, numbers


def decide_formula(block: Block, order: list[str], evidence: dict | None = None,
                   numbers: dict | None = None) -> Decision:
    cands = [c for c in block.candidates if c.format == "latex" and c.content.strip()]
    if not cands:
        return Decision(status=ir.FAILED, rule="no_candidate")
    rank = {name: i for i, name in enumerate(order)}
    cands.sort(key=lambda c: rank.get(c.engine, len(rank)))
    rejected: dict[str, list] = {}
    for c in cands:
        problems = check_latex(c.content)
        if problems:
            rejected[c.engine] = [{"type": "lint", "problems": problems}]
    native_result = None
    if evidence is not None and evidence["status"] == "text_present":
        native_result = native_checks.analyze(evidence, {c.engine: c.content for c in cands}, numbers=numbers)
        for f in native_result["findings"]:
            if f.get("candidate") in {c.engine for c in cands}:
                rejected.setdefault(f["candidate"], []).append(f)
    groups: dict[tuple, list] = {}
    for c in cands:
        if c.engine not in rejected:
            groups.setdefault(_body_key(c.content), []).append(c)
    ranked = sorted(groups.values(), key=lambda g: (-len({c.family for c in g}), rank.get(g[0].engine, 99)))
    ev = {"groups": [[c.engine for c in g] for g in ranked], "rejected": rejected,
          "native": ("checked" if native_result else "unavailable")}
    if numbers:
        ev["number_association"] = numbers
    if ranked:
        best = ranked[0]
        families = sorted({c.family for c in best})
        others = [c for g in ranked[1:] for c in g]
        if len(families) >= 2 and not others:
            return Decision(ir.ACCEPTED, best[0].content, f"unanimous:{'+'.join(families)}", ev)
        if len(families) >= 2 and len(families) > max(len({c.family for c in g}) for g in ranked[1:]):
            ev["dissent"] = [compare_latex(best[0].content, c.content) | {"engine": c.engine} for c in others]
            return Decision(ir.ACCEPTED, best[0].content, f"majority:{'+'.join(families)}", ev)
        if len(ranked) == 1:
            return Decision(ir.UNVERIFIED, best[0].content, f"single_family:{families[0]}", ev)
    if len(cands) >= 2:
        base = (ranked[0][0] if ranked else cands[0])
        ev["differences"] = [compare_latex(base.content, c.content) | {"engine": c.engine}
                             for c in cands if c is not base]
    return Decision(ir.CONFLICT if len(cands) >= 2 else ir.UNVERIFIED,
                    (ranked[0][0].content if ranked else None),
                    "disagreement" if len(cands) >= 2 else "single_candidate", ev)


def run(doc: Document, page_chars: dict[int, list[dict]], order: list[str]) -> dict:
    counts: dict[str, int] = {}
    widths = {p.index: p.width for p in doc.pages}
    layer = {p.index: p.text_layer.get("status") for p in doc.pages}
    for block in doc.blocks:
        if (block.decision and block.decision.by != "program"
                and block.decision.evidence.get("input_hash") == evidence_hash(block)):
            continue  # an escalation answer stands until its evidence changes
        if block.kind in ir.MATH_KINDS:
            evidence = numbers = None
            if layer.get(block.page) in ("good", "degraded"):
                displays = [b.bbox for b in doc.blocks if b.page == block.page and b.kind == ir.DISPLAY_MATH]
                evidence, numbers = _native_evidence(block, page_chars.get(block.page, []), displays,
                                                     widths[block.page])
            block.decision = decide_formula(block, order, evidence, numbers)
        elif block.kind in ir.PROSE_KINDS:
            source = block.extra.get("text_source", "")
            block.decision = (Decision(ir.ACCEPTED, None, "text_layer") if source == "text_layer"
                              else Decision(ir.UNVERIFIED, None, f"ocr_only:{source}"))
        elif block.kind == ir.TABLE:
            html = next((c for c in block.candidates if c.format == "html"), None)
            block.decision = Decision(ir.UNVERIFIED, html.content if html else None,
                                      "table_structure_unchecked" if html else "image_only")
        else:
            continue
        counts[block.decision.status] = counts.get(block.decision.status, 0) + 1
    return counts
