"""LaTeX 归一化与相似度比较（公式双识别的判定规则）。

不做数学语义等价证明，只做合理的 normalization + 相似度：
- 去空白、去 \left/\right（保留定界符）、去 \tag{...}
- \mathrm/\mathbf/\mathit/\textbf/\pmb/\boldsymbol 等字体命令剥离
- {x} 单 token 花括号展开、间距命令 \, \; \quad 等移除
- Greek/符号命令保留（\alpha vs \beta 必须区分开）
判定：ratio >= 0.90 PASS；否则 REVIEW（附原始两端结果）。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"\\tag\{[^}]*\}")
# 字体/修饰命令：剥掉命令名，保留内容
_FONT_CMD_RE = re.compile(
    r"\\(?:mathrm|mathbf|mathit|mathsf|mathtt|textbf|textit|pmb|bm|boldsymbol"
    r"|mathnormal|operatorname|mathop|displaystyle|textstyle|scriptstyle)\b")
# 纯间距/尺寸命令：整体删除
_SPACING_CMD_RE = re.compile(
    r"\\(?:,|;|:|!| |quad|qquad|enspace|thinspace|medspace|thickspace"
    r"|big|Big|bigg|Bigg|bigl|bigr|Bigl|Bigr|biggl|biggr|Biggl|Biggr"
    r"|limits|nolimits|displaystyle)\b")
_LEFT_RIGHT_RE = re.compile(r"\\(left|right|middle)\b")
# {x} -> x（单个 token 的花括号）
_SINGLE_BRACE_RE = re.compile(r"\{(\\?[a-zA-Z0-9]+)\}")
# $$ / $ 包裹
_DOLLAR_RE = re.compile(r"\$+")
# 常见函数名：\log 与 log（来自 \operatorname{log} 剥离后）视为相同
_FUNC_NAME_RE = re.compile(
    r"\\(log|ln|lg|sin|cos|tan|cot|sec|csc|exp|min|max|sup|inf|arg|argmin|argmax"
    r"|det|deg|dim|ker|lim|liminf|limsup|Pr|gcd|sinh|cosh|tanh|softmax)\b")
# 公式环境归一：array/aligned/alignedat/gathered/split 结构上等价，去掉列格式
_ENV_RE = re.compile(
    r"\\(?:begin|end)\s*\{(array|aligned|alignedat|gathered|split|multline"
    r"|matrix|pmatrix|bmatrix|vmatrix|cases)\*?\s*\}"
    r"(\s*\{\s*[^{}]*\})?")
_ALIGN_MARK_RE = re.compile(r"&|\\\\|~")
_LEFTOVER_BRACE_RE = re.compile(r"[{}]")


def latex_normalize(latex: str) -> str:
    s = latex.strip()
    s = _DOLLAR_RE.sub("", s)
    s = _TAG_RE.sub("", s)
    s = _ENV_RE.sub("ENV", s)
    s = _ALIGN_MARK_RE.sub("", s)
    # \left( -> ( ；\right. -> . （删除无渲染的右点也可接受，比较层面无差异）
    s = _LEFT_RIGHT_RE.sub("", s)
    s = _FONT_CMD_RE.sub("", s)
    s = _SPACING_CMD_RE.sub("", s)
    s = _FUNC_NAME_RE.sub(r"\1", s)
    for _ in range(3):  # 嵌套单 token 花括号逐层展开
        s = _SINGLE_BRACE_RE.sub(r"\1", s)
    s = _LEFTOVER_BRACE_RE.sub("", s)  # 残余花括号不参与比较
    s = _WS_RE.sub("", s)
    return s


def latex_similarity(a: str, b: str) -> float:
    na, nb = latex_normalize(a), latex_normalize(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def verdict(parser_latex: str, ocr_latex: str, threshold: float = 0.90) -> tuple[str, float]:
    """返回 (PASS|REVIEW, similarity)。"""
    sim = latex_similarity(parser_latex, ocr_latex)
    return ("PASS" if sim >= threshold else "REVIEW", round(sim, 4))
