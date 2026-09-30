"""PDF text layer and page objects: the program-side evidence every later
stage builds on. Prose comes from here whenever the layer is usable; OCR is
the fallback, not the default.

Requires PyMuPDF. Coordinates use the displayed page, top-left origin, in PDF
points (including page rotation). Glyph IDs are local to the PDF font.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path

# Font families whose glyphs are mathematical symbols or math italics. Math set
# in ordinary text fonts (mathptmx, Word's Cambria italic) is not caught here.
_MATH_FONT = re.compile(
    r"^(?:CM(?:MI|SY|EX|BSY|MIB)|MSAM|MSBM|EU[FSRX]|EUFM|EUSM|RSFS|LM(?:Math|MathItalic|MathSymbols|MathExtension)"
    r"|STIX(?:Two)?Math|STIXGeneral-Italic|XITSMath|Asana|CambriaMath|Cambria-Math|NewCM.*Math|TeXGyre\w*Math"
    r"|LatinModernMath|(?:new)?tx(?:mi|sy|ex|sya|syb)|NewTXMI|NewTXBMI|ntx(?:mi|sy|ex)|rtxmi|px(?:mi|sy|ex)|zxmi"
    r"|MTMI|MTSY|MTEX|MathematicalPi|Symbol(?:MT)?|Euclid|Mathematica|StandardSymbol|MT-Extra|MTExtra)",
    re.IGNORECASE)


def font_name(raw: str) -> str:
    return re.sub(r"^[A-Z]{6}\+", "", raw or "")


def is_math_font(name: str) -> bool:
    name = font_name(name)
    return bool(_MATH_FONT.match(name)) or "math" in name.lower()


def page_characters(page) -> list[dict]:
    """Read once per page; preserve drawing order and suspicious encodings."""
    import pymupdf

    rotation = page.rotation_matrix
    fonts = {}
    for font in page.get_fonts(full=True):
        name = re.sub(r"^[A-Z]{6}\+", "", font[3])
        fonts.setdefault(name, set()).add(font[0])
    result = []
    for span_index, span in enumerate(page.get_texttrace()):
        xrefs = fonts.get(span["font"], set())
        for char_index, (codepoint, glyph, origin, bbox) in enumerate(span["chars"]):
            char = chr(codepoint) if 0 <= codepoint <= 0x10FFFF else "\ufffd"
            rect = pymupdf.Rect(bbox) * rotation
            point = pymupdf.Point(origin) * rotation
            result.append({
                "source_index": [span_index, char_index],
                "text": char, "codepoint": codepoint, "glyph_id": glyph,
                "font": span["font"], "font_flags": span["flags"],
                "font_xref": next(iter(xrefs)) if len(xrefs) == 1 else None,
                "size_pt": span["size"], "origin_pt": list(point),
                "bbox_pt": list(rect), "direction_unrotated": list(span["dir"]),
                "direction_pt": [span['dir'][0] * rotation.a + span['dir'][1] * rotation.c,
                                 span['dir'][0] * rotation.b + span['dir'][1] * rotation.d],
                "render_type": span["type"], "opacity": span["opacity"],
                "suspicious_encoding": char == "\ufffd" or
                    unicodedata.category(char) in ("Cc", "Co", "Cs"),
            })
    from .fontnames import attach_glyph_names
    attach_glyph_names(page.parent, result)
    return result


def body_font(characters: list[dict]) -> str | None:
    counts = Counter(c["font"] for c in characters if c["render_type"] != 3 and c["opacity"] > 0)
    return counts.most_common(1)[0][0] if counts else None


def region_evidence(characters: list[dict], region: list[float], target: list[float],
                    page_body_font: str | None = None) -> dict:
    """Keep glyphs intersecting region; target membership uses the glyph centre.

    A wider region retains equation numbers and nearby prose. Neither membership
    nor PDF font flags establishes mathematical meaning or a correct Unicode map.
    """
    selected = []
    for char in characters:
        x0, y0, x1, y1 = char["bbox_pt"]
        if x1 < region[0] or x0 > region[2] or y1 < region[1] or y0 > region[3]:
            continue
        cx, cy = (x0+x1)/2, (y0+y1)/2
        selected.append(char | {"in_target": target[0] <= cx <= target[2]
                               and target[1] <= cy <= target[3]})
    return {
        "coordinate_system": "displayed_page_top_left_pt",
        "body_font": page_body_font or body_font(characters),
        "region_bbox_pt": list(region), "target_bbox_pt": list(target), "characters": selected,
        "fonts": sorted({c["font"] for c in selected}),
        "n_suspicious_encoding": sum(c["suspicious_encoding"] for c in selected),
        "status": "text_present" if selected else "no_text_in_region",
    }


def text_layer_status(page, characters: list[dict]) -> dict:
    """Classify whether prose can be read from the text layer.

    good      born-digital text, few undecodable glyphs
    degraded  text exists but many glyphs lack a Unicode mapping
    ocr_layer invisible text over an image (a previous OCR pass; unverified)
    none      no usable text; the page needs OCR
    """
    visible = [c for c in characters if c["render_type"] != 3 and c["opacity"] > 0]
    invisible = len(characters) - len(visible)
    suspicious = sum(c["suspicious_encoding"] for c in visible)
    area = abs(page.rect)
    image_cover = sum(abs(page.rect & info["bbox"]) for info in page.get_image_info()) / area if area else 0
    if len(visible) >= 20:
        status = "degraded" if suspicious > 0.05 * len(visible) else "good"
    elif invisible >= 20:
        status = "ocr_layer"
    else:
        status = "none"
    sizes = Counter(round(c["size_pt"], 1) for c in visible)
    return {"status": status, "n_visible": len(visible), "n_invisible": invisible,
            "n_suspicious": suspicious, "image_cover": round(image_cover, 3),
            "body_font": body_font(characters),
            "body_size": sizes.most_common(1)[0][0] if sizes else None}


def page_objects(page, limit: int = 4000) -> dict:
    """Image and vector-drawing boxes; figure boundaries are refined against these."""
    rot = page.rotation_matrix
    images = [[round(v, 2) for v in (info["bbox"] * rot)] for info in page.get_image_info()]
    drawings = []
    for d in page.get_drawings():
        r = d["rect"] * rot
        if r.is_empty and r.width < 0.1 and r.height < 0.1:
            continue
        drawings.append([round(v, 2) for v in r])
        if len(drawings) >= limit:
            break
    return {"images": images, "drawings": drawings, "drawings_truncated": len(drawings) >= limit}


def extract(pdf_path: Path, out_dir: Path) -> list[dict]:
    """Write native/page_NNNN.json.gz per page; return page records for the IR."""
    import pymupdf
    from ..ir import write_json
    pages = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            chars = page_characters(page)
            layer = text_layer_status(page, chars)
            write_json(Path(out_dir) / f"page_{page.number:04d}.json.gz",
                       {"characters": chars, "objects": page_objects(page)}, compress=True)
            pages.append({"index": page.number, "width": round(page.rect.width, 2),
                          "height": round(page.rect.height, 2), "rotation": page.rotation,
                          "text_layer": layer})
    return pages


def load_page(native_dir: Path, page: int) -> dict:
    from ..ir import read_json
    return read_json(Path(native_dir) / f"page_{page:04d}.json.gz")
