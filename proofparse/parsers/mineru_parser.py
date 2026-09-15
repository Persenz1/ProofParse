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

    def parse(self, pdf_path: Path, work_dir: Path, asset_dir: Path | None = None) -> Document:
        pdf_path = Path(pdf_path).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            config.mineru_exe(),
            "-p", str(pdf_path),
            "-o", str(work_dir),
            "-b", config.MINERU_BACKEND,
            "-d", config.resolve_device(),
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
        for i, item in enumerate(raw):
            block = self._convert_block(item)
            block.block_id = f"b{i:06d}"
            doc.blocks.append(block)

        import shutil
        for block in doc.blocks:
            if block.type not in ("figure", "table", "unknown"):
                continue
            src = candidates[0].parent / block.extra.get("img_path", "")
            if src.is_file():
                rel = Path("assets") / f"{block.block_id}{src.suffix}"
                dst = (asset_dir or work_dir.parent) / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                block.extra["asset"] = rel.as_posix()

        doc.metadata = self._extract_metadata(doc.blocks)
        return doc

    # ------------------------------------------------------------------
    def _convert_block(self, item: dict) -> Block:
        btype = item.get("type", "text")
        bbox = item.get("bbox")
        page = item.get("page_idx")
        extra = {k: v for k, v in item.items()
                 if k not in {"type", "text", "bbox", "page_idx", "text_level", "text_format"}}

        def joined(value):
            if isinstance(value, list):
                return "\n\n".join(joined(x) for x in value)
            if isinstance(value, dict):
                return joined(value.get("text", value.get("content", "")))
            return str(value or "")

        if btype in ("image", "chart", "table"):
            prefix = "image" if btype == "image" else btype
            caption = joined(item.get(f"{prefix}_caption", item.get("img_caption", [])))
            footnote = joined(item.get(f"{prefix}_footnote", item.get("img_footnote", [])))
            return Block(type="table" if btype == "table" else "figure",
                         content=joined(item.get("table_body", "")) if btype == "table" else "",
                         page=page, bbox=bbox, source="mineru_pipeline",
                         extra={**extra, "caption": caption, "footnote": footnote,
                                "structure_verified": False})

        if btype in ("list", "code"):
            content = joined(item.get("list_items", [])) if btype == "list" else joined(item.get("code_body", ""))
            return Block(type=btype, content=content or joined(item.get("text", "")),
                         page=page, bbox=bbox, source="mineru_pipeline", extra=extra)

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
            # 首页 header 可能实际是论文标题，不能按上游类型直接丢弃。
            return Block(type=BLOCK_PARAGRAPH if btype == "header" and page == 0 else BLOCK_DROPPED, content=" ".join(p for p in parts if p),
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

        if not text and btype != "text":
            return Block(type="unknown", content=joined(item.get("content", "")),
                         page=page, bbox=bbox, source="mineru_pipeline",
                         extra={"orig_type": btype, **extra})

        # 页脚之外的文字（包括脚注）保留。
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
            if title_idx is not None and b.type == BLOCK_PARAGRAPH:
                break
            if b.type == BLOCK_TITLE and (b.page or 0) == 0:
                # 连续的刊名/论文名标题块，使用作者段落前的最后一个。
                md.title = b.content
                title_idx = i

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
        all_text = re.sub(r"(10\.\d{4,9}/[^\s<>]+-)\s+([A-Za-z0-9])", r"\1\2", all_text)
        m = _DOI_RE.search(all_text)
        if m:
            md.doi = m.group(0).rstrip(".,")
        # year 只从版权行提取（"© 2016 IEEE"），不从摘要正文猜——
        # 实测从正文猜会把 "WMT 2014" 当成发表年
        m = _COPYRIGHT_YEAR_RE.search(all_text)
        if m:
            md.year = int(m.group(1))
        return md
