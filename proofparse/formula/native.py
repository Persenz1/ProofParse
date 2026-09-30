"""Native glyph constraints for review, not a general PDF-to-LaTeX engine.

Only visually confirmed, PDF-bound glyph mappings override Unicode or style.
Symbol alignments and number associations are hints; they never resolve review.
"""
from __future__ import annotations

from collections import Counter
import re

from .syntax import split_equation, tokens

SYMBOLS = dict(zip(
    ('alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa '
     'lambda mu nu xi pi varpi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega '
     'Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega').split(),
    'αβγδεϵζηθϑικλμνξπϖρϱσςτυφϕχψωΓΔΘΛΞΠΣΥΦΨΩ'))
SYMBOLS.update({'cdot': '⋅', 'times': '×', 'leq': '≤', 'le': '≤', 'geq': '≥',
                'ge': '≥', 'neq': '≠', 'ne': '≠', 'infty': '∞', 'partial': '∂',
                'nabla': '∇', 'ell': 'ℓ', 'sum': '∑', 'prod': '∏', 'int': '∫'})
FONTS = {'mathcal': 'calligraphic', 'mathscr': 'script', 'mathbb': 'double_struck',
         'mathfrak': 'fraktur', 'mathbf': 'bold', 'boldsymbol': 'bold', 'pmb': 'bold',
         'bm': 'bold', 'mathrm': 'roman', 'mathit': 'italic', 'mathsf': 'sans',
         'mathtt': 'monospace'}
TEXT = {'text', 'textrm', 'textnormal', 'textbf', 'textit', 'mbox', 'hbox', 'operatorname'}
# These commands do not introduce alphabetic glyphs. Their arguments are still read.
STRUCTURE = {'frac', 'dfrac', 'tfrac', 'sqrt', 'left', 'right', 'big', 'Big', 'bigg',
             'Bigg', 'bigl', 'bigr', 'Bigl', 'Bigr', 'overline', 'bar', 'hat', 'widehat',
             'tilde', 'widetilde', 'vec', 'dot', 'ddot', 'underline', 'overset', 'underset',
             'stackrel', 'quad', 'qquad', 'displaystyle', 'textstyle', 'scriptstyle',
             'scriptscriptstyle', 'scriptsize', 'limits', 'nolimits'}


def candidate_atoms(latex: str) -> dict:
    """Expose supported glyphs with font scopes and body character offsets.

    Unsupported commands are explicit. This lexer does not claim to recover
    fraction/matrix topology or TeX macro expansion.
    """
    body, tags = split_equation(latex)
    ts = [t for t in tokens(body) if not t.value.isspace()]
    atoms, unsupported = [], []

    def parse(i, styles=(), role='math', one=False):
        while i < len(ts):
            t = ts[i]
            i += 1
            value = t.value
            if value == '}':
                return i
            if value == '{':
                i = parse(i, styles, role)
            elif value in ('_', '^'):
                i = parse(i, styles, 'subscript' if value == '_' else 'superscript', True)
            elif value.startswith('\\'):
                command = value[1:]
                if command in FONTS or command in TEXT:
                    style = FONTS.get(command)
                    i = parse(i, (*styles, style) if style else styles,
                              'text' if command in TEXT else role, True)
                elif command in ('begin', 'end'):
                    if i < len(ts) and ts[i].value == '{':
                        i += 1
                        while i < len(ts) and ts[i].value != '}': i += 1
                        i += i < len(ts)
                elif command in SYMBOLS:
                    atoms.append({'text': SYMBOLS[command], 'styles': list(styles),
                                  'role': role, 'body_offset': [t.start, t.end]})
                elif command not in STRUCTURE and command not in (',', ';', ':', '!', ' ', '\\'):
                    unsupported.append(value)
            elif value not in '&$':
                atoms.append({'text': value, 'styles': list(styles), 'role': role,
                              'body_offset': [t.start, t.end]})
            if one:
                return i
        return i

    parse(0)
    return {'atoms': atoms, 'numbers': [t.value.strip() for t in tags],
            'unsupported_commands': sorted(set(unsupported))}


def apply_glyph_map(characters: list[dict], mappings: list[dict]) -> list[dict]:
    lookup = {(m['font_xref'], m['glyph_id']): m for m in mappings}
    result = []
    for c in characters:
        c = dict(c)
        mapping = lookup.get((c.get('font_xref'), c['glyph_id']))
        if mapping:
            c['mapped_text'] = mapping['text']
            c['mapped_styles'] = mapping.get('styles', [])
            c['mapping_source'] = mapping['source']
        result.append(c)
    return result


def visible(c):
    return c['render_type'] != 3 and c['opacity'] > 0


def symbol(c):
    return c.get('mapped_text', c['text'])


def number_candidates(characters: list[dict], target: list[float],
                      other_targets: list[list[float]] = ()) -> dict:
    """Associate isolated numeric labels using row geometry and nearest formula.

    Only ordinary/mapped parentheses are recognized. Broken encodings stay
    unresolved. Prose references and labels inside formula bodies are excluded.
    """
    lines = []
    for c in sorted((c for c in characters if visible(c) and
                     (c['bbox_pt'][0] >= target[2] or c['bbox_pt'][2] <= target[0])),
                    key=lambda c: c['origin_pt'][1]):
        y = c['origin_pt'][1]
        line = next((line for line in lines if abs(line[0]['origin_pt'][1]-y) <=
                     min(line[0]['size_pt'], c['size_pt'])*0.25), None)
        if line is None:
            lines.append([c])
        else:
            line.append(c)
    found = []
    for line in lines:
        groups = [[]]
        for c in sorted(line, key=lambda c: c['bbox_pt'][0]):
            if groups[-1] and c['bbox_pt'][0]-groups[-1][-1]['bbox_pt'][2] > c['size_pt']*1.2:
                groups.append([])
            groups[-1].append(c)
        for group in groups:
            text = ''.join(symbol(c) for c in group).strip()
            match = re.fullmatch(r'\(\s*((?:[A-Z][.\-]?)?\d+(?:[.\-]\d+)*[a-z]?)\s*\)', text)
            if not match:
                continue
            bbox = [min(c['bbox_pt'][0] for c in group), min(c['bbox_pt'][1] for c in group),
                    max(c['bbox_pt'][2] for c in group), max(c['bbox_pt'][3] for c in group)]
            y = (bbox[1]+bbox[3])/2

            def distance(box):
                if not box[1] <= y <= box[3]: return float('inf')
                if bbox[0] >= box[2]: return bbox[0]-box[2]
                if bbox[2] <= box[0]: return box[0]-bbox[2]
                return float('inf')

            gap = distance(target)
            if gap == float('inf'):
                continue
            if any(distance(other) <= gap for other in other_targets if other != target):
                continue
            found.append({'value': match.group(1), 'bbox_pt': bbox,
                          'source_indices': [c['source_index'] for c in group]})
    return {'status': 'associated_by_layout' if len(found) == 1 else 'ambiguous' if found else 'unresolved',
            'candidates': found}


def analyze(evidence: dict, a: str, b: str, *, numbers: dict | None = None) -> dict:
    chars = [c for c in evidence['characters'] if c['in_target'] and visible(c)]
    counts = Counter(symbol(c) for c in chars)
    result = {'number_association': numbers or {'status': 'not_applicable', 'candidates': []},
              'candidates': {}, 'findings': []}
    for name, text in (('parser', a), ('formula_ocr', b)):
        parsed = candidate_atoms(text)
        atoms = parsed['atoms']
        candidate_counts = Counter(atom['text'] for atom in atoms)
        alignment = []
        for atom in atoms:
            indices = [c['source_index'] for c in chars if symbol(c) == atom['text']]
            alignment.append(atom | {'source_indices': indices,
                                     'status': 'unique_symbol' if len(indices) == 1 and candidate_counts[atom['text']] == 1
                                     else 'ambiguous' if indices else 'not_in_text_layer'})
        parsed['alignment'] = alignment
        del parsed['atoms']
        result['candidates'][name] = parsed
        if not text:
            continue
        # Compare style counts only when the symbol multiplicity agrees and the
        # lexer understood all commands. Repeated symbols never get a fake pairing.
        if not parsed['unsupported_commands']:
            for char, count in counts.items():
                if not char.isalpha() or candidate_counts[char] != count:
                    continue
                source = [c for c in chars if symbol(c) == char]
                for style in ('bold', 'calligraphic', 'script', 'double_struck', 'fraktur'):
                    required = sum(style in c.get('mapped_styles', []) or
                                   (style == 'bold' and bool(c['font_flags'] & 16)) for c in source)
                    supplied = sum(style in atom['styles'] for atom in atoms if atom['text'] == char)
                    if required > supplied:
                        result['findings'].append({'candidate': name, 'type': 'font_constraint',
                            'symbol': char, 'style': style, 'source_count': required,
                            'candidate_count': supplied,
                            'source_indices': [c['source_index'] for c in source]})
        association = result['number_association']
        if association['status'] == 'associated_by_layout':
            expected = association['candidates'][0]['value']
            if parsed['numbers'] != [expected]:
                result['findings'].append({'candidate': name, 'type': 'number_constraint',
                    'source_number': expected, 'candidate_numbers': parsed['numbers'],
                    'association': 'layout_hint'})
    # An ordinary prose citation caught in a math bbox is useful boundary evidence.
    raw = ''.join(symbol(c) for c in chars)
    if re.search(r'(?:Fig(?:ure)?\.|Table)\s*\d', raw):
        result['findings'].append({'type': 'math_prose_boundary', 'source_text': raw})
    return result
