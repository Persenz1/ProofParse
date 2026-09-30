"""Protect mathematical content during document patches."""
from __future__ import annotations

import re

from .compare import latex_normalize
from .lint import check_latex
from .syntax import math_spans, orphan_number, split_equation, unwrap_math


def equation_patch(old: str, new: str, number_correction=None) -> tuple[str, str | None]:
    new = unwrap_math(new)
    _, before = split_equation(old)
    _, after = split_equation(new)
    old_numbers = [t.raw for t in before]
    if not before and (number := orphan_number(old)):
        old_numbers = [r"\tag{" + number + "}"]
        _, before = split_equation(old_numbers[0])
    new_numbers = [t.raw for t in after]
    keys = lambda tags: [(t.value, t.starred) for t in tags]
    if before and keys(before) != keys(after):
        if number_correction == {"old": old_numbers, "new": new_numbers} and after:
            pass  # An explicit, source-checked numbering correction.
        elif not after and len(before) == 1 and not re.search(r"\\(?:begin|end)\b", new):
            new += before[0].raw
        else:
            return new, "protected_equation_number"
    if not split_equation(new)[0]:
        return new, "empty_equation_body"
    if check_latex(new):
        return new, "invalid_latex"
    # A display block stores its body only; Markdown adds the delimiters.
    spans, balanced = math_spans(new)
    if spans or not balanced:
        return new, "nested_math_delimiters"
    return new, None


def prose_patch(old: str, new: str, math_edits: list[dict] | None = None) -> str | None:
    # Explicit math fragments also allow repairing a broken/escaped delimiter.
    # Every other formula in the paragraph remains protected.
    for edit in math_edits or []:
        fragment, replacement = edit.get("old"), edit.get("new")
        if not isinstance(fragment, str) or not fragment or not isinstance(replacement, str):
            return "invalid_math_edit"
        spans, balanced = math_spans(replacement)
        if (not balanced or len(spans) != 1 or spans[0].start != 0
                or spans[0].end != len(replacement)):
            return "invalid_math_edit"
        if old.count(fragment) != 1: return "ambiguous_math_edit"
        span = spans[0]
        body = replacement[span.body_start:span.body_end]
        corrected, error = equation_patch(fragment, body)
        if error or latex_normalize(corrected) != latex_normalize(body):
            return error or "protected_equation_number"
        old = old.replace(fragment, replacement, 1)
    before, old_balanced = math_spans(old)
    after, new_balanced = math_spans(new)
    if not new_balanced: return "unbalanced_math_delimiters"
    if not old_balanced: return "repair_math_delimiters_first"
    bodies = lambda text, spans: [latex_normalize(text[s.body_start:s.body_end]) for s in spans]
    if bodies(old, before) != bodies(new, after):
        return "protected_inline_math"
    return None


def inline_patch(text: str, candidate: str, corrected: str) -> tuple[str, str | None]:
    spans, balanced = math_spans(text)
    if not balanced: return text, "unbalanced_math_delimiters"
    matches = [s for s in spans
               if latex_normalize(text[s.body_start:s.body_end]) == latex_normalize(candidate)]
    if len(matches) != 1: return text, "ambiguous_span"
    span = matches[0]
    replacement, error = equation_patch(text[span.body_start:span.body_end], corrected)
    if error: return text, error
    return text[:span.body_start] + replacement + text[span.body_end:], None


def duplicate_insert(content: str, existing: list[str]) -> bool:
    """Catch verbatim text already present in a same/adjacent-page merged block.

    Keep punctuation, case and math intact. Short labels only match whole blocks
    so common headings and symbols inside prose do not block legitimate inserts.
    """
    normalize = lambda text: re.sub(r"\s+", " ", text).strip()
    needle = normalize(content)
    if not needle: return False
    return any(needle == (haystack := normalize(text)) or
               (len(needle) >= 40 and needle in haystack) for text in existing)
