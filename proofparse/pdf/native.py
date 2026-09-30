"""Character evidence from a PDF text layer; never an automatic LaTeX verdict.

Requires optional PyMuPDF. Coordinates use the displayed page, top-left origin,
in PDF points (including page rotation). Glyph IDs are local to the PDF font.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
import re


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


def region_evidence(characters: list[dict], page_size: tuple[float, float],
                    region_1000: list[float], target_1000: list[float]) -> dict:
    """Keep intersecting glyphs; target membership uses the glyph's center.

    A wider region retains equation numbers and nearby prose. Neither membership
    nor PDF font flags establishes mathematical meaning or a correct Unicode map.
    """
    width, height = page_size

    def points(box):
        return [box[0]*width/1000, box[1]*height/1000,
                box[2]*width/1000, box[3]*height/1000]

    region, target = points(region_1000), points(target_1000)
    selected = []
    for char in characters:
        x0, y0, x1, y1 = char["bbox_pt"]
        if x1 < region[0] or x0 > region[2] or y1 < region[1] or y0 > region[3]:
            continue
        cx, cy = (x0+x1)/2, (y0+y1)/2
        selected.append(char | {"in_target": target[0] <= cx <= target[2]
                               and target[1] <= cy <= target[3]})
    font_counts = Counter(c['font'] for c in characters if c['render_type'] != 3 and c['opacity'] > 0)
    body_font = font_counts.most_common(1)[0][0] if font_counts else None
    return {
        "coordinate_system": "displayed_page_top_left_pt",
        "body_font": body_font, "page_size_pt": [width, height], "region_bbox_pt": region,
        "target_bbox_pt": target, "characters": selected,
        "fonts": sorted({c["font"] for c in selected}),
        "n_suspicious_encoding": sum(c["suspicious_encoding"] for c in selected),
        "status": "text_present" if selected else "no_text_in_region",
    }
