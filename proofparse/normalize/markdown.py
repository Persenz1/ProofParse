"""Document -> 语义 Markdown。

只做语义输出：front matter + 标题层级 + 段落 + 公式。
不做版式还原，不加 HTML/CSS。
"""
from __future__ import annotations

import re

from ..models.document import (
    BLOCK_EQUATION,
    BLOCK_HEADING,
    BLOCK_TITLE,
    Document,
)

_SUP_TAG_RE = re.compile(r"</?sup>")


def _clean_inline(text: str) -> str:
    """轻量清理：去掉 MinerU 输出的 <sup> 标签（脚注标记），压缩空白。"""
    text = _SUP_TAG_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_markdown(doc: Document, blocks) -> str:
    md = doc.metadata
    lines: list[str] = []

    # front matter
    lines.append("---")
    if md.title:
        lines.append(f"title: {md.title}")
    if md.authors:
        lines.append("authors:")
        for a in md.authors:
            lines.append(f"  - {_clean_inline(a)}")
    if md.year:
        lines.append(f"year: {md.year}")
    if md.doi:
        lines.append(f"doi: {md.doi}")
    lines.append("---")
    lines.append("")

    for b in blocks:
        if b.type == BLOCK_TITLE:
            continue  # 标题已进入 front matter
        if b.type == BLOCK_HEADING:
            # MinerU level 从 2 起为章节；映射为从 '#' 开始
            hashes = "#" * max(1, min(b.level - 1, 6))
            lines.append(f"{hashes} {_clean_inline(b.content)}")
            lines.append("")
        elif b.type == BLOCK_EQUATION:
            lines.append("$$")
            lines.append(b.content)
            lines.append("$$")
            lines.append("")
        else:  # paragraph
            lines.append(_clean_inline(b.content))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"
