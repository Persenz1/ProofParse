"""统一中间文档模型。

所有 parser 必须将解析结果转换为这里的 Document 结构，
后续 normalize / markdown 构建只面向该模型，不依赖具体 parser。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# 语义块类型（规范化后的内部类型）
BLOCK_TITLE = "title"
BLOCK_HEADING = "heading"
BLOCK_PARAGRAPH = "paragraph"
BLOCK_EQUATION = "equation"
BLOCK_DROPPED = "dropped"  # 被过滤的块（figure/table/page number 等），保留在 document.json 供追溯


@dataclass
class Metadata:
    title: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    doi: Optional[str] = None


@dataclass
class Block:
    type: str                       # BLOCK_* 常量
    content: str                    # 文本 / LaTeX
    page: Optional[int] = None      # 0-based 页码
    bbox: Optional[list[float]] = None
    level: int = 0                  # heading 层级（1 起），其它块为 0
    source: str = ""                # 例如 "mineru_pipeline"
    extra: dict[str, Any] = field(default_factory=dict)  # parser 原始附加信息（img_path 等）

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Document:
    metadata: Metadata = field(default_factory=Metadata)
    blocks: list[Block] = field(default_factory=list)
    source_pdf: str = ""
    parser: dict[str, str] = field(default_factory=dict)  # name / version / backend

    def to_dict(self) -> dict:
        return {
            "metadata": asdict(self.metadata),
            "source_pdf": self.source_pdf,
            "parser": self.parser,
            "blocks": [b.to_dict() for b in self.blocks],
        }
