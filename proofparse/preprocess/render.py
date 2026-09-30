"""Page rendering and cropping in PDF points (displayed page, top-left origin)."""
from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium


def crop_regions(pdf_path: Path, jobs: list[tuple[int, list[float], Path, float]], scale: float = 3.0) -> None:
    """jobs: (page, bbox_pt, out_path, pad_pt). Each page is rendered once."""
    by_page: dict[int, list] = {}
    for page, bbox, out, pad in jobs:
        by_page.setdefault(page, []).append((bbox, Path(out), pad))
    if not by_page:
        return
    with pdfium.PdfDocument(str(pdf_path)) as pdf:
        for page_index, crops in sorted(by_page.items()):
            page = pdf[page_index]
            image = page.render(scale=scale).to_pil()
            page.close()
            for bbox, out, pad in crops:
                box = (max(0, int((bbox[0] - pad) * scale)), max(0, int((bbox[1] - pad) * scale)),
                       min(image.width, int((bbox[2] + pad) * scale + 0.999)),
                       min(image.height, int((bbox[3] + pad) * scale + 0.999)))
                if box[2] <= box[0] or box[3] <= box[1]:
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                image.crop(box).save(out)


def render_page(pdf_path: Path, page_index: int, out_path: Path, scale: float = 1.5) -> Path:
    with pdfium.PdfDocument(str(pdf_path)) as pdf:
        page = pdf[page_index]
        image = page.render(scale=scale).to_pil()
        page.close()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return out_path
