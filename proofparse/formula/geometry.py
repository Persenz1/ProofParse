"""Conservative script paths and one-matrix row constraints from native geometry."""
from collections import Counter

from .syntax import tokens, split_equation
from .native import extension_glyph, normalized_symbol, symbol, COMPARABLE, ACCENTS

SCRIPT_SIZE_RATIO = 0.85
SCRIPT_BASELINE_SHIFT = 0.15
BASELINE_TOLERANCE = 0.3
MATRICES = {'matrix', 'pmatrix', 'bmatrix', 'vmatrix', 'Bmatrix', 'array'}


def source_roles(chars):
    usable = [c for c in chars if not extension_glyph(c) and
              normalized_symbol(symbol(c)) in COMPARABLE and symbol(c) not in ACCENTS]
    roles, previous = {}, []
    size = max((c['size_pt'] for c in usable), default=0)
    for char in sorted(usable, key=lambda c: (c['origin_pt'][0], c['origin_pt'][1])):
        index = tuple(char['source_index'])
        x, y = char['origin_pt']
        parents = [p for p in previous if p['origin_pt'][0] < x and
                   char['size_pt'] < SCRIPT_SIZE_RATIO * p['size_pt'] and
                   abs(y - p['origin_pt'][1]) <= p['size_pt'] and
                   x - p['bbox_pt'][2] <= 1.5 * p['size_pt']]
        if parents:
            parent = max(parents, key=lambda p: p['origin_pt'][0])
            delta = y - parent['origin_pt'][1]
            parent_role = roles[tuple(parent['source_index'])]
            if abs(delta) > SCRIPT_BASELINE_SHIFT * parent['size_pt'] and parent_role is not None:
                role = 'superscript' if delta < 0 else 'subscript'
                roles[index] = role if parent_role == 'math' else parent_role + '>' + role
            else:
                roles[index] = None
        else:
            roles[index] = 'math' if char['size_pt'] >= SCRIPT_SIZE_RATIO * size else None
        previous.append(char)
    return roles


def geometry_reliable(chars):
    return not any((c.get('suspicious_encoding') and not c.get('mapped_text')) or
                   (not c.get('font') and not c.get('mapped_text')) or
                   abs(c.get('direction_pt', c.get('direction_unrotated', [1, 0]))[1]) > 0.1
                   for c in chars if not extension_glyph(c))


def script_constraint(chars, parsed):
    if not geometry_reliable(chars):
        return {'status': 'unreliable', 'skipped': {},
                'reason': 'Unmapped encoding or non-horizontal writing'}, []
    if parsed['unsupported_commands']:
        return {'status': 'skipped', 'skipped': {'unsupported_commands': parsed['unsupported_commands']},
                'reason': 'Unknown macros may change script scope'}, []
    roles = source_roles(chars)
    source = Counter(normalized_symbol(symbol(c)) for c in chars if not extension_glyph(c))
    candidates = Counter(normalized_symbol(a['text']) for a in parsed['atoms'])
    findings, skipped, checked = [], Counter(), 0
    for atom in parsed['atoms']:
        s = normalized_symbol(atom['text'])
        if s not in COMPARABLE or atom['role'] == 'text':
            continue
        if atom.get('in_fraction'):
            skipped['fraction_symbols'] += 1
            continue
        if source[s] != 1 or candidates[s] != 1:
            skipped['ambiguous_or_missing_symbols'] += 1
            continue
        char = next(c for c in chars if normalized_symbol(symbol(c)) == s and not extension_glyph(c))
        role = roles.get(tuple(char['source_index']))
        if role is None:
            skipped['unanchored_script'] += 1
            continue
        checked += 1
        if role != atom['role']:
            findings.append({'type': 'script_constraint', 'symbol': s, 'source_role': role,
                             'candidate_role': atom['role'], 'source_index': char['source_index']})
    return {'status': 'partial' if skipped else 'checked', 'skipped': dict(skipped),
            'checked_symbols': checked}, findings


def matrix_rows(latex):
    ts = [t.value for t in tokens(split_equation(latex)[0]) if not t.value.isspace()]
    environments, stack, depth, current, rows, i = [], [], 0, None, 1, 0
    row_content = False
    while i < len(ts):
        value = ts[i]
        i += 1
        if value in (r'\begin', r'\end') and i < len(ts) and ts[i] == '{':
            end = i + 1
            while end < len(ts) and ts[end] != '}': end += 1
            name = ''.join(ts[i + 1:end])
            i = end + 1
            if value == r'\begin':
                if name in MATRICES:
                    environments.append(name)
                    if current is not None:
                        return {'status': 'skipped', 'reason': 'Nested matrix environments'}
                    current, depth, rows, row_content = name, 0, 1, False
                stack.append(name)
                if name == 'array' and i < len(ts) and ts[i] == '{':
                    i += 1
                    nesting = 1
                    while i < len(ts) and nesting:
                        nesting += (ts[i] == '{') - (ts[i] == '}')
                        i += 1
            else:
                if not stack or stack.pop() != name:
                    return {'status': 'unreliable', 'reason': 'Unbalanced environment'}
                if name == current:
                    current = None
                    if not row_content and rows > 1:
                        rows -= 1
            continue
        if current:
            if value == '{': depth += 1
            elif value == '}': depth -= 1
            elif value == r'\\' and depth == 0 and stack[-1] == current:
                rows += 1
                row_content = False
            elif value != '&':
                row_content = True
    if len(environments) != 1:
        return {'status': 'not_applicable' if not environments else 'skipped',
                'reason': 'Requires exactly one matrix environment'}
    if stack or current or depth != 0:
        return {'status': 'unreliable', 'reason': 'Unclosed matrix structure'}
    return {'status': 'checked', 'candidate_rows': rows}


def matrix_constraint(chars, latex, target=None):
    candidate = matrix_rows(latex)
    if candidate['status'] != 'checked':
        return candidate, []
    if any(t.value in (r'\frac', r'\dfrac', r'\tfrac') for t in tokens(latex)):
        return {'status': 'skipped', 'reason': 'Fraction layout can create secondary row baselines'}, []
    if not geometry_reliable(chars):
        return {'status': 'unreliable', 'reason': 'Unmapped encoding or non-horizontal writing'}, []
    pieces = dict(zip('⎛⎝⎜⎞⎠⎟⎡⎣⎢⎤⎦⎥⎧⎩⎨⎫⎭⎬', '((()))[[[]]]{{{}}}'))
    brackets = [c for c in chars if extension_glyph(c) and
                pieces.get(symbol(c), symbol(c)) in '()[]{}|']
    groups = []
    for char in sorted(brackets, key=lambda c: c['origin_pt'][0]):
        if groups and abs(char['origin_pt'][0] - groups[-1][0]['origin_pt'][0]) < BASELINE_TOLERANCE * char['size_pt']:
            groups[-1].append(char)
        else:
            groups.append([char])
    pairs, opened = [], []
    for group in groups:
        shape = pieces.get(symbol(group[0]), symbol(group[0]))
        if shape in '([{':
            opened.append((shape, group))
        elif shape == '|' and not (opened and opened[-1][0] == '|'):
            opened.append((shape, group))
        elif opened and opened[-1][0] == dict(zip(')]}|', '([{|')).get(shape):
            pairs.append((opened.pop()[1], group))
    if not pairs:
        return {'status': 'unreliable', 'reason': 'No unique pair of extension delimiters'}, []
    def height(pair):
        return max(c['bbox_pt'][3] for group in pair for c in group) - min(c['bbox_pt'][1] for group in pair for c in group)
    tallest = max(height(pair) for pair in pairs)
    pairs = [pair for pair in pairs if tallest - height(pair) <= BASELINE_TOLERANCE * pair[0][0]['size_pt']]
    pairs.sort(key=lambda pair: pair[1][0]['origin_pt'][0] - pair[0][0]['origin_pt'][0], reverse=True)
    if len(pairs) > 1:
        widths = [pair[1][0]['origin_pt'][0] - pair[0][0]['origin_pt'][0] for pair in pairs[:2]]
        if abs(widths[0] - widths[1]) < BASELINE_TOLERANCE * pairs[0][0][0]['size_pt']:
            return {'status': 'unreliable', 'reason': 'Multiple equally plausible delimiter pairs'}, []
    left_group, right_group = pairs[0]
    left = max(c['bbox_pt'][2] for c in left_group)
    right = min(c['bbox_pt'][0] for c in right_group)
    chosen = left_group + right_group
    top = target[1] if target else min(c['bbox_pt'][1] for c in chosen)
    bottom = target[3] if target else max(c['bbox_pt'][3] for c in chosen)
    inside = [c for c in chars if not extension_glyph(c) and left <= c['origin_pt'][0] <= right
              and top <= c['origin_pt'][1] <= bottom]
    if not inside:
        return {'status': 'unreliable', 'reason': 'No glyphs enclosed by matrix delimiters'}, []
    roles = source_roles(inside)
    main = [c for c in inside if roles.get(tuple(c['source_index'])) == 'math']
    baselines = []
    for char in sorted(main, key=lambda c: c['origin_pt'][1]):
        if not baselines or abs(char['origin_pt'][1] - baselines[-1][0]['origin_pt'][1]) > BASELINE_TOLERANCE * char['size_pt']:
            baselines.append([char])
        else:
            baselines[-1].append(char)
    if not baselines:
        return {'status': 'unreliable', 'reason': 'No reliable primary matrix baselines'}, []
    source_rows = len(baselines)
    findings = [] if source_rows == candidate['candidate_rows'] else [{
        'type': 'matrix_constraint', 'source_rows': source_rows,
        'candidate_rows': candidate['candidate_rows'],
        'source_baselines_pt': [row[0]['origin_pt'][1] for row in baselines]}]
    return candidate | {'source_rows': source_rows, 'skipped_script_glyphs': len(inside) - len(main)}, findings
