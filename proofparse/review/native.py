"""Attach optional native constraints to existing review tasks, locally."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..pdf.native import page_characters, region_evidence
from ..formula.native import analyze, apply_glyph_map, number_candidates


def pdf_digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def load_glyph_map(path: Path, pdf_path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    if data['pdf_sha256'] != pdf_digest(pdf_path):
        raise ValueError(f'Glyph map belongs to another PDF: {path}')
    return data['glyphs']


def confirm_glyph(pdf_path: Path, map_path: Path, page_index: int,
                  source_index: list[int], text: str, styles: list[str]) -> None:
    """Register a glyph only after the caller has inspected its source image."""
    import pymupdf

    with pymupdf.open(pdf_path) as pdf:
        glyph = next(c for c in page_characters(pdf[page_index]) if c['source_index'] == source_index)
    if glyph['font_xref'] is None:
        raise ValueError('Ambiguous PDF font resource; cannot reuse this glyph mapping')
    if len(text) != 1:
        raise ValueError('A glyph mapping requires one Unicode character')
    mappings = load_glyph_map(map_path, pdf_path)
    mappings = [m for m in mappings if (m['font_xref'], m['glyph_id']) != (glyph['font_xref'], glyph['glyph_id'])]
    mappings.append({'font_xref': glyph['font_xref'], 'glyph_id': glyph['glyph_id'],
                     'text': text, 'styles': styles,
                     'source': {'page': page_index, 'source_index': source_index,
                                'bbox_pt': glyph['bbox_pt'], 'font': glyph['font']}})
    map_path.write_text(json.dumps({'pdf_sha256': pdf_digest(pdf_path), 'glyphs': mappings},
                                  ensure_ascii=False, indent=2), encoding='utf-8')


def attach_native(items, paper_dir: Path, document: dict) -> None:
    formulas = [it for it in items if it.kind in ('formula_display', 'formula_inline')
                and it.page is not None and it.bbox]
    if not formulas:
        return
    pdf_path = paper_dir / (document.get('source_pdf') or 'source.pdf')
    if not pdf_path.is_file():
        for it in formulas: it.extra['native_constraints'] = {'status': 'source_pdf_missing'}
        return
    try:
        import pymupdf
    except ImportError:
        for it in formulas: it.extra['native_constraints'] = {'status': 'pymupdf_not_installed'}
        return
    mappings = load_glyph_map(paper_dir / 'native_glyphs.json', pdf_path)
    details = {}
    with pymupdf.open(pdf_path) as pdf:
        cache = {}
        for it in formulas:
            page = pdf[it.page]
            width, height = page.rect.width, page.rect.height
            if it.page not in cache:
                cache[it.page] = apply_glyph_map(page_characters(page), mappings)
            chars = cache[it.page]
            target = list(it.bbox)
            if it.kind == 'formula_inline':
                target = [target[0]/width*1000, target[1]/height*1000,
                          target[2]/width*1000, target[3]/height*1000]
            evidence = region_evidence(chars, (width, height), target, target)
            numbers = None
            if it.kind == 'formula_display' and it.issue_type != 'orphan_equation_number':
                others = [[b['bbox'][0]*width/1000, b['bbox'][1]*height/1000,
                           b['bbox'][2]*width/1000, b['bbox'][3]*height/1000]
                          for b in document['blocks'] if b.get('type') == 'equation'
                          and b.get('page') == it.page and b.get('bbox')]
                numbers = number_candidates(chars, evidence['target_bbox_pt'], others)
            constraints = analyze(evidence, it.candidate_a, it.candidate_b, numbers=numbers)
            constraints['status'] = evidence['status']
            constraints['coordinate_system'] = evidence['coordinate_system']
            constraints['target_bbox_pt'] = evidence['target_bbox_pt']
            constraints['fonts'] = {str(c['font_xref']): c['font'] for c in evidence['characters']
                                    if c['font_xref'] is not None}
            constraints['glyphs'] = [
                {k: c[k] for k in ('source_index', 'text', 'glyph_id', 'font_xref', 'size_pt',
                                   'origin_pt', 'bbox_pt', 'font_flags', 'suspicious_encoding',
                                   'mapped_text', 'mapped_styles', 'mapping_source') if k in c}
                for c in evidence['characters'] if c['in_target']]
            details[it.issue_id] = constraints
            raw = json.dumps(constraints, ensure_ascii=False, sort_keys=True)
            # Keep full per-glyph geometry locally; model-facing tasks carry only
            # actionable constraints plus an address for inspecting the details.
            it.extra['native_constraints'] = {
                'status': constraints['status'],
                'number_association': constraints['number_association'],
                'findings': constraints['findings'],
                'candidates': {name: {
                    'numbers': value['numbers'],
                    'unsupported_commands': value['unsupported_commands'],
                    'alignment_counts': {state: sum(a['status'] == state for a in value['alignment'])
                                         for state in ('unique_symbol', 'ambiguous', 'not_in_text_layer')}
                } for name, value in constraints['candidates'].items()},
                'details_file': str((paper_dir / 'native_evidence.json').resolve()),
                'details_key': it.issue_id,
                'evidence_hash': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
            }
            if constraints['findings'] and not it.review_asset:
                from ..pdf.render import render_crop
                # New native-only issues may previously have had no OCR crop.
                region = list(evidence['target_bbox_pt'])
                for label in constraints['number_association']['candidates']:
                    box = label['bbox_pt']
                    region = [min(region[0], box[0]), min(region[1], box[1]),
                              max(region[2], box[2]), max(region[3], box[3])]
                bbox = [region[0]/width*1000, region[1]/height*1000,
                        region[2]/width*1000, region[3]/height*1000]
                asset = Path('review_assets') / f'native_{it.issue_id}.png'
                render_crop(pdf_path, it.page, bbox, paper_dir / asset)
                it.review_asset = asset.as_posix()

    detail_path = paper_dir / 'native_evidence.json'
    serialized = json.dumps(details, ensure_ascii=False, indent=2)
    if not detail_path.exists() or detail_path.read_text(encoding='utf-8') != serialized:
        detail_path.write_text(serialized, encoding='utf-8')


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Register one visually confirmed glyph for reuse within a PDF.')
    parser.add_argument('paper_dir', type=Path)
    parser.add_argument('--confirm-glyph', nargs=3, type=int, required=True, metavar=('PAGE', 'SPAN', 'CHAR'))
    parser.add_argument('--text', required=True)
    parser.add_argument('--styles', nargs='*', default=[],
                        choices=['bold', 'calligraphic', 'script', 'double_struck', 'fraktur'])
    args = parser.parse_args()
    doc = json.loads((args.paper_dir / 'document.json').read_text(encoding='utf-8'))
    page, span, char = args.confirm_glyph
    confirm_glyph(args.paper_dir / (doc.get('source_pdf') or 'source.pdf'),
                  args.paper_dir / 'native_glyphs.json', page, [span, char], args.text, args.styles)
    print('Saved native_glyphs.json; re-export the worklist to refresh affected evidence.')


if __name__ == '__main__':
    main()
