"""PDF 渲染与区域裁剪：为 QC 警告生成复核图。

注意：MinerU 3.x content_list.json 的 bbox 是 1000x1000 归一化坐标，
必须按页面实际尺寸换算：x_px = bbox_x / 1000 * page_width_pt * scale。
"""
from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium


def render_crop(pdf_path: Path, page_idx: int, bbox1000: list[float],
                out_path: Path, scale: float = 3.0, pad: int = 14) -> Path:
    pdf = pdfium.PdfDocument(str(pdf_path))
    page = pdf[page_idx]
    w, h = page.get_size()
    img = page.render(scale=scale).to_pil()
    x1 = bbox1000[0] / 1000 * w * scale
    y1 = bbox1000[1] / 1000 * h * scale
    x2 = bbox1000[2] / 1000 * w * scale
    y2 = bbox1000[3] / 1000 * h * scale
    crop = img.crop((
        max(0, int(x1) - pad), max(0, int(y1) - pad),
        min(img.width, int(x2) + pad), min(img.height, int(y2) + pad),
    ))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(str(out_path))
    pdf.close()
    return out_path


def render_page(pdf_path: Path, page_idx: int, out_path: Path,
                scale: float = 1.5) -> Path:
    """无 bbox 的警告（如整句丢失）渲染整页供人工定位。"""
    pdf = pdfium.PdfDocument(str(pdf_path))
    img = pdf[page_idx].render(scale=scale).to_pil()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path))
    pdf.close()
    return out_path
