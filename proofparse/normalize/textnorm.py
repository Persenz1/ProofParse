"""文本规范化工具：用于覆盖率检查的对齐匹配。

原则：匹配用的规范化尽量激进（只留 a-z0-9），
保证跨换行/连字符/变音符/空格的鲁棒包含判断。
"""
from __future__ import annotations

import re
import unicodedata

# 断词连字符：行尾 "mechan-\nical" -> "mechanical"
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(\w)")
_WS_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def dehyphenate(text: str) -> str:
    """恢复 PDF 强制断行造成的断词，同时把换行折叠为空格。

    两种断词形式都处理：行尾 'mechan-\\nical'，以及分块拼接产生的
    're- search'（连字符后换行被折叠成空格）。误判风险（复合词在
    连字符处断行，如 'well-' + 'known'）存在但概率低，且只影响
    补回文本的观感，不影响匹配。
    """
    text = _HYPHEN_BREAK_RE.sub(r"\1\2", text)
    text = re.sub(r"(\w)- (\w)", r"\1\2", text)
    return _WS_RE.sub(" ", text)


_DROPCAP_RE = re.compile(r"^([A-Z]) ([A-Z]{2,})")


def fix_dropcap(text: str) -> str:
    """'T HE last three decades' -> 'THE last three decades'。"""
    return _DROPCAP_RE.sub(r"\1\2", text)


def normalize_for_match(text: str) -> str:
    """激进规范化：NFKD 分解变音符，只保留 [a-z0-9]。

    'Michal Cˇ ap' 和 'Michal Čáp' 都会归一到 'michalcap'，
    're-\nsearch' -> 'research'。
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = dehyphenate(text).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def split_sentences(page_text: str) -> list[str]:
    """把一页的文字层切成句子（保留原文，不做规范化）。"""
    parts = _SENTENCE_SPLIT_RE.split(page_text)
    return [p.strip() for p in parts if p.strip()]


# 疑似损坏变音符：字母 + 间隔型重音符 + 空格 + 小写字母，如 'Cˇ ap' 'Frazzoli´ '
_SUSPECT_GLYPH_RE = re.compile(
    r"[A-Za-z][\u0301\u030c\u02c7\u00b4\u0060\u02dc\u00a8]" + r"\s+[a-z]"
)


def find_suspect_glyphs(text: str) -> list[str]:
    return _SUSPECT_GLYPH_RE.findall(text)
