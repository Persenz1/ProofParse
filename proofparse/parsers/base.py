"""Parser adapter 基类。

新增 parser（Marker、后续 VLM backend 等）只需实现 DocumentParser，
返回统一的 Document 中间模型。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models.document import Document


class DocumentParser(ABC):
    name: str = "base"

    @abstractmethod
    def parse(self, pdf_path: Path, work_dir: Path) -> Document:
        """解析 pdf_path，返回 Document。

        work_dir 用于存放 parser 产生的原始中间文件（MinerU 的 content_list.json 等），
        便于事后追溯与调试。
        """
        raise NotImplementedError
