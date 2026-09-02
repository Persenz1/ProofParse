"""MinerU pipeline backend adapter。

通过 subprocess 调用 mineru CLI（与具体 Agent 无关，任何环境都能跑），
然后读取 content_list.json 转成统一 Document 模型。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from .. import config
from ..models.document import (
    BLOCK_DROPPED,
    BLOCK_EQUATION,
    BLOCK_HEADING,
    BLOCK_PARAGRAPH,
    BLOCK_TITLE,
    Block,
    Document,
    Metadata,
)
from .base import DocumentParser

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
# 版权行年份：'© 2016 IEEE' / '©2016' / '(c) 2016'
_COPYRIGHT_YEAR_RE = re.compile(r"[©\(]\s*(?:c\)\s*)?((?:19|20)\d{2})\b", re.IGNORECASE)


def _mineru_version() -> str:
    try:
        out = subprocess.run(
            [config.mineru_exe(), "-v"],
            capture_output=True, text=True, timeout=60,
        )
        m = re.search(r"(\d+\.\d+\.\d+)", out.stdout + out.stderr)
        return m.group(1) if m else "unknown"
    except Exception:
        return "unknown"


class MinerUParser(DocumentParser):
    name = "mineru"

    def parse(self, pdf_path: Path, work_dir: Path) -> Document:
        pdf_path = Path(pdf_path)
        work_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            config.mineru_exe(),
            "-p", str(pdf_path),
            "-o", str(work_dir),
            "-b", config.MINERU_BACKEND,
            "-d", config.MINERU_DEVICE,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(
                f"MinerU 解析失败 (exit {proc.returncode}):\n{proc.stderr[-2000:]}"
            )

        # MinerU 输出: work_dir/<stem>/<method>/<stem>_content_list.json
        candidates = sorted(work_dir.rglob(f"{pdf_path.stem}_content_list.json"))
        if not candidates:
            raise RuntimeError(f"未找到 MinerU 输出的 content_list.json，目录: {work_dir}")
        raw = json.loads(candidates[0].read_text(encoding="utf-8"))

        doc = Document(
            source_pdf=str(pdf_path),
            parser={
                "name": self.name,
                "version": _mineru_version(),
                "backend": config.MINERU_BACKEND,
            },
        )
        for item in raw:
            doc.blocks.append(self._convert_block(item))

        doc.metadata = self._extract_metadata(doc.blocks)
        return doc

    # ------------------------------------------------------------------
    def _convert_block(self, item: dict) -> Block:
        btype = item.get("type", "text")
        bbox = item.get("bbox")
        page = item.get("page_idx")
        extra = {k: v for k, v in item.items()
                 if k not in {"type", "text", "bbox", "page_idx", "text_level", "text_format"}}

        if btype in config.DROP_BLOCK_TYPES:
            # 图/表的 caption、表格正文等文字要保留在 content 里：
            # 覆盖率检查需要它们避免把 caption 句子误判为"正文丢失"
            parts = [item.get("text") or ""]
            for k in ("img_caption", "img_footnote", "table_caption",
                      "table_body", "table_footnote", "chart_caption", "chart_footnote"):
                v = item.get(k)
                if isinstance(v, list):
                    parts.extend(str(x) for x in v)
                elif isinstance(v, str):
                    parts.append(v)
            return Block(type=BLOCK_DROPPED, content=" ".join(p for p in parts if p),
                         page=page, bbox=bbox, source="mineru_pipeline",
                         extra={"orig_type": btype, **extra})

        if btype == "equation":
            latex = (item.get("text") or "").strip()
            # 去掉 MinerU 自带的 $$ 包裹，统一在 markdown 构建时处理
            latex = re.sub(r"^\$\$|\$\$$", "", latex).strip()
            return Block(type=BLOCK_EQUATION, content=latex, page=page, bbox=bbox,
                         source="mineru_pipeline",
                         extra={"text_format": item.get("text_format", "latex"), **extra})

        text = (item.get("text") or "").strip()
        level = item.get("text_level") or 0
        if level:
            # MinerU: text_level=1 通常是论文标题；>=2 为章节标题
            btype_internal = BLOCK_TITLE if level == 1 else BLOCK_HEADING
            return Block(type=btype_internal, content=text, page=page, bbox=bbox,
                         level=level, source="mineru_pipeline", extra=extra)

        # text / list / 其它可保留文本块一律视为段落
        return Block(type=BLOCK_PARAGRAPH, content=text, page=page, bbox=bbox,
                     source="mineru_pipeline",
                     extra={"orig_type": btype, **extra})

    # ------------------------------------------------------------------
    def _extract_metadata(self, blocks: list[Block]) -> Metadata:
        """best-effort 元数据：title 取第一个 title 块；
        authors 取首页 title 与 Abstract 之间的短文本行；
        doi/year 用正则在前两页文本中找。不可靠时留空。"""
        md = Metadata()
        title_idx = None
        for i, b in enumerate(blocks):
            if b.type == BLOCK_TITLE:
                md.title = b.content
                title_idx = i
                break

        # authors：首页、位于 title 之后、"Abstract" 标题之前的段落块
        if title_idx is not None:
            for b in blocks[title_idx + 1:]:
                if b.type in (BLOCK_HEADING, BLOCK_TITLE):
                    break
                if b.type == BLOCK_PARAGRAPH and (b.page or 0) == 0:
                    line = b.content.strip()
                    if line and len(line) < 200:
                        md.authors.append(line)

        # DOI / 版权行可能藏在被过滤的页脚块里（IEEE 论文实测如此），
        # 因此扫描全部块（含 dropped），不受正文过滤影响
        all_text = "\n".join(b.content for b in blocks if (b.page or 0) <= 1)
        m = _DOI_RE.search(all_text)
        if m:
            md.doi = m.group(0).rstrip(".,")
        # year 只从版权行提取（"© 2016 IEEE"），不从摘要正文猜——
        # 实测从正文猜会把 "WMT 2014" 当成发表年
        m = _COPYRIGHT_YEAR_RE.search(all_text)
        if m:
            md.year = int(m.group(1))
        return md
