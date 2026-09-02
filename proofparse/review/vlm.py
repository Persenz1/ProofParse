"""多模态裁决后端。

后端抽象：输入裁剪图 + 双候选 + 封闭问题，输出结构化 JSON：
    {"choice": "parser"|"ocr"|"custom",
     "corrected_latex": "..." | null,
     "confidence": 0.0-1.0,
     "reason": "..."}

当前实现 OpenAI 兼容接口（chat/completions，base64 图），配置：
    PROOFPARSE_VLM_BASE_URL   如 https://api.moonshot.cn/v1
    PROOFPARSE_VLM_API_KEY
    PROOFPARSE_VLM_MODEL      如 kimi-latest / moonshot-v1-32k-vision-preview
    PROOFPARSE_VLM_TIMEOUT    秒，默认 120
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from .collect import KIND_TEXT, ReviewItem

_CHOICES = ("parser", "ocr", "custom")


class VLMError(Exception):
    pass


def build_prompt(item: ReviewItem) -> str:
    """封闭问题：两个候选哪个与图一致，或给出正确答案。要求纯 JSON 输出。"""
    if item.kind == KIND_TEXT:
        task = (
            "这是科研论文 PDF 某区域的裁剪图。下面有两个文本候选："
            "A 是解析器输出的文本，B 是 PDF 内嵌文字层提取的文本。"
            "请对照图片判断哪个候选与图片实际内容一致。"
        )
    else:
        task = (
            "这是科研论文中一个数学公式的裁剪图。下面有两个 LaTeX 候选："
            "A 来自版式解析器，B 来自独立公式 OCR 模型。"
            "请对照图片判断哪个候选的 LaTeX 与图片中的公式一致。"
        )
    return (
        f"{task}\n\n"
        f"候选 A（{item.label_a}）：\n{item.candidate_a}\n\n"
        f"候选 B（{item.label_b}）：\n{item.candidate_b}\n\n"
        "规则：\n"
        "1. 若 A 与图片一致，choice 填 \"parser\"；若 B 一致，填 \"ocr\"；"
        "若两者都有误，填 \"custom\" 并在 corrected_latex 给出你校对后的正确版本。\n"
        "2. 只判断图片中实际可见的内容，绝不脑补。裁剪图可能紧贴内容边缘，"
        "候选中任何在图里完全看不见的符号、文字或数字，都不能作为选择该候选的理由；"
        "若某候选包含图中不存在的内容，应视为错误候选。\n"
        "3. confidence 取 0~1：图片清晰且确定时 ≥0.9；模糊或只能部分辨认时 <0.7。\n"
        "4. 严格只输出一个 JSON 对象，不要输出任何其他文字：\n"
        '{"choice": "parser|ocr|custom", "corrected_latex": "…或null", '
        '"confidence": 0.95, "reason": "一句话理由"}'
    )


def parse_verdict(raw: str) -> dict:
    """从模型输出中 robust 解析 JSON verdict。"""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise VLMError(f"输出中无 JSON: {raw[:200]!r}")
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        # 模型常把 LaTeX 反斜杠直接写进字符串（非法 JSON 转义），修复后重试
        fixed = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", m.group(0))
        try:
            obj = json.loads(fixed)
        except json.JSONDecodeError as e:
            raise VLMError(f"JSON 解析失败: {e}: {m.group(0)[:200]!r}")
    choice = str(obj.get("choice", "")).strip().lower()
    if choice not in _CHOICES:
        raise VLMError(f"非法 choice: {choice!r}")
    try:
        confidence = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "choice": choice,
        "corrected_latex": obj.get("corrected_latex") or None,
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": str(obj.get("reason", ""))[:500],
    }


class OpenAICompatVLM:
    """OpenAI 兼容 chat/completions 后端（图片走 base64 data URL）。"""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None,
                 model: Optional[str] = None, timeout: Optional[float] = None):
        self.base_url = (base_url or os.environ.get("PROOFPARSE_VLM_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.environ.get("PROOFPARSE_VLM_API_KEY") or ""
        self.model = model or os.environ.get("PROOFPARSE_VLM_MODEL") or ""
        self.timeout = timeout or float(os.environ.get("PROOFPARSE_VLM_TIMEOUT", "120"))
        self.max_tokens = int(os.environ.get("PROOFPARSE_VLM_MAX_TOKENS", "4096"))
        # 厂商私有扩展参数（如 MiMo 的 {"thinking": {"type": "disabled"}}），JSON 字符串
        self.extra_body = json.loads(os.environ.get("PROOFPARSE_VLM_EXTRA_BODY", "{}"))
        if not (self.base_url and self.api_key and self.model):
            raise VLMError(
                "多模态后端未配置：请设置 PROOFPARSE_VLM_BASE_URL / "
                "PROOFPARSE_VLM_API_KEY / PROOFPARSE_VLM_MODEL（或用 CLI 参数传入）"
            )

    def adjudicate(self, item: ReviewItem, image_path: Path, retries: int = 2) -> dict:
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": build_prompt(item)},
                ],
            }],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            **self.extra_body,
        }
        body = json.dumps(payload).encode("utf-8")
        last_err: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                raw = self._post(body)
                verdict = parse_verdict(raw)
                verdict["model"] = self.model
                return verdict
            except Exception as e:
                last_err = e
                if attempt < retries:
                    time.sleep(2 * (attempt + 1))
        raise VLMError(f"裁决失败（重试 {retries} 次后）: {last_err}")

    def _post(self, body: bytes) -> str:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise VLMError(f"HTTP {e.code}: {detail}")
        if data.get("error"):
            raise VLMError(f"API error: {data['error']}")
        return data["choices"][0]["message"]["content"]
