"""Page rendering and cropping in PDF points (displayed page, top-left origin)."""
from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium


def crop_regions(pdf_path: Path, jobs: list[tuple[int, list[float], Path, float | tuple[float, float]]],
                 scale: float = 3.0) -> None:
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
                x_pad, y_pad = pad if isinstance(pad, tuple) else (pad, pad)
                box = (max(0, int((bbox[0] - x_pad) * scale)), max(0, int((bbox[1] - y_pad) * scale)),
                       min(image.width, int((bbox[2] + x_pad) * scale + 0.999)),
                       min(image.height, int((bbox[3] + y_pad) * scale + 0.999)))
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


def crop_fragments(pdf_path: Path, jobs: list[tuple[int, list[list[float]], list[float], Path, float]],
                   scale: float = 3.0) -> None:
    """Stitch wrapped formula segments, excluding the prose inside their union box."""
    from PIL import Image
    by_page = {}
    for page, boxes, baselines, out, pad in jobs:
        by_page.setdefault(page, []).append((boxes, baselines, Path(out), pad))
    if not by_page:
        return
    with pdfium.PdfDocument(str(pdf_path)) as pdf:
        for index, fragments in by_page.items():
            page = pdf[index]
            image = page.render(scale=scale).to_pil()
            page.close()
            for boxes, baselines, out, pad in fragments:
                crops = [image.crop((max(0, int((b[0] - pad) * scale)),
                                     max(0, int((b[1] - pad) * scale)),
                                     min(image.width, int((b[2] + pad) * scale + 0.999)),
                                     min(image.height, int((b[3] + pad) * scale + 0.999))))
                         for b in boxes]
                gap = max(1, round(pad * scale))
                above = [baseline * scale - max(0, int((box[1] - pad) * scale))
                         for box, baseline in zip(boxes, baselines)]
                top = max(above)
                height = round(top + max(c.height - a for c, a in zip(crops, above)))
                merged = Image.new("RGB", (sum(c.width for c in crops) + gap * (len(crops) - 1),
                                           height), "white")
                x = 0
                for crop, anchor in zip(crops, above):
                    merged.paste(crop, (x, round(top - anchor)))
                    x += crop.width + gap
                out.parent.mkdir(parents=True, exist_ok=True)
                merged.save(out)
