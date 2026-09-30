"""Conservative candidate agreement, never a proof of mathematical correctness."""
from __future__ import annotations

from difflib import SequenceMatcher

from .syntax import split_equation, tokens, unwrap_math


_ALIASES = {r"\leq": r"\le", r"\geq": r"\ge", r"\ne": r"\neq"}
_TEXT = {r"\text", r"\textrm", r"\textnormal", r"\textbf", r"\textit",
         r"\textsf", r"\texttt", r"\mbox", r"\hbox", r"\operatorname"}
_LAYOUT = {r"\dfrac": r"\frac", r"\tfrac": r"\frac"}
_SPACING = {r"\,", r"\;", r"\:", r"\!", r"\quad", r"\qquad", r"\ "}
_SYMBOLS = {"\\" + name for name in (
    "alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa "
    "lambda mu nu xi pi varpi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega "
    "Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega infty prime partial nabla ell"
).split()}


def normalized_tokens(latex: str, *, layout: bool = False) -> list[str]:
    """Normalize whitespace and explicit notation aliases without erasing groups.

    Fonts, operators and alignment separators stay intact. Text-command arguments
    remain opaque, including spaces. Only single-token scripts receive implicit
    braces; x^12 stays different from x^{12}.
    """
    ts = tokens(unwrap_math(latex))
    if any(t.value in ("%", r"\verb", r"\def", r"\newcommand", r"\catcode") for t in ts):
        return [unwrap_math(latex)]
    result = []
    i = 0
    while i < len(ts):
        value = ts[i].value
        i += 1
        if value.isspace(): continue
        if value in _TEXT:
            result.append(value)
            while i < len(ts) and ts[i].value.isspace(): i += 1
            if i < len(ts) and ts[i].value == "*":
                result.append("*")
                i += 1
                while i < len(ts) and ts[i].value.isspace(): i += 1
            if i < len(ts) and ts[i].value == "{":
                depth = 0
                while i < len(ts):
                    literal = ts[i].value
                    result.append(literal)
                    i += 1
                    if literal == "{": depth += 1
                    elif literal == "}": depth -= 1
                    if depth == 0: break
            continue
        value = _ALIASES.get(value, value)
        if layout:
            if value in _SPACING: continue
            value = _LAYOUT.get(value, value)
        result.append(value)
        if value in ("^", "_"):
            while i < len(ts) and ts[i].value.isspace(): i += 1
            if i < len(ts):
                atom = ts[i].value
                if (len(atom) == 1 and atom not in "{}\\^_$%&#") or atom in _SYMBOLS:
                    result.extend(("{", atom, "}"))
                    i += 1
    return result


def latex_normalize(latex: str) -> str:
    # Preserve token boundaries: \\alpha x must not become \\alphax.
    return "\x1f".join(normalized_tokens(latex))


def latex_similarity(a: str, b: str) -> float:
    na, nb = normalized_tokens(a), normalized_tokens(b)
    return SequenceMatcher(None, na, nb, autojunk=False).ratio() if na and nb else 0.0


def compare_latex(parser_latex: str, ocr_latex: str) -> dict:
    a_body, a_tags = split_equation(parser_latex)
    b_body, b_tags = split_equation(ocr_latex)
    a, b = normalized_tokens(a_body), normalized_tokens(b_body)
    if not a or not b:
        relation = "missing"
    elif a == b:
        relation = "exact" if a_body == b_body else "notation"
    elif normalized_tokens(a_body, layout=True) == normalized_tokens(b_body, layout=True):
        relation = "layout"
    else:
        relation = "content"
    tag_keys = lambda tags: [(t.value, t.starred) for t in tags]
    numbers = ("equal" if tag_keys(a_tags) == tag_keys(b_tags) else
               "missing_parser" if not a_tags else "missing_ocr" if not b_tags else "different")
    diffs = [{"a_tokens": [i, j], "b_tokens": [k, l], "a": a[i:min(j, i + 12)], "b": b[k:min(l, k + 12)],
              **({"truncated": True} if j - i > 12 or l - k > 12 else {})}
             for op, i, j, k, l in SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
             if op != "equal"]
    return {"body_relation": relation, "number_relation": numbers,
            "numbers_a": [t.raw for t in a_tags], "numbers_b": [t.raw for t in b_tags],
            "differences": diffs[:8], "difference_count": len(diffs)}


def verdict(parser_latex: str, ocr_latex: str, threshold: float = 0.90) -> tuple[str, float]:
    comparison = compare_latex(parser_latex, ocr_latex)
    # Legacy PASS means candidate agreement only. Layout/number differences still
    # require review; similarity is never an acceptance rule.
    from .qc import check_latex
    agreement = (comparison["body_relation"] in ("exact", "notation")
                 and comparison["number_relation"] == "equal"
                 and not check_latex(parser_latex) and not check_latex(ocr_latex))
    return ("PASS" if agreement else "REVIEW", round(latex_similarity(parser_latex, ocr_latex), 4))
