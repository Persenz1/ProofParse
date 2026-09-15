"""Document -> 语义 Markdown。

只做语义输出：front matter + 标题层级 + 段落 + 公式。
不做版式还原，不加 HTML/CSS。
"""
from __future__ import annotations

import re
import json

from ..models.document import (
    BLOCK_EQUATION,
    BLOCK_HEADING,
    BLOCK_TITLE,
    Document,
)

_SUP_TAG_RE = re.compile(r"</?sup>")


def _clean_inline(text: str) -> str:
    """轻量清理：去掉 MinerU 输出的 <sup> 标签（脚注标记），压缩空白。"""
    # 保留上标引用/脚注边界，避免把 years<sup>12</sup> 变成 years12。
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_markdown(doc: Document, blocks) -> str:
    md = doc.metadata
    lines: list[str] = []

    # front matter
    lines.append("---")
    if md.title:
        lines.append(f"title: {json.dumps(md.title, ensure_ascii=False)}")
    if md.authors:
        lines.append("authors:")
        for a in md.authors:
            lines.append(f"  - {json.dumps(a, ensure_ascii=False)}")
    if md.year:
        lines.append(f"year: {md.year}")
    if md.doi:
        lines.append(f"doi: {md.doi}")
    lines.append("---")
    lines.append("")

    for b in blocks:
        lines.append(f"<!-- {b.block_id} page={(b.page + 1) if b.page is not None else '?'} -->")
        if b.type == BLOCK_TITLE:
            lines.extend([f"# {_clean_inline(b.content)}", ""])
            continue
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
        elif b.type in ("figure", "table", "unknown"):
            caption = b.extra.get("caption", "")
            if caption:
                lines.extend([caption, ""])
            if b.type == "table" and b.extra.get("structure_verified"):
                from .tables import render_table
                lines.extend([render_table(b.content), ""])
            if b.extra.get("asset"):
                lines.extend([f"[{'表格原图' if b.type == 'table' else '原图'} {b.block_id}]({b.extra['asset']})", ""])
            else:
                lines.extend(["[原图缺失，需复查]", ""])
            if b.type == "table" and not b.extra.get("structure_verified"):
                lines.extend(["[表格结构尚未视觉确认；请读取原图。候选保存在 document.json。]", ""])
            if b.extra.get("footnote"):
                lines.extend([b.extra["footnote"], ""])
        elif b.type == "code":
            fence = "`" * max(3, max((len(m.group()) + 1 for m in re.finditer(r"`+", b.content)), default=3))
            lines.extend([fence, b.content, fence, ""])
            for key in ("code_caption", "code_footnote"):
                value = b.extra.get(key, [])
                lines.extend(value if isinstance(value, list) else [value])
        elif b.type == "list":
            lines.extend([b.content, ""])
        else:  # paragraph
            lines.append(_clean_inline(b.content))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"
