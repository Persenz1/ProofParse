"""Compare previously verified error points, not full-paper accuracy."""
import json
from pathlib import Path

BASE = Path('output/mimo-flash-pilot-20260929')
NEW = Path('output/native-api-pilot-20260930')
CHECKS = {
    't01': {'a': 'match', 'number_a': 'mismatch', 'number_b': 'missing'},
    't02': {'a': 'match', 'number_a': 'mismatch'},
    't03': {'a': 'match', 'number_a': 'mismatch'},
    't04': {'number_a': 'mismatch'},
    't05': {'a': 'mismatch'},
    't10': {'a': 'mismatch'},
    't11': {'a': 'mismatch'},
    't15': {'number_a': 'match'},
    't20': {'a': 'mismatch', 'number_a': 'match'},
    't21': {'a': 'mismatch'},
    't22': {'a': 'mismatch'},
    't23': {'b': 'not_provided'},
    't24': {'b': 'not_provided'},
}


def read_rows(path):
    return {r['id']: r for r in (json.loads(s) for s in path.read_text(encoding='utf-8').splitlines())}


def main():
    configurations = [('mimo-v2.6-flash', 'disabled', BASE),
                      ('mimo-v2.6-flash', 'enabled', BASE/'thinking-errors'),
                      ('mimo-v2.6-pro', 'disabled', BASE/'pro-no-thinking-errors'),
                      ('mimo-v2.6-pro', 'enabled', BASE/'pro-thinking-errors')]
    results = []
    for model, thinking, old_dir in configurations:
        new_dir = NEW/f'{model}-{thinking}'
        if not (new_dir/'runs.jsonl').exists(): continue
        old, new = read_rows(old_dir/'responses.jsonl'), read_rows(new_dir/'responses.jsonl')
        rows = []
        for task, expected in CHECKS.items():
            a, b = old.get(task, {}).get('decision', {}), new.get(task, {}).get('decision', {})
            rows.append({'id': task, 'expected_known_fields': expected,
                         'old_point_pass': all(a.get(k) == v for k, v in expected.items()),
                         'new_point_pass': all(b.get(k) == v for k, v in expected.items()),
                         'old': a, 'new': b})
        summary = json.loads((new_dir/'runs.jsonl').read_text(encoding='utf-8').splitlines()[-1]) if (new_dir/'runs.jsonl').exists() else None
        result = {'model': model, 'thinking': thinking, 'rows': rows,
                  'old_known_points_passed': sum(r['old_point_pass'] for r in rows),
                  'new_known_points_passed': sum(r['new_point_pass'] for r in rows),
                  'new_run': summary}
        results.append(result)
        print(json.dumps({k:v for k,v in result.items() if k not in ('rows','new_run')}))
    (NEW/'comparison.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__': main()
