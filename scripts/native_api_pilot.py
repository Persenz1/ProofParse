"""Repeat the fixed MiMo pilot with automatic PDF text-layer evidence only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mimo_judge_pilot as pilot
from proofparse.pdf.native import page_characters, region_evidence

IDS = 't01 t02 t03 t04 t05 t10 t11 t15 t20 t21 t22 t23 t24'.split()


def prepare(original: Path, pdf_dir: Path, out: Path, checked: bool = False):
    import pymupdf
    start = time.perf_counter()
    tasks = json.loads((original / 'tasks.json').read_text(encoding='utf-8'))
    tasks = [t for t in tasks if t['id'] in IDS]
    pages = {}
    for task in tasks:
        task['images'] = [str((original / image).resolve()) for image in task['images']]
        if checked:
            from proofparse.formula.qc import check_latex
            task['local_program_checks'] = {
                'candidate_b_present': bool(task['b']),
                'equation_number_applicable': task['kind'] == 'display',
                'note': 'Automatic checks, no human labels. Structural LaTeX errors prevent faithful transcription. '
                        'An absent B requires not_provided, not match. Number fields for non-display tasks are not_applicable.',
            }
        if task['kind'] not in ('display', 'inline'):
            continue  # unchanged figure controls
        key = (task['paper'], task['page'])
        if key not in pages:
            with pymupdf.open(pdf_dir / (task['paper'] + '.pdf')) as pdf:
                page = pdf[task['page']]
                pages[key] = (page_characters(page), (page.rect.width, page.rect.height))
        chars, size = pages[key]
        evidence = region_evidence(chars, size, task['source_region_bbox_1000'], task['target_bbox_1000'])
        target = evidence['target_bbox_pt']
        if checked:
            from proofparse.formula.native import analyze, number_candidates
            numbers = number_candidates(chars, target) if task['kind'] == 'display' else None
            constraints = analyze(evidence, task['a'], task['b'], numbers=numbers)
            task['local_program_checks'].update(
                a_syntax=check_latex(task['a']), b_syntax=check_latex(task['b']),
                native_findings=constraints['findings'], number_association=constraints['number_association'])
        # Keep the formula plus same-row peripheral labels, not unrelated prose.
        chars = [c for c in evidence['characters'] if c['in_target'] or
                 target[1]-2 <= (c['bbox_pt'][1]+c['bbox_pt'][3])/2 <= target[3]+2]
        fonts = list(dict.fromkeys(c['font'] for c in chars))
        task['pdf_text_layer'] = {
            'note': 'Automatically extracted raw PDF evidence. Unicode mappings and font flags can be wrong; '
                    'positions and font changes aid image reading but do not prove correctness. '
                    'No human-confirmed glyph mappings or previous judgments are included. '
                    'Rows are in PDF drawing order, not guaranteed mathematical reading order. '
                    'Coordinates are displayed-page PDF points, top-left origin. in_target=false rows are context only.',
            'fonts': fonts,
            'target_bbox_pt': [round(x, 3) for x in target],
            'columns': ['character', 'font_index', 'font_flags', 'glyph_id', 'size_pt',
                        'baseline_x', 'baseline_y', 'left', 'top', 'right', 'bottom', 'in_target'],
            'rows': [[c['text'], fonts.index(c['font']), c['font_flags'], c['glyph_id'],
                      round(c['size_pt'], 3), *[round(x, 3) for x in c['origin_pt']],
                      *[round(x, 3) for x in c['bbox_pt']], c['in_target']] for c in chars],
        }
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'tasks.json').open('x', encoding='utf-8') as file:
        json.dump(tasks, file, ensure_ascii=False, indent=2)
    (out / 'prompt.txt').write_text(pilot.INSTRUCTIONS, encoding='utf-8')
    print(json.dumps({'tasks': len(tasks), 'formula_tasks': sum('pdf_text_layer' in t for t in tasks),
                      'preparation_seconds': round(time.perf_counter()-start, 4)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--original', type=Path, default=Path('output/mimo-flash-pilot-20260929'))
    parser.add_argument('--pdf-dir', type=Path, default=Path('E:/Agent Tmp WS/PDF/input'))
    parser.add_argument('--model', choices=['mimo-v2.6-flash', 'mimo-v2.6-pro'])
    parser.add_argument('--thinking', choices=['disabled', 'enabled'], default='disabled')
    parser.add_argument('--limit', type=int, default=13)
    parser.add_argument('--checked', action='store_true', help='Also include automatic local checks, without human glyph mappings')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.original, args.pdf_dir, args.out, args.checked)
        return 0
    if not args.model:
        parser.error('--model is required for run')
    if not os.environ.get('MIMO_API_KEY'):
        for line in (Path(__file__).resolve().parents[1] / '.env').read_text(encoding='utf-8-sig').splitlines():
            name, sep, value = line.partition('=')
            if sep and name.strip() == 'MIMO_API_KEY':
                os.environ['MIMO_API_KEY'] = value.strip()
    return pilot.run(args.out, args.limit, 4, False, args.thinking,
                     8192 if args.thinking == 'enabled' else 512,
                     results=args.out / f'{args.model}-{args.thinking}', model=args.model)


if __name__ == '__main__':
    raise SystemExit(main())
