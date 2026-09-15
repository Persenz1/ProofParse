"""保守的 LaTeX 一致性比较；相似度只用于排序，不证明数学正确。"""
from __future__ import annotations
import re
from difflib import SequenceMatcher


def latex_normalize(latex: str) -> str:
    s = latex.strip()
    if s.startswith("$$") and s.endswith("$$"):
        s = s[2:-2]
    elif s.startswith("$") and s.endswith("$"):
        s = s[1:-1]
    return re.sub(r"\s+", " ", s).strip()


def latex_similarity(a: str, b: str) -> float:
    na, nb = latex_normalize(a), latex_normalize(b)
    return SequenceMatcher(None, na, nb).ratio() if na and nb else 0.0


def verdict(parser_latex: str, ocr_latex: str, threshold: float = 0.90) -> tuple[str, float]:
    a, b = latex_normalize(parser_latex), latex_normalize(ocr_latex)
    return ("PASS" if a and a == b else "REVIEW", round(latex_similarity(a, b), 4))
