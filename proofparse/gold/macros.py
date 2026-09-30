"""Expand author macros in gold LaTeX so it is comparable with model output.

OCR models emit what is drawn (\\mathbb{R}), not the author's shorthand (\\R).
Only definitions whose meaning is clear are expanded: \\newcommand family,
undelimited \\def, \\DeclareMathOperator, \\DeclarePairedDelimiter and \\let
aliases. Anything else an author defined is reported, never guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .texscan import _read_cs, _skip_group, _skip_ws

MAX_EXPANSIONS = 2000


@dataclass(frozen=True)
class Macro:
    nargs: int = 0
    default: str | None = None   # optional first argument default
    body: str = ""
    star_variant: str | None = None  # paired delimiters: body used after '*'


def _group_text(text: str, i: int) -> tuple[str, int]:
    i = _skip_ws(text, i)
    if i < len(text) and text[i] == "{":
        end = _skip_group(text, i)
        return text[i + 1:end - 1], end
    if i < len(text) and text[i] == "\\":
        name, end = _read_cs(text, i)
        return "\\" + name, end
    return (text[i], i + 1) if i < len(text) else ("", i)


def _opt_text(text: str, i: int) -> tuple[str | None, int]:
    j = _skip_ws(text, i)
    if j < len(text) and text[j] == "[":
        end = _skip_group(text, j, "[", "]")
        return text[j + 1:end - 1], end
    return None, i


def _name(text: str, i: int) -> tuple[str | None, int]:
    raw, j = _group_text(text, i)
    raw = raw.strip()
    return (raw[1:], j) if raw.startswith("\\") else (None, j)


def collect(text: str) -> tuple[dict[str, Macro], set[str]]:
    """Return (expandable macros, author-defined names that are not expandable)."""
    macros: dict[str, Macro] = {}
    unsupported: set[str] = set()
    for m in re.finditer(r"\\(newcommand|renewcommand|providecommand|DeclareRobustCommand|"
                         r"def|gdef|edef|xdef|DeclareMathOperator|DeclarePairedDelimiter|"
                         r"NewDocumentCommand|RenewDocumentCommand|let)(?![A-Za-z@])", text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        if re.search(r"(?<!\\)%", text[line_start:m.start()]):
            continue
        cmd, i = m.group(1), m.end()
        star = i < len(text) and text[i] == "*"
        if star:
            i += 1
        if cmd in ("def", "gdef", "edef", "xdef"):
            j = _skip_ws(text, i)
            if j >= len(text) or text[j] != "\\":
                continue
            name, j = _read_cs(text, j)
            k = j
            while k < len(text) and text[k] != "{":
                k += 1
            params = text[j:k]
            if not re.fullmatch(r"(?:#\d)*", params.replace(" ", "")) or cmd in ("edef", "xdef"):
                unsupported.add(name)
                continue
            body, _ = _group_text(text, k)
            macros.setdefault(name, Macro(nargs=params.count("#"), body=body))
        elif cmd == "let":
            j = _skip_ws(text, i)
            if j >= len(text) or text[j] != "\\":
                continue
            name, j = _read_cs(text, j)
            j = _skip_ws(text, j)
            if j < len(text) and text[j] == "=":
                j = _skip_ws(text, j + 1)
            if j < len(text) and text[j] == "\\":
                target, _ = _read_cs(text, j)
                if target != name:
                    macros[name] = Macro(body="\\" + target)
        elif cmd == "DeclareMathOperator":
            name, j = _name(text, i)
            if name:
                label, _ = _group_text(text, j)
                macros[name] = Macro(body=f"\\operatorname{'*' if star else ''}{{{label}}}")
        elif cmd == "DeclarePairedDelimiter":
            name, j = _name(text, i)
            if name:
                left, j = _group_text(text, j)
                right, _ = _group_text(text, j)
                macros[name] = Macro(nargs=1, body=f"{left} #1{right}",
                                     star_variant=f"\\left{left} #1\\right{right}")
        elif cmd in ("NewDocumentCommand", "RenewDocumentCommand"):
            name, _ = _name(text, i)
            if name:
                unsupported.add(name)  # xparse signatures are not expanded
        else:
            name, j = _name(text, i)
            if not name:
                continue
            nargs, j = _opt_text(text, j)
            default, j = _opt_text(text, j)
            body, _ = _group_text(text, j)
            try:
                n = int(nargs) if nargs else 0
            except ValueError:
                unsupported.add(name)
                continue
            macro = Macro(nargs=n, default=default, body=body)
            if cmd == "providecommand":
                macros.setdefault(name, macro)
            else:
                macros[name] = macro
    unsupported = {n for n in unsupported if n[:1].isalpha() and n != 'csname'}  # internal \@ / \csname tricks
    for name in unsupported:
        macros.pop(name, None)
    return macros, unsupported


def _substitute(body: str, args: list[str]) -> str:
    return re.sub(r"#(\d)", lambda m: args[int(m.group(1)) - 1] if int(m.group(1)) <= len(args) else m.group(0),
                  body)


def expand(latex: str, macros: dict[str, Macro]) -> tuple[str, bool]:
    """Expand known macros. Returns (text, complete) where complete is False if
    the expansion limit was hit (e.g. a recursive definition)."""
    out = latex
    count = 0
    i = 0
    while i < len(out):
        if out[i] != "\\":
            i += 1
            continue
        name, j = _read_cs(out, i)
        macro = macros.get(name)
        if macro is None:
            i = j
            continue
        count += 1
        if count > MAX_EXPANSIONS:
            return out, False
        body = macro.body
        k = j
        if macro.star_variant is not None and k < len(out) and out[k] == "*":
            body, k = macro.star_variant, k + 1
        args = []
        remaining = macro.nargs
        if macro.default is not None and remaining:
            opt, k = _opt_text(out, k)
            args.append(macro.default if opt is None else opt)
            remaining -= 1
        for _ in range(remaining):
            arg, k = _group_text(out, k)
            args.append(arg)
        replacement = _substitute(body, args)
        replacement = re.sub(r"\\ensuremath\s*", "", replacement)
        # keep a letter-initial continuation from gluing onto a trailing control word
        if re.search(r"\\[A-Za-z]+$", replacement) and k < len(out) and out[k].isalpha():
            replacement += " "
        out = out[:i] + replacement + out[k:]
        # rescan the replacement: macros may expand to other macros
    return out, True


def used_unsupported(latex: str, unsupported: set[str]) -> list[str]:
    return sorted({n for n in re.findall(r"\\([A-Za-z@]+)", latex) if n in unsupported})
