"""Formula output formatting, reapplied to raw cached responses without inference."""
from __future__ import annotations

import re
from .lint import check_latex

_TOKEN = re.compile(r"\\[A-Za-z]+|\\.|\$\$?|[{}]|.", re.DOTALL)
_MATH_FUNCTIONS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "sinh", "cosh", "tanh",
    "arcsin", "arccos", "arctan", "exp", "log", "ln", "lim", "max", "min",
    "sup", "inf", "arg", "det", "dim", "mod", "gcd", "lcm", "ker", "rank",
}
_PROSE_WORDS = {"is", "are", "the", "for", "where", "and", "or", "if", "then"}


def normalize_formula(raw: str) -> tuple[str, str | None]:
    """Unwrap a complete formula, never select a formula from surrounding text.

    A crop may contain a multiline aligned/cases formula. Separate Markdown
    formula blocks and explanations remain in ``raw`` and are rejected.
    This is an output-format check; it does not verify the recognition itself.
    """
    text = raw.strip()
    if not text:
        return "", "empty_output"
    if "```" in text or "~~~" in text:
        fenced = re.fullmatch(
            r"(```|~~~)(?:latex|tex|math|markdown)?[ \t]*\r?\n(.*?)\r?\n\1",
            text, re.DOTALL | re.IGNORECASE,
        )
        if not fenced or "```" in fenced[2] or "~~~" in fenced[2]:
            return "", "non_formula_code_fence"
        text = fenced[2].strip()

    markers, top_text = [], []
    depth = 0
    for token in _TOKEN.finditer(text):
        value = token[0]
        if value == "{":
            depth += 1
        elif value == "}":
            depth -= 1
        elif depth == 0:
            if value in ("$", "$$", r"\[", r"\]", r"\(", r"\)"):
                markers.append((value, token.start(), token.end()))
            elif not value.startswith("\\"):
                top_text.append(value)
    if markers:
        pairs = {"$": "$", "$$": "$$", r"\[": r"\]", r"\(": r"\)"}
        if (len(markers) != 2 or markers[0][1] != 0 or markers[1][2] != len(text)
                or pairs.get(markers[0][0]) != markers[1][0]):
            return "", "multiple_or_incomplete_math_delimiters"
        text = text[markers[0][2]:markers[1][1]].strip()

    plain = "".join(top_text)
    words = re.findall(r"[A-Za-z]+", plain)
    if (any((len(word) >= 3 and not word.isupper() and word.lower() not in _MATH_FUNCTIONS)
            or word.lower() in _PROSE_WORDS for word in words)
            or re.search(r"[\u3400-\u9fff]|<[^>]+>|[#`]", plain)):
        return "", "non_formula_text"
    # Two independent display environments are not one crop-level formula.
    if len(re.findall(r"\\begin\{(?:equation\*?|align\*?|gather\*?|displaymath)\}", text)) > 1:
        return "", "multiple_formula_environments"
    if not markers and r"\begin" not in text:
        relation = r"[=<>≤≥≠≈]|\\(?:approx|sim|simeq|equiv|leq?|geq?|neq?)(?![A-Za-z])"
        if sum(bool(re.search(relation, line)) for line in text.splitlines()) > 1:
            return "", "multiple_unwrapped_formulas"
    problems = check_latex(text)
    if problems:
        return "", "invalid_latex:" + ",".join(problems)
    return (text, None) if text else ("", "empty_output")


def content(output: dict) -> tuple[str, str | None]:
    if "raw" in output and output.get("output_error") != "token_limit_reached":
        return normalize_formula(output["raw"])
    return output.get("latex", ""), output.get("output_error")
