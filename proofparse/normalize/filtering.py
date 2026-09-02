"""确定性过滤：Figure/Table 删除 + References 截断。

原则：不依赖大模型，只根据块类型与标题文本做确定性判断。
"""
from __future__ import annotations

import re

from .. import config
from ..models.document import BLOCK_DROPPED, BLOCK_HEADING, Block

_HEADING_NORM_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")


def _norm_heading(text: str) -> str:
    """'7. References' -> 'references'；'REFERENCES' -> 'references'。"""
    t = text.strip().lower()
    t = _HEADING_NORM_RE.sub("", t)
    return t


def find_references_cutoff(blocks: list[Block]) -> int | None:
    """返回 References 章节标题块的索引；没有则返回 None。

    只认 heading 块（parser 判定为标题、独占一行），
    避免正文中 'References to previous studies ...' 被误判。
    """
    for i, b in enumerate(blocks):
        if b.type != BLOCK_HEADING:
            continue
        if _norm_heading(b.content) in {_HEADING_NORM_RE.sub("", h) for h in config.REFERENCE_HEADINGS}:
            return i
    return None


def apply_filtering(blocks: list[Block]) -> tuple[list[Block], list[Block], dict]:
    """返回 (保留块, 丢弃块, 统计信息)。

    - References 标题及其后所有块整体截断（acknowledgments 若排在 references 之前会保留，
      这是可接受的折衷；多数会议/期刊论文 ack 在 references 前）
    - BLOCK_DROPPED 类型块直接过滤
    """
    cutoff = find_references_cutoff(blocks)
    kept: list[Block] = []
    dropped: list[Block] = []
    truncated = False
    for i, b in enumerate(blocks):
        if cutoff is not None and i >= cutoff:
            dropped.append(b)
            truncated = True
            continue
        if b.type == BLOCK_DROPPED:
            dropped.append(b)
            continue
        kept.append(b)

    stats = {
        "references_cutoff_found": cutoff is not None,
        "n_blocks_total": len(blocks),
        "n_blocks_kept": len(kept),
        "n_blocks_dropped": len(dropped),
    }
    return kept, dropped, stats
