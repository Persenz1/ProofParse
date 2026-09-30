"""Small lexical helpers; preserve TeX groups instead of rewriting with regexes."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Token:
    value: str
    start: int
    end: int


def tokens(text: str) -> list[Token]:
    return [Token(m.group(), m.start(), m.end())
            for m in re.finditer(r"\\[a-zA-Z]+|\\.|\s+|.", text, re.DOTALL)]


def unwrap_math(text: str) -> str:
    text = text.strip()
    for left, right in (("$$", "$$"), (r"\[", r"\]"), (r"\(", r"\)"), ("$", "$")):
        if len(text) >= len(left) + len(right) and text.startswith(left) and text.endswith(right):
            return text[len(left):-len(right)].strip()
    return text


@dataclass(frozen=True)
class EquationTag:
    value: str
    starred: bool
    raw: str


def split_equation(text: str) -> tuple[str, list[EquationTag]]:
    """Separate explicit top-level tags, retaining their original TeX spelling."""
    text = unwrap_math(text)
    ts = tokens(text)
    tags, parts = [], []
    depth = cursor = i = 0
    while i < len(ts):
        t = ts[i]
        if t.value == r"\tag" and depth == 0:
            j = i + 1
            while j < len(ts) and ts[j].value.isspace(): j += 1
            starred = j < len(ts) and ts[j].value == "*"
            if starred: j += 1
            while j < len(ts) and ts[j].value.isspace(): j += 1
            if j < len(ts) and ts[j].value == "{":
                k, nesting = j + 1, 1
                while k < len(ts) and nesting:
                    if ts[k].value == "{": nesting += 1
                    elif ts[k].value == "}": nesting -= 1
                    k += 1
                if nesting == 0:
                    end = ts[k - 1].end
                    tags.append(EquationTag(text[ts[j].end:ts[k - 1].start], starred, text[t.start:end]))
                    parts.extend((text[cursor:t.start], " "))
                    cursor, i = end, k
                    continue
        if t.value == "{": depth += 1
        elif t.value == "}": depth -= 1
        i += 1
    parts.append(text[cursor:])
    return "".join(parts).strip(), tags


def orphan_number(text: str) -> str | None:
    # Parenthesized numeric, appendix and supplementary labels only.
    m = re.fullmatch(r"\(\s*((?:[A-Z][.\-]?)?\d+(?:[.\-]\d+)*[a-z]?)\s*\)", text.strip())
    return m.group(1) if m else None


@dataclass(frozen=True)
class MathSpan:
    start: int
    end: int
    body_start: int
    body_end: int


def math_spans(text: str) -> tuple[list[MathSpan], bool]:
    """Find Markdown math bodies, respecting escaped dollars and code spans.

    The flag reports unbalanced or mixed delimiters; it is not a TeX validator.
    """
    spans = []
    i = 0
    opening = None
    closing = {"$": "$", "$$": "$$", r"\(": r"\)", r"\[": r"\]"}
    while i < len(text):
        if text[i] == "`" and opening is None:
            end = i + 1
            while end < len(text) and text[end] == "`": end += 1
            next_tick = text.find(text[i:end], end)
            i = len(text) if next_tick < 0 else next_tick + end - i
            continue
        if text[i] == "\\":
            value = text[i:i + 2]
            if value not in (r"\(", r"\)", r"\[", r"\]"):
                i += 2
                continue
        elif text[i] == "$":
            value = "$$" if text.startswith("$$", i) else "$"
        else:
            i += 1
            continue
        if opening is None:
            if value not in closing: return spans, False
            opening = (value, i)
        else:
            left, start = opening
            if value != closing[left]: return spans, False
            spans.append(MathSpan(start, i + len(value), start + len(left), i))
            opening = None
        i += len(value)
    return spans, opening is None
