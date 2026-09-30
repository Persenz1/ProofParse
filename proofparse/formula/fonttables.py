"""Small, explicit TeX font tables; PDF glyph IDs are not character codes."""
import re
import unicodedata

# LaTeX Project encguide.pdf, pp. 33-34 (OML/OMS):
# https://tug.ctan.org/macros/latex/base/encguide.pdf
# AMSFonts user guide, font charts (MSBM/Euler):
# https://tug.ctan.org/fonts/amsfonts/doc/amsfndoc.pdf
# Cross-checked against TeX Live mmap/{oml,oms,umsb}.cmap.
OML = dict(enumerate('ΓΔΘΛΞΠΣΥΦΨΩαβγδεζηθικλμνξπρστυφχψω'))
OML.update({0x0F: 'ϵ', 0x1E: 'ϕ'})
OML.update(dict(zip(range(0x22, 0x28), 'εϑϖϱςφ')))
OML.update({0x3A: '.', 0x3B: ',', 0x40: '∂'})
OMS = {0x00: '−', 0x01: '⋅', 0x02: '×', 0x30: '′', 0x31: '∞'}
FAMILIES = {
    'CMSY': ('OMS', ['calligraphic']), 'CMBSY': ('OMS', ['calligraphic', 'bold']),
    'MSBM': ('UMSB', ['double_struck']), 'EUSM': ('EUS', ['script']),
    'EUSB': ('EUS', ['script', 'bold']), 'RSFS': ('RSFS', ['script']),
    'EUFM': ('EUF', ['fraktur']), 'EUFB': ('EUF', ['fraktur', 'bold']),
    'CMMIB': ('OML', ['bold', 'italic']), 'CMMI': ('OML', ['italic']),
    'CMBX': ('OT1', ['bold']),
}


def font_family(name):
    return re.sub(r'\d+$', '', re.sub(r'^[A-Z]{6}\+', '', name)).upper()


def font_table(char):
    family = font_family(char.get('font', ''))
    if family not in FAMILIES:
        return None
    encoding, styles = FAMILIES[family]
    # font_charcode is an explicitly supplied encoded slot. Unicode codepoints
    # and subset GIDs cannot safely stand in for that slot.
    code = char.get('font_charcode')
    text = unicodedata.normalize('NFKC', char.get('text', ''))
    if code is not None:
        if 65 <= code <= 90 or (encoding in ('OML', 'OT1', 'EUF') and 97 <= code <= 122):
            text = chr(code)
        elif encoding == 'OML':
            text = OML.get(code, chr(code) if 48 <= code <= 57 else '')
        elif encoding == 'OMS':
            text = OMS.get(code, '')
        else:
            text = ''
    elif char.get('suspicious_encoding'):
        return None
    if len(text) != 1:
        return None
    upper = 'A' <= text <= 'Z'
    if encoding in ('OMS', 'UMSB', 'EUS', 'RSFS') and not upper:
        if code is None or encoding != 'OMS' or code not in OMS:
            return None
        styles = []
    elif encoding == 'EUF' and not text.isascii():
        return None
    elif encoding in ('OML', 'OT1') and not (text.isalnum() or text in OML.values()):
        return None
    return {'mapped_text': text, 'mapped_styles': list(styles), 'mapping_source': 'font_table',
            'mapping_detail': {'family': family, 'encoding': encoding,
                               'input': 'encoded_slot' if code is not None else 'decoded_unicode'}}
