"""Scoring a predicted formula against gold LaTeX.

Three levels, each strictly looser than the previous one:

strict  token-identical after whitespace/alias normalisation (compare.py)
layout  also ignores spacing commands and \\dfrac/\\tfrac
loose   also ignores sizing (\\left \\right \\big ...), \\displaystyle, \\limits,
        alignment-environment wrappers and operator-name spelling; normalizes
        comments, arrow aliases, accent arguments and scoped roman declarations

"loose" is the level used for "correct". It preserves symbols, scripts,
font styles, semantic groups and matrix cells. A rendering-based metric
(CDM) can be added beside these; it does not replace them.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..formula.compare import _SYMBOLS, normalized_tokens
from ..formula.syntax import split_equation, tokens

_SIZING = {r"\left", r"\right", r"\big", r"\Big", r"\bigg", r"\Bigg", r"\bigl", r"\bigr", r"\Bigl",
           r"\Bigr", r"\biggl", r"\biggr", r"\Biggl", r"\Biggr", r"\bigm", r"\Bigm", r"\middle",
           r"\displaystyle", r"\textstyle", r"\limits", r"\nolimits"}
_WRAPPERS = re.compile(r"\\(?:begin|end)\s*\{(?:aligned|align\*?|split|gathered|gather\*?|equation\*?|"
                       r"multline\*?|eqnarray\*?|flalign\*?|alignat\*?|alignedat)\}(?:\{\d+\})?")
_OPERATORS = ("sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh log ln lg exp max min sup inf "
              "lim liminf limsup det dim ker deg gcd hom arg Pr mod").split()
_OPNAME = re.compile(r"\\(?:operatorname\*?|mathrm)\s*\{\s*((?:[A-Za-z]\s*)+)\}")
_ROMAN = re.compile(r"\{\s*\\rm\s+([A-Za-z0-9]+(?:\s+[A-Za-z0-9]+)*)\s*\}")
_ACCENTS = {"\\" + name for name in
            "bar overline hat widehat tilde widetilde dot ddot dddot ddddot vec breve check acute grave".split()}


def _without_comments(latex: str) -> str:
    parts, cursor = [], 0
    ts = tokens(latex)
    for i, token in enumerate(ts):
        if token.start < cursor or token.value != "%":
            continue
        parts.append(latex[cursor:token.start])
        end = latex.find("\n", token.end)
        cursor = end + 1 if end >= 0 else len(latex)
        # A comment terminates a control word; removing it must not form
        # a different command with letters on the next line.
        if i and re.fullmatch(r"\\[A-Za-z]+", ts[i - 1].value):
            parts.append(" ")
    parts.append(latex[cursor:])
    return "".join(parts)


def _accent_arguments(latex: str) -> str:
    ts, inserts = tokens(latex), []
    for i, token in enumerate(ts):
        if token.value not in _ACCENTS:
            continue
        j = i + 1
        while j < len(ts) and ts[j].value.isspace():
            j += 1
        if j < len(ts):
            atom = ts[j].value
            if (len(atom) == 1 and atom.isalnum()) or atom in _SYMBOLS:
                inserts.extend(((ts[j].start, "{"), (ts[j].end, "}")))
    for pos, value in sorted(inserts, reverse=True):
        latex = latex[:pos] + value + latex[pos:]
    return latex


def _loose_source(latex: str) -> str:
    body, _ = split_equation(_without_comments(latex))
    # Keep the original group: its declaration must not affect neighbouring
    # symbols or change the argument boundaries of another command.
    roman = lambda m: r"{\mathrm{" + m.group(1) + "}}"
    whole_roman = _ROMAN.fullmatch(body)
    body = (r"\mathrm{" + whole_roman.group(1) + "}" if whole_roman
            else _ROMAN.sub(roman, body))
    body = _accent_arguments(body)
    body = _WRAPPERS.sub(" ", body)

    def opname(m):
        word = re.sub(r"\s+", "", m.group(1))
        return f"\\{word} " if word in _OPERATORS else m.group(0)

    return _OPNAME.sub(opname, body)


def tokens_at(latex: str, level: str) -> list[str]:
    if level == "strict":
        return normalized_tokens(split_equation(latex)[0])
    if level == "layout":
        return normalized_tokens(split_equation(latex)[0], layout=True)
    toks = normalized_tokens(_loose_source(latex), layout=True)
    # drop sizing commands; "\left." / "\right." delimiters vanish with them
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t in _SIZING:
            if t in (r"\left", r"\right", r"\middle") and i + 1 < len(toks) and toks[i + 1] == ".":
                i += 1
            i += 1
            continue
        out.append(r"\rightarrow" if t == r"\to" else t)
        i += 1
    return out


def score(pred: str, gold: str) -> dict:
    result = {}
    for level in ("strict", "layout", "loose"):
        result[level] = tokens_at(pred, level) == tokens_at(gold, level)
    a, b = tokens_at(pred, "loose"), tokens_at(gold, "loose")
    result["similarity"] = round(SequenceMatcher(None, a, b, autojunk=False).ratio(), 4) if a or b else 1.0
    result["empty"] = not pred.strip()
    return result


def same(a: str, b: str, level: str = "loose") -> bool:
    return tokens_at(a, level) == tokens_at(b, level)
