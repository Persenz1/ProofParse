"""Structural LaTeX checks. Passing proves nothing about content; failing
means the string cannot be delivered as-is."""
from __future__ import annotations

import re

from .syntax import tokens


def _array_column_overflow(latex: str) -> bool:
    values = [token.value for token in tokens(latex) if not token.value.isspace()]

    def group(start):
        if start >= len(values) or values[start] != "{":
            return [], start
        end, depth = start + 1, 1
        while end < len(values) and depth:
            if values[end] == "{":
                depth += 1
            elif values[end] == "}":
                depth -= 1
            end += 1
        return (values[start + 1:end - 1] if depth == 0 else []), end

    stack = []
    i = 0
    while i < len(values):
        value = values[i]
        if value in (r"\begin", r"\end"):
            name, i = group(i + 1)
            name = "".join(name)
            if value == r"\begin":
                columns = None
                if name == "array":
                    declaration, i = group(i)
                    if declaration and all(v in "lcr|" for v in declaration):
                        columns = sum(v in "lcr" for v in declaration)
                stack.append({"name": name, "columns": columns, "cells": 1,
                              "maximum": 1, "complex": False})
            elif stack and stack[-1]["name"] == name:
                current = stack.pop()
                if (current["columns"] and not current["complex"]
                        and current["maximum"] > current["columns"]):
                    return True
            continue
        if stack and stack[-1]["columns"] is not None:
            current = stack[-1]
            if value == "&":
                current["cells"] += 1
                current["maximum"] = max(current["maximum"], current["cells"])
            elif value == r"\\":
                current["cells"] = 1
            elif value == r"\multicolumn":
                current["complex"] = True
        i += 1
    return False


def check_latex(latex: str) -> list[str]:
    """返回问题列表；空列表表示通过。"""
    problems: list[str] = []

    if "\ufffd" in latex:
        problems.append("replacement_char")

    # 只统计非转义花括号：\left\{ ... \right. 中的 \{ 不参与配对计数
    n_open = len(re.findall(r"(?<!\\)\{", latex))
    n_close = len(re.findall(r"(?<!\\)\}", latex))
    if n_open != n_close:
        problems.append(f"brace_mismatch({n_open}vs{n_close})")

    n_left = len(re.findall(r"\\left(?![a-zA-Z])", latex))
    n_right = len(re.findall(r"\\right(?![a-zA-Z])", latex))
    if n_left != n_right:
        problems.append(f"left_right_mismatch({n_left}vs{n_right})")

    begins = re.findall(r"\\begin\{([^}]*)\}", latex)
    ends = re.findall(r"\\end\{([^}]*)\}", latex)
    if sorted(begins) != sorted(ends):
        problems.append("begin_end_mismatch")

    if re.search(r"(.)\1{9,}", latex):
        problems.append("suspicious_repetition")

    if _array_column_overflow(latex):
        problems.append("array_column_overflow")

    # A delimiter pair cannot cross a brace group or alignment cell, even
    # when the total numbers of left/right and braces happen to match.
    depth = 0
    delimiters = []
    for token in re.findall(r'\\(?:begin|end)\s*\{[^}]*\}|\\left(?![a-zA-Z])|\\right(?![a-zA-Z])|\\[a-zA-Z]+|\\.|[{}&]', latex):
        if token.startswith(r'\begin'):
            depth += 100
        elif token.startswith(r'\end'):
            depth -= 100
        elif token == '{':
            depth += 1
        elif token == '}':
            if delimiters and delimiters[-1] == depth:
                problems.append('delimiter_crosses_group')
            depth -= 1
            if depth < 0:
                problems.append('unexpected_close_brace')
        elif token == r'\left':
            delimiters.append(depth)
        elif token == r'\right':
            if not delimiters or delimiters.pop() != depth:
                problems.append('delimiter_scope_mismatch')
        elif token in ('&', r'\\') and depth in delimiters:
            problems.append('delimiter_crosses_alignment')

    return list(dict.fromkeys(problems))
