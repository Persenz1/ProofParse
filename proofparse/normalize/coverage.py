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

def _extract_chunks(pdf_path: Path) -> list:
    """PDFium 文字行矩形；返回原始文字及可见页面左上原点归一化坐标。"""
    import pypdfium2 as pdfium
    pages = []
    with pdfium.PdfDocument(str(pdf_path)) as pdf:
        for page in pdf:
            textpage = page.get_textpage()
            left, bottom, right, top = page.get_bbox()
            width, height = right-left, top-bottom
            angle = page.get_rotation()
            chunks = []
            for i in range(textpage.count_rects()):
                l, b, r, t = textpage.get_rect(i)
                text = textpage.get_text_bounded(l, b, r, t).strip()
                if not text: continue
                x, y = ((l+r)/2-left)/width, ((b+t)/2-bottom)/height
                if angle == 90: nx, ny = y, x
                elif angle == 180: nx, ny = 1-x, y
                elif angle == 270: nx, ny = 1-y, 1-x
                else: nx, ny = x, 1-y
                chunks.append((text, nx*1000, ny*1000))
            pages.append(chunks)
            textpage.close()
            page.close()
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
    pages_norm = _extract_chunks(pdf_path)

    chunk_map = _assign_chunks(pages_norm, blocks)

    fixes: list[dict] = []
    warnings: list[dict] = check_orphan_equation_numbers(blocks)

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

        warnings.append({
            "type": "text_recall",
            "page": b.page,
            "bbox": b.bbox,
            "block_id": b.block_id,
            "similarity": round(ratio, 3),
            # 相似度中等偏高时，差异几乎都来自行内公式的文字层替换字符
            # （Σ→P、α→a 等），parser 输出通常比文字层更准——标记而非报警
            "likely_cause": "math_divergence" if ratio >= 0.5 else "possible_text_loss",
            "missing_text": raw_tl,
            "parser_text": b.content,
            "status": "needs_review",
        })

    # 从源出发保留没有任何解析块接收的文字行；不能因为缺块而跳过。
    for page, chunks in enumerate(pages_norm):
        boxes = [b.bbox for b in blocks if b.page == page and b.bbox]
        missing = [(text, x, y) for text, x, y in chunks
                   if not any(bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3] for bb in boxes)]
        if missing:
            warnings.append({"type": "unassigned_source", "page": page,
                             "missing_text": "\n".join(t for t, _, _ in missing),
                             "parser_text": "", "status": "needs_review",
                             "likely_cause": "unassigned_source"})

    return {"fixes": fixes, "warnings": warnings}


def check_orphan_equation_numbers(blocks: list[Block]) -> list[dict]:
    """Flag a right-aligned equation number with no equation on its row.

    This also works without a PDF text layer. The crop includes the missing
    left-hand expression; the number's own tiny bbox would hide the omission.
    """
    warnings = []
    for b in blocks:
        if (b.type != BLOCK_PARAGRAPH or not b.bbox or b.extra.get('merged_into')
                or b.bbox[0] < 700 or not re.fullmatch(r'\(\s*\d+[a-z]?\s*\)', b.content.strip())):
            continue
        y = (b.bbox[1] + b.bbox[3]) / 2
        if any(other.page == b.page and other.type == 'equation' and other.bbox
               and other.bbox[1]-5 <= y <= other.bbox[3]+5 for other in blocks):
            continue
        warnings.append({'type': 'orphan_equation_number', 'page': b.page,
                         'bbox': [0, max(0, b.bbox[1]-8), b.bbox[2], min(1000, b.bbox[3]+8)],
                         'block_id': b.block_id, 'parser_text': b.content, 'missing_text': '',
                         'likely_cause': 'orphan_equation_number', 'status': 'needs_review'})
    return warnings
