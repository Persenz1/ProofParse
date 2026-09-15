"""将已确认的简单表格转为 Markdown，复杂表格保留有限 HTML。"""
from html.parser import HTMLParser
from html import escape
import re


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.html, self.cell = [], [], None
        self.complex = False
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.blocked += 1
            return
        if self.blocked or tag not in ("table", "thead", "tbody", "tfoot", "tr", "td", "th", "b", "strong", "i", "em", "sup", "sub", "u", "br"):
            return
        safe = []
        for k, v in attrs:
            if k in ("rowspan", "colspan") and (v or "").isdigit():
                safe.append(f' {k}="{v}"')
                self.complex |= int(v) > 1
        self.html.append(f"<{tag}{''.join(safe)}>")
        if tag == "tr": self.rows.append([])
        if tag in ("td", "th"): self.cell = []
        if tag in ("b", "strong", "i", "em", "sup", "sub", "u", "br"):
            self.complex = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.blocked = max(0, self.blocked - 1)
            return
        if self.blocked: return
        if tag in ("td", "th") and self.cell is not None:
            if self.rows: self.rows[-1].append(''.join(self.cell).strip())
            self.cell = None
        if tag in ("table", "thead", "tbody", "tfoot", "tr", "td", "th", "b", "strong", "i", "em", "sup", "sub", "u"):
            self.html.append(f"</{tag}>")

    def handle_data(self, data):
        if self.blocked: return
        self.html.append(escape(data))
        if self.cell is not None: self.cell.append(data)


def render_table(html: str) -> str:
    p = TableParser()
    p.feed(html)
    if (p.complex or not p.rows or not p.rows[0]
            or any(not re.search(r"[A-Za-z\u4e00-\u9fff]", c) for c in p.rows[0])
            or any(len(r) != len(p.rows[0]) for r in p.rows)):
        return ''.join(p.html)
    rows = ['| ' + ' | '.join(c.replace('|', '\\|').replace('\n', ' ') for c in r) + ' |' for r in p.rows]
    rows.insert(1, '| ' + ' | '.join(['---'] * len(p.rows[0])) + ' |')
    return '\n'.join(rows)
