"""文本覆盖率检查（位置感知版）：检测 parser 丢字（召回错误）。

方法：
1. pypdf visitor_text 提取带坐标的文字层块（用户空间坐标，原点左下）。
2. 坐标换算到 MinerU 的 1000x1000 归一化空间（原点左上），
   按 bbox 把每个文字块指派给对应的 MinerU block。
   落在 image/table/caption/footnote 等 dropped 块里的文字不参与正文检查，
   从根本上避免 caption/表格单元格造成的误报。
3. 对每个保留段落块，比较"该区域文字层原文"与"parser 输出"的
   规范化相似度（difflib ratio）。严重不一致且缺失量超过阈值才报警。
4. 安全自动修复：parser 输出是文字层原文的"后缀"（典型 IEEE drop-cap
   首段前半句丢失）时，把缺失前缀从文字层补回该块开头。
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from pypdf import PdfReader

from ..models.document import BLOCK_PARAGRAPH, Block
from .textnorm import dehyphenate, fix_dropcap, normalize_for_match

_LATEX_CMD_RE = re.compile(r"\\[a-zA-Z]+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")

_RATIO_THRESHOLD = 0.85      # 低于此相似度视为可疑
_MIN_DEFICIT_CHARS = 40      # 规范化后缺失字符数阈值


# ---------------------------------------------------------------- 坐标提取

def _extract_chunks(pdf_path: Path) -> list[list[tuple[str, float, float]]]:
    """每页 [(text, x, y), ...]，坐标为 PDF 用户空间（原点左下）。"""
    reader = PdfReader(str(pdf_path))
    pages: list[list[tuple[str, float, float]]] = []
    for page in reader.pages:
        chunks: list[tuple[str, float, float]] = []

        def visitor(text, cm, tm, font_dict, font_size):
            if text.strip():
                chunks.append((text, float(tm[4]), float(tm[5])))

        page.extract_text(visitor_text=visitor)
        pages.append(chunks)
    return pages


def _norm1000(x: float, y: float, pw: float, ph: float) -> tuple[float, float]:
    """用户空间(左下原点) -> MinerU 归一化(左上原点, 0-1000)。"""
    return x / pw * 1000.0, (ph - y) / ph * 1000.0


def _assign_chunks(pages, blocks: list[Block]) -> dict[int, list[str]]:
    """把文字块指派给包含它的最小 bbox 所属 block（block 用 id 索引）。"""
    # 预计算 bbox
    boxes = []
    for b in blocks:
        if b.page is not None and b.bbox:
            boxes.append((b.page, b.bbox, id(b)))
    by_page: dict[int, list] = {}
    for pg, bb, bid in boxes:
        by_page.setdefault(pg, []).append((bb, bid))

    out: dict[int, list[str]] = {}
    for page_idx, chunks in enumerate(pages):
        boxes_pg = by_page.get(page_idx)
        if not boxes_pg:
            continue
        for text, nx, ny in chunks:
            # 指派给包含该点的面积最小的 block
            best_bid, best_area = None, None
            for bb, bid in boxes_pg:
                if bb[0] <= nx <= bb[2] and bb[1] <= ny <= bb[3]:
                    area = (bb[2] - bb[0]) * (bb[3] - bb[1])
                    if best_area is None or area < best_area:
                        best_bid, best_area = bid, area
            if best_bid is not None:
                out.setdefault(best_bid, []).append(text)
    return out


# ------------------------------------------------------- 带映射的规范化

def _normalize_with_map(raw: str) -> tuple[str, list[int]]:
    """返回 (norm_str, idx_map)：norm_str 第 i 个字符对应 raw 的第 idx_map[i] 个字符。"""
    norm_chars: list[str] = []
    idx_map: list[int] = []
    for i, ch in enumerate(raw):
        for c in unicodedata.normalize("NFKD", ch):
            if unicodedata.combining(c):
                continue
            c = c.lower()
            if "a" <= c <= "z" or "0" <= c <= "9":
                norm_chars.append(c)
                idx_map.append(i)
    return "".join(norm_chars), idx_map


def _norm_block_content(text: str) -> str:
    text = _LATEX_CMD_RE.sub("", text)
    text = _HTML_TAG_RE.sub("", text)
    return normalize_for_match(text)


# ---------------------------------------------------------------- 主流程

def check_coverage(pdf_path: Path, blocks: list[Block]) -> dict:
    """返回 {'fixes': [...], 'warnings': [...]}；自动修复直接就地修改 blocks。"""
    reader = PdfReader(str(pdf_path))
    page_sizes = [(float(p.mediabox.width), float(p.mediabox.height)) for p in reader.pages]

    raw_pages = _extract_chunks(pdf_path)
    # 坐标换算
    pages_norm: list[list[tuple[str, float, float]]] = []
    for page_idx, chunks in enumerate(raw_pages):
        pw, ph = page_sizes[page_idx]
        pages_norm.append([(t, *_norm1000(x, y, pw, ph)) for t, x, y in chunks])

    chunk_map = _assign_chunks(pages_norm, blocks)

    fixes: list[dict] = []
    warnings: list[dict] = []

    for b in blocks:
        if b.type != BLOCK_PARAGRAPH or not b.content:
            continue
        chunks = chunk_map.get(id(b))
        if not chunks:
            # 该块没有任何文字层内容（可能纯公式段落或 OCR 生成），无法判断，跳过
            continue
        raw_tl = dehyphenate(" ".join(chunks))
        norm_tl, idx_map = _normalize_with_map(raw_tl)
        norm_b = _norm_block_content(b.content)
        if not norm_tl:
            continue

        ratio = SequenceMatcher(None, norm_tl, norm_b).ratio()

        # 判定依据是缺失规模而非相似度：长段落丢一整句相似度仍 >0.9。
        # deficit = 文字层文本中所有不匹配位置的总字符数（用 matching_blocks 累计，
        # 不能用最长公共子串——零散差异会让它严重高估缺失）
        sm = SequenceMatcher(None, norm_tl, norm_b)
        matched = sum(mb.size for mb in sm.get_matching_blocks())
        deficit = len(norm_tl) - matched
        if deficit < _MIN_DEFICIT_CHARS:
            continue

        # 安全自动修复：block 文本完整是文字层的后缀 -> 前缀丢失（drop-cap 场景）
        def _mostly_prose(norm_piece: str) -> bool:
            """待补回内容必须基本是散文（字母占比 >=90%）。
            防止把表格残渣（数字密集的单元格文本）补进正文。"""
            if not norm_piece:
                return False
            n_alpha = sum(1 for c in norm_piece if c.isalpha())
            return n_alpha / len(norm_piece) >= 0.9

        if norm_b and norm_b in norm_tl:
            j = norm_tl.find(norm_b)
            if j >= _MIN_DEFICIT_CHARS and _mostly_prose(norm_tl[:j]):
                raw_prefix = fix_dropcap(raw_tl[: idx_map[j - 1] + 1].strip())
                if raw_prefix:
                    b.content = raw_prefix + " " + b.content
                    fixes.append({
                        "type": "text_recall_autofix",
                        "page": b.page,
                        "restored_text": raw_prefix[:300],
                    })
                    continue
            # block 是前缀 -> 后缀丢失，同理补回
            if (j == 0 and len(norm_tl) - len(norm_b) >= _MIN_DEFICIT_CHARS
                    and _mostly_prose(norm_tl[len(norm_b):])):
                raw_suffix = raw_tl[idx_map[len(norm_b)]:].strip()
                if raw_suffix:
                    b.content = b.content + " " + raw_suffix
                    fixes.append({
                        "type": "text_recall_autofix",
                        "page": b.page,
                        "restored_text": raw_suffix[:300],
                    })
                    continue

        warnings.append({
            "type": "text_recall",
            "page": b.page,
            "bbox": b.bbox,
            "similarity": round(ratio, 3),
            # 相似度中等偏高时，差异几乎都来自行内公式的文字层替换字符
            # （Σ→P、α→a 等），parser 输出通常比文字层更准——标记而非报警
            "likely_cause": "math_divergence" if ratio >= 0.5 else "possible_text_loss",
            "missing_text": raw_tl[:300],
            "parser_text": b.content[:200],
            "status": "needs_review",
        })

    return {"fixes": fixes, "warnings": warnings}
