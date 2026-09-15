"""Conservatively reunite split figure panels using source caption geometry."""
import re

from ..pdf.render import render_crop

MAIN_CAPTION = re.compile(r"(?:Fig(?:ure)?\.?\s*\d+)\s*[.:]", re.I)


def _caption_text(block):
    return ' '.join(('$' + s.get('content', '') + '$') if s.get('type') == 'inline_equation'
                    else s.get('content', '') for line in block.get('lines', []) for s in line.get('spans', []))


def group_figures(doc, middle, pdf_path, output_dir):
    for page in middle.get('pdf_info', []):
        number = page['page_idx']
        width, height = page['page_size']
        figures = [b for b in doc.blocks if b.page == number and b.type == 'figure' and b.bbox]
        if not figures:
            continue
        def norm(bb):
            return [bb[0]/width*1000, bb[1]/height*1000, bb[2]/width*1000, bb[3]/height*1000]
        anchors = []
        panel_labels = []
        for raw in page.get('para_blocks', []):
            if raw.get('type') not in ('image', 'chart') or not raw.get('bbox'):
                continue
            bb = norm(raw['bbox'])
            owner = min(figures, key=lambda b: sum(abs(x-y) for x,y in zip(b.bbox,bb)))
            if max(abs(x-y) for x,y in zip(owner.bbox,bb)) > 3:
                continue
            for child in raw.get('blocks', []):
                if child.get('type') not in ('image_caption', 'chart_caption'):
                    continue
                text = _caption_text(child)
                if re.match(r'^\s*\([a-z]\)', text) and child.get('bbox'):
                    panel_labels.append(norm(child['bbox']))
                if MAIN_CAPTION.match(text.strip()) and child.get('bbox'):
                    caption = owner.extra.get('caption', '')
                    match = MAIN_CAPTION.search(caption)
                    anchors.append((owner, norm(child['bbox']), caption[match.start():] if match else text))
        groups = {owner.block_id: [] for owner, _, _ in anchors}
        for figure in figures:
            candidates = [(owner, caption, text) for owner, caption, text in anchors
                          if figure.bbox[3] <= caption[1]+5
                          and min(figure.bbox[2],caption[2]) > max(figure.bbox[0],caption[0])]
            if not candidates:
                continue
            owner, caption, _ = min(candidates, key=lambda a:a[1][1]-figure.bbox[3])
            groups[owner.block_id].append(figure)
        for owner, caption, text in anchors:
            members = groups[owner.block_id]
            if len(members) < 2 or owner not in members:
                continue
            bb = [min(b.bbox[0] for b in members), min(b.bbox[1] for b in members),
                  max(b.bbox[2] for b in members), max(b.bbox[3] for b in members)]
            body_top = bb[1]
            # Subfigure titles can sit outside the detected chart body.
            # Include their actual geometry instead of relying on fixed padding.
            for label in panel_labels:
                if (bb[1]-40/height*1000 <= label[1] < caption[1]
                        and label[3] <= bb[3]
                        and min(label[2],bb[2]) > max(label[0],bb[0])):
                    bb = [min(bb[0],label[0]), min(bb[1],label[1]),
                          max(bb[2],label[2]), max(bb[3],label[3])]
            # Labels can lie just above a panel. Never include the main caption itself.
            bb[1] = max(0, bb[1] - 12/height*1000)
            preceding = [b.bbox[3] for b in doc.blocks if b.page == number and b.bbox and b.content.strip()
                         and (b.type in ('dropped','heading','title') or (b.type == 'paragraph' and len(b.content)>100))
                         and bb[1] <= b.bbox[3] <= body_top
                         and min(b.bbox[2],bb[2]) > max(b.bbox[0],bb[0])]
            if preceding:
                bb[1] = min(body_top, max(preceding) + 3/height*1000)
            # Reject groups spanning prose between the panels and the main caption.
            prose = [b for b in doc.blocks if b.page == number and b.type == 'paragraph'
                     and b.content.strip() and b.bbox and len(b.content) > 100
                     and bb[0] <= (b.bbox[0]+b.bbox[2])/2 <= bb[2]
                     and bb[1] < (b.bbox[1]+b.bbox[3])/2 < caption[1]]
            if prose:
                continue
            relative = f'assets/{owner.block_id}_group.png'
            render_crop(pdf_path, number, bb, output_dir/relative, pad=6)
            owner.extra.update(asset=relative, caption=text, grouped_from=[b.block_id for b in members])
            owner.bbox = bb
            for b in members:
                if b is not owner:
                    b.extra['merged_into'] = owner.block_id
            # Short labels inside a complete figure need not become standalone equations/text.
            for b in doc.blocks:
                if b is owner or b.page != number or not b.bbox or b.type not in ('paragraph','equation'):
                    continue
                if (bb[0] <= b.bbox[0] and b.bbox[2] <= bb[2] and bb[1] <= b.bbox[1]
                        and b.bbox[3] <= bb[3] and len(b.content) < 200):
                    b.extra['merged_into'] = owner.block_id
