"""Scoring a predicted formula against gold LaTeX.

Three levels, each strictly looser than the previous one:

strict  token-identical after whitespace/alias normalisation (compare.py)
layout  also ignores spacing commands and \\dfrac/\\tfrac
loose   also ignores sizing (\\left \\right \\big ...), \\displaystyle, \\limits,
        alignment-environment wrappers and operator-name spelling

"loose" is the level used for "correct". It never ignores a symbol, a
script, a font command, a group or a matrix cell. A rendering-based metric
(CDM) can be added beside these; it does not replace them.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..formula.compare import normalized_tokens
from ..formula.syntax import split_equation

_SIZING = {r"\left", r"\right", r"\big", r"\Big", r"\bigg", r"\Bigg", r"\bigl", r"\bigr", r"\Bigl",
           r"\Bigr", r"\biggl", r"\biggr", r"\Biggl", r"\Biggr", r"\bigm", r"\Bigm", r"\middle",
           r"\displaystyle", r"\textstyle", r"\limits", r"\nolimits"}
_WRAPPERS = re.compile(r"\\(?:begin|end)\s*\{(?:aligned|align\*?|split|gathered|gather\*?|equation\*?|"
                       r"multline\*?|eqnarray\*?|flalign\*?|alignat\*?|alignedat)\}(?:\{\d+\})?")
_OPERATORS = ("sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh log ln lg exp max min sup inf "
              "lim liminf limsup det dim ker deg gcd hom arg Pr mod").split()
_OPNAME = re.compile(r"\\(?:operatorname\*?|mathrm)\s*\{\s*((?:[A-Za-z]\s*)+)\}")


def _loose_source(latex: str) -> str:
    body, _ = split_equation(latex)
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
        out.append(t)
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
