"""本地质量检测（确定性，不用大模型）。

检查项：
- 公式 LaTeX 合法性（括号配对 / \\left-\\right / \\begin-\\end / 替换字符 / 异常重复）
- 疑似损坏变音符（如 'Cˇ ap'）
- 文本召回（coverage 模块产出，在此汇总）

每条 warning 带 status：
- needs_review：无法自动处理，需多模态模型或人工终审（配 review_assets 裁剪图）
所有能自动修复的问题进 fixes 列表，不占用终审资源。
"""
from __future__ import annotations

import re

from ..models.document import BLOCK_EQUATION, Document
from ..normalize.textnorm import find_suspect_glyphs


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

    return problems


def run_qc(doc: Document, kept_blocks, dropped_blocks, filter_stats: dict,
           coverage_result: dict) -> dict:
    """生成 qc.json 内容（v2，带状态分级与自动修复记录）。"""
    warnings: list[dict] = []

    # 1) 公式 LaTeX 合法性
    eq_count = 0
    for i, b in enumerate(kept_blocks):
        if b.type != BLOCK_EQUATION:
            continue
        eq_count += 1
        problems = check_latex(b.content)
        if problems:
            warnings.append({
                "id": f"eq_{i}",
                "type": "latex_sanity",
                "page": b.page,
                "bbox": b.bbox,
                "problems": problems,
                "content_preview": b.content[:200],
                "status": "needs_review",
            })

    # 2) 疑似损坏变音符
    for i, b in enumerate(kept_blocks):
        if b.type != "paragraph" or not b.content:
            continue
        hits = find_suspect_glyphs(b.content)
        if hits:
            warnings.append({
                "id": f"glyph_{i}",
                "type": "suspect_glyph",
                "page": b.page,
                "bbox": b.bbox,
                "problems": hits[:5],
                "content_preview": b.content[:200],
                "status": "needs_review",
            })

    # 3) 文本召回（无法自动补回的丢失句子）
    for w in coverage_result.get("warnings", []):
        warnings.append({"id": f"recall_p{w['page']}", **w})

    inline_math_count = 0
    for b in kept_blocks:
        if b.type == "paragraph":
            inline_math_count += len(re.findall(r"\$[^$]+\$", b.content))

    fixes = coverage_result.get("fixes", [])
    return {
        "parser": doc.parser,
        "filter_stats": filter_stats,
        "n_display_equations": eq_count,
        "n_inline_math_spans": inline_math_count,
        "n_auto_fixed": len(fixes),
        "fixes": fixes,
        "n_warnings": len(warnings),
        "warnings": warnings,
        "summary": {
            "status": "needs_review" if warnings else "auto_pass",
            "n_needs_review": len(warnings),
        },
    }
