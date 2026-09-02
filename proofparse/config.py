"""集中配置。所有可调参数放这里，避免散落在代码中。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 运行 MinerU / 公式模型所用的 Python 解释器。
# 优先级：PROOFPARSE_PYTHON 环境变量 > 当前解释器（pip install -e . 后直接可用）。
_PROOFPARSE_PYTHON = os.environ.get("PROOFPARSE_PYTHON", sys.executable)

# mineru 可执行文件路径（默认取 PROOFPARSE_PYTHON 同目录 Scripts 下）
def mineru_exe() -> str:
    env = os.environ.get("MINERU_EXE")
    if env:
        return env
    scripts = Path(_PROOFPARSE_PYTHON).parent / "Scripts" / "mineru.exe"
    if scripts.exists():
        return str(scripts)
    return "mineru"  # 退化为 PATH 查找

# MinerU 运行参数
MINERU_BACKEND = os.environ.get("PROOFPARSE_MINERU_BACKEND", "pipeline")
MINERU_DEVICE = os.environ.get("PROOFPARSE_MINERU_DEVICE", "cuda")

# 输出根目录（可用命令行 -o 覆盖）
DEFAULT_OUTPUT_ROOT = Path(os.environ.get("PROOFPARSE_OUTPUT", "output"))

# References 章节标题（规范化小写后精确匹配，见 normalize/filtering.py）
REFERENCE_HEADINGS = {
    "references", "reference", "bibliography", "literature cited",
    "works cited", "参考文献",
}

# 需要在 Markdown 中丢弃的 MinerU 块类型
DROP_BLOCK_TYPES = {
    "image", "chart", "table",
    "page_number", "page_footer", "page_footnote", "header", "footer",
    "aside_text", "seal",
}
