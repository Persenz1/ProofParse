"""Locate math segments in LaTeX source.

This is a scanner, not a TeX engine: it recognises the delimiters authors
actually write ($, $$, \\( \\), \\[ \\], math environments, \\ensuremath) and
skips comments, verbatim material and macro definitions. Math produced by
author macros is invisible here; the gold builder detects it afterwards as
uncoloured math glyphs and reports those pages as incomplete.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_MATH_ENVS = {"equation", "align", "alignat", "flalign", "gather", "multline", "eqnarray",
              "displaymath", "math", "dmath", "dgroup", "darray", "xalignat", "xxalignat"}
MATH_ENVS = _MATH_ENVS | {e + "*" for e in _MATH_ENVS}
INLINE_ENVS = {"math"}
ALIGNMENT_ENVS = {e for e in MATH_ENVS if e.rstrip("*") in
                  {"align", "alignat", "flalign", "gather", "multline", "eqnarray",
                   "xalignat", "xxalignat", "dgroup", "darray"}}
VERBATIM_ENVS = {"verbatim", "verbatim*", "Verbatim", "BVerbatim", "LVerbatim", "lstlisting",
                 "minted", "comment", "filecontents", "filecontents*", "spverbatim", "tcblisting"}

# Argument shapes of definition commands; their bodies are never typeset math.
_NEWCOMMAND = ("name", "opt", "opt", "group")
DEFINITIONS = {
    **{c: _NEWCOMMAND for c in ("newcommand", "renewcommand", "providecommand",
                                "DeclareRobustCommand")},
    **{c: ("name", "params", "group") for c in ("def", "gdef", "edef", "xdef")},
    "DeclareMathOperator": ("name", "group"),
    "newenvironment": ("group", "opt", "opt", "group", "group"),
    "renewenvironment": ("group", "opt", "opt", "group", "group"),
    **{c: ("name", "group", "group") for c in ("NewDocumentCommand", "RenewDocumentCommand",
                                              "ProvideDocumentCommand", "DeclareDocumentCommand",
                                              "DeclarePairedDelimiter")},
    "DeclarePairedDelimiterX": ("name", "opt", "group", "group", "group"),
    "NewDocumentEnvironment": ("group", "group", "group", "group"),
    "newtheorem": ("group", "opt", "group", "opt"),
    "let": ("name", "eq", "name"),
    "tikzset": ("group",), "pgfplotsset": ("group",),
}


@dataclass(frozen=True)
class MathSegment:
    start: int          # whole segment including delimiters
    end: int
    body_start: int
    body_end: int
    delim: str          # $ | $$ | \( | \[ | env | ensuremath
    env: str | None
    display: bool
    context: tuple[str, ...]  # enclosing text-mode environments, outermost first
    line: int


def _skip_group(text: str, i: int, open_: str = "{", close: str = "}") -> int:
    """i points at the opening char; return index after the matching close."""
    depth = 0
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            i = _line_end(text, i)
            continue
        if c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def _line_end(text: str, i: int) -> int:
    j = text.find("\n", i)
    return len(text) if j < 0 else j + 1


def _skip_ws(text: str, i: int) -> int:
    while i < len(text):
        if text[i] in " \t\r\n":
            i += 1
        elif text[i] == "%":
            i = _line_end(text, i)
        else:
            break
    return i


def _read_cs(text: str, i: int) -> tuple[str, int]:
    """i points at a backslash. Return (name, index after it)."""
    j = i + 1
    if j < len(text) and text[j].isalpha():
        while j < len(text) and (text[j].isalpha() or text[j] == "@"):
            j += 1
        return text[i + 1:j], j
    return text[i + 1:j + 1], j + 1


def _read_env_name(text: str, i: int) -> tuple[str | None, int]:
    j = _skip_ws(text, i)
    if j < len(text) and text[j] == "{":
        end = text.find("}", j)
        if end > 0:
            return text[j + 1:end].strip(), end + 1
    return None, i


def _skip_definition(text: str, i: int, shape: tuple[str, ...]) -> int:
    if i < len(text) and text[i] == "*":
        i += 1
    for part in shape:
        j = _skip_ws(text, i)
        if part == "name":
            if j < len(text) and text[j] == "{":
                i = _skip_group(text, j)
            elif j < len(text) and text[j] == "\\":
                i = _read_cs(text, j)[1]
        elif part == "opt":
            if j < len(text) and text[j] == "[":
                i = _skip_group(text, j, "[", "]")
        elif part == "params":
            while j < len(text) and text[j] != "{":
                j += 1
            i = j
        elif part == "eq":
            i = j + 1 if j < len(text) and text[j] == "=" else j
        elif part == "group":
            if j < len(text) and text[j] == "{":
                i = _skip_group(text, j)
            elif j < len(text) and text[j] == "\\":  # \def\x\y style body
                i = _read_cs(text, j)[1]
    return i


def _skip_verb(text: str, i: int) -> int:
    """i is just after \\verb (or \\lstinline)."""
    if i < len(text) and text[i] == "*":
        i += 1
    if i < len(text) and text[i] == "[":
        i = _skip_group(text, i, "[", "]")
    if i >= len(text):
        return i
    delim = text[i]
    if delim == "{":
        return _skip_group(text, i)
    end = text.find(delim, i + 1)
    return len(text) if end < 0 else end + 1


def _find_math_end(text: str, i: int, delim: str, env: str | None) -> tuple[int, int] | None:
    """Scan math from body start; return (body_end, segment_end)."""
    depth = 0
    nesting = 0
    while i < len(text):
        c = text[i]
        if c == "%":
            i = _line_end(text, i)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        elif c == "$" and depth == 0:
            if delim == "$$" and text.startswith("$$", i):
                return i, i + 2
            if delim == "$":
                return i, i + 1
        elif c == "\\":
            name, j = _read_cs(text, i)
            if depth == 0 and ((delim == r"\(" and name == ")") or (delim == r"\[" and name == "]")):
                return i, j
            if env and name in ("begin", "end"):
                found, k = _read_env_name(text, j)
                if found == env:
                    if name == "begin":
                        nesting += 1
                    elif nesting:
                        nesting -= 1
                    else:
                        return i, k
                i = k if found else j
                continue
            i = j
            continue
        i += 1
    return None


def scan(text: str, *, body_only: bool = False) -> list[MathSegment]:
    """Return math segments in source order. body_only restricts the scan to
    \\begin{document}..\\end{document} (use for the main file)."""
    i, stop = 0, len(text)
    if body_only:
        m = re.search(r"\\begin\s*\{document\}", text)
        i = m.end() if m else len(text)
        m = re.search(r"\\end\s*\{document\}", text[i:])
        stop = i + m.start() if m else len(text)
    segments: list[MathSegment] = []
    context: list[str] = []
    line_starts = [0] + [m.end() for m in re.finditer("\n", text)]

    def line_of(pos: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    def add(start, body_start, delim, env, display):
        found = _find_math_end(text, body_start, delim, env)
        if found is None:
            return len(text)
        body_end, end = found
        segments.append(MathSegment(start, end, body_start, body_end, delim, env, display,
                                    tuple(context), line_of(start)))
        return end

    while i < stop:
        c = text[i]
        if c == "%":
            i = _line_end(text, i)
        elif c == "$":
            if text.startswith("$$", i):
                i = add(i, i + 2, "$$", None, True)
            else:
                i = add(i, i + 1, "$", None, False)
        elif c == "\\":
            name, j = _read_cs(text, i)
            if name == "(":
                i = add(i, j, r"\(", None, False)
            elif name == "[":
                i = add(i, j, r"\[", None, True)
            elif name in ("verb", "lstinline", "mintinline"):
                if name == "mintinline":
                    j = _skip_group(text, _skip_ws(text, j))
                i = _skip_verb(text, j)
            elif name in DEFINITIONS:
                i = _skip_definition(text, j, DEFINITIONS[name])
            elif name == "ensuremath":
                k = _skip_ws(text, j)
                if k < len(text) and text[k] == "{":
                    end = _skip_group(text, k)
                    segments.append(MathSegment(i, end, k + 1, end - 1, "ensuremath", None, False,
                                                tuple(context), line_of(i)))
                    i = end
                else:
                    i = k
            elif name == "begin":
                env, k = _read_env_name(text, j)
                if env in MATH_ENVS:
                    i = add(i, k, "env", env, env not in INLINE_ENVS)
                elif env in VERBATIM_ENVS:
                    m = re.compile(r"\\end\s*\{" + re.escape(env) + r"\}").search(text, k)
                    i = m.end() if m else len(text)
                else:
                    if env:
                        context.append(env)
                    i = k
            elif name == "end":
                env, k = _read_env_name(text, j)
                if env and context and context[-1] == env:
                    context.pop()
                i = k
            else:
                i = j
        else:
            i += 1
    return segments


_TRAILING_BREAK = re.compile(r"(?:\\\\\s*(?:\[[^\]]*\])?\s*)$")


def marker_positions(text: str, seg: MathSegment) -> tuple[int, int]:
    """Where to open and close a colour marker, both inside the math body.

    Alignment environments must not end with a row break after the marker,
    or the closing marker would add an empty row.
    """
    open_at = seg.body_start
    close_at = seg.body_end
    body = text[seg.body_start:seg.body_end]
    if seg.env in ALIGNMENT_ENVS:
        m = _TRAILING_BREAK.search(body.rstrip())
        if m:
            close_at = seg.body_start + m.start()
    return open_at, close_at


_INCLUDE = re.compile(r"\\(input|include|subfile)\s*\{([^}]+)\}|\\(?:sub)?import\s*\{([^}]*)\}\s*\{([^}]+)\}")


def includes(text: str, *, body_only: bool = False) -> list[str]:
    """Relative paths of files included from the (body of the) given source."""
    start = 0
    if body_only:
        m = re.search(r"\\begin\s*\{document\}", text)
        start = m.end() if m else len(text)
    found = []
    for m in _INCLUDE.finditer(text, start):
        line_start = text.rfind("\n", 0, m.start()) + 1
        if "%" in text[line_start:m.start()].replace(r"\%", ""):
            continue
        found.append(m.group(2) if m.group(1) else (m.group(3) or "") + m.group(4))
    return found
