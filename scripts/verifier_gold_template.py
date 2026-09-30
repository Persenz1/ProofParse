"""Prepare draft formula gold records from saved, same-crop pilot outputs."""
import argparse
import json
from pathlib import Path


def build_gold(tasks_path, m_path, l_path, pdf_dir):
    tasks = json.loads(tasks_path.read_text(encoding='utf-8'))
    models = {
        name: {t['id']: t['latex'] for t in
               json.loads(path.read_text(encoding='utf-8'))['tasks']}
        for name, path in (('M', m_path), ('L', l_path))
    }
    records = []
    for task in tasks:
        crop = (tasks_path.parent / task['ocr_crop']).resolve()
        pdf = (pdf_dir / (task['paper'] + '.pdf')).resolve()
        for path in (crop, pdf):
            if not path.is_file():
                raise FileNotFoundError(path)
        records.append({
            'id': task['id'], 'paper': task['paper'], 'page': task['page'],
            'kind': task['kind'], 'target_bbox_1000': task['target_bbox_1000'],
            'source_region_bbox_1000': task['source_region_bbox_1000'],
            'crop': str(crop), 'source_pdf': str(pdf),
            'candidates': {'A': task['a'], 'B': task['b'],
                           'M': models['M'][task['id']], 'L': models['L'][task['id']]},
            'gold_latex': '', 'gold_status': 'draft',
            'equivalent_latex': [], 'notes': '',
        })
    return records


def write_gold(records, out):
    """Never replace a gold file that may contain the user's corrections."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as file:
        json.dump(records, file, ensure_ascii=False, indent=2)
        file.write('\n')


def main():
    pilot = Path('output/local-formula-pilot-20260930')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks', type=Path, default=pilot / 'tasks.json')
    parser.add_argument('--m', type=Path, default=pilot / 'PP-FormulaNet_plus-M.json')
    parser.add_argument('--l', type=Path, default=pilot / 'PP-FormulaNet_plus-L.json')
    parser.add_argument('--pdf-dir', type=Path, default=Path('E:/Agent Tmp WS/PDF/input'))
    parser.add_argument('--out', type=Path, default=Path('output/verifier-gold-20260930/gold.json'))
    args = parser.parse_args()
    records = build_gold(args.tasks, args.m, args.l, args.pdf_dir)
    write_gold(records, args.out)
    print(json.dumps({'tasks': len(records), 'draft': len(records), 'confirmed': 0,
                      'output': str(args.out.resolve())}, ensure_ascii=False))


if __name__ == '__main__':
    main()
