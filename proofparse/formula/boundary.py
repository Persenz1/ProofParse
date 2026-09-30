"""Suggest edge-only prose trims; never recrop or rewrite a formula."""
import re

from .native import symbol, visible

REFERENCES = re.compile(r'(?<![A-Za-z])(?:Fig\.|Figure|Table|Eq\.)(?![A-Za-z])')
WORDS = re.compile(r'[A-Za-z]{2,}')


def boundary_suggestions(evidence):
    body_font = evidence.get('body_font')
    target = evidence.get('target_bbox_pt')
    page_size = evidence.get('page_size_pt')
    if not body_font or not target or not page_size:
        return {'status': 'unreliable', 'reason': 'Full-page prose font or coordinate evidence missing'}, []
    chars = [c for c in evidence['characters'] if c['in_target'] and visible(c)]
    segments = []
    for index, char in enumerate(chars):
        if char.get('font') == body_font:
            if segments and segments[-1][-1] == index - 1:
                segments[-1].append(index)
            else:
                segments.append([index])
    findings = []
    for indices in segments:
        text, owners = '', []
        previous = None
        for index in indices:
            char = chars[index]
            if previous and char['bbox_pt'][0] - previous['bbox_pt'][2] > char['size_pt'] * 0.25:
                text += ' '
                owners.append(index)
            token = symbol(char)
            text += token
            owners.extend([index] * len(token))
            previous = char
        match = REFERENCES.search(text) or WORDS.search(text)
        if not match:
            continue
        start = match.start()
        # Numeric math before a citation in the same prose font stays in math.
        if REFERENCES.search(text):
            while start > 0 and text[start - 1] in ' (':
                start -= 1
        else:
            start = 0
        prose_indices = [index for index in indices if index >= owners[start]]
        prose = text[start:].strip()
        trim = ('leading' if indices[0] == 0 and prose_indices[0] == 0 else
                'trailing' if indices[-1] == len(chars) - 1 else 'none')
        finding = {'type': 'boundary_suggestion', 'trim': trim, 'prose_text': prose,
                   'source_indices': [chars[i]['source_index'] for i in prose_indices],
                   'body_font': body_font}
        remaining = [c for i, c in enumerate(chars) if i not in prose_indices]
        if trim == 'none' or not remaining:
            finding.update(trim='none', reason='Interior text or no remaining mathematical glyphs')
        else:
            box = list(target)
            if trim == 'trailing':
                edge = min(chars[i]['bbox_pt'][0] for i in prose_indices)
                box[2] = (max(c['bbox_pt'][2] for c in remaining) + edge) / 2
            else:
                edge = max(chars[i]['bbox_pt'][2] for i in prose_indices)
                box[0] = (min(c['bbox_pt'][0] for c in remaining) + edge) / 2
            if box[0] < box[2] and box[1] < box[3]:
                width, height = page_size
                finding['suggested_target_bbox_pt'] = box
                finding['suggested_crop_bbox_1000'] = [box[0] / width * 1000, box[1] / height * 1000,
                                                       box[2] / width * 1000, box[3] / height * 1000]
            else:
                finding.update(trim='none', reason='Prose overlaps remaining math geometry')
        findings.append(finding)
    return {'status': 'checked', 'body_font': body_font}, findings
