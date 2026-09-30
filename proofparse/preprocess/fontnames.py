"""Optional embedded-font glyph names for evidence, with explicit degradation."""
from io import BytesIO


def embedded_glyph_names(doc, xref):
    try:
        from fontTools.ttLib import TTFont
        from fontTools.cffLib import CFFFontSet
    except ImportError:
        return {'status': 'skipped', 'reason': 'fontTools is not installed'}, []
    name, extension, kind, data = doc.extract_font(xref)
    if not data:
        return {'status': 'skipped', 'reason': 'PDF font is not embedded'}, []
    try:
        if extension in ('ttf', 'otf'):
            with TTFont(BytesIO(data)) as font:
                names = font.getGlyphOrder()
        elif extension == 'cff':
            font = CFFFontSet()
            font.decompile(BytesIO(data), None)
            names = list(font[0].charset)
        else:
            return {'status': 'skipped', 'reason': f'Unsupported embedded format: {extension}'}, []
    except (ValueError, KeyError, IndexError, AssertionError) as error:
        return {'status': 'unreliable', 'reason': f'Cannot decode font: {error}'}, []
    return {'status': 'available'}, names


def attach_glyph_names(doc, characters):
    """Recover recognized names by GID, never by a guessed character-code slot."""
    cache = {}
    for char in characters:
        if not char.get('suspicious_encoding'):
            continue
        xref = char.get('font_xref')
        if xref is None:
            char['glyph_name_check'] = {'status': 'unreliable', 'reason': 'Ambiguous font resource'}
            continue
        if xref not in cache:
            cache[xref] = embedded_glyph_names(doc, xref)
        check, names = cache[xref]
        char['glyph_name_check'] = check
        gid = char['glyph_id']
        if names and 0 <= gid < len(names):
            from fontTools.agl import toUnicode
            name = names[gid]
            char['glyph_name'] = name
            text = toUnicode(name)
            if len(text) == 1:
                char['glyph_name_text'] = text
            else:
                char['glyph_name_check'] = {'status': 'unreliable', 'reason': 'No single Unicode glyph name'}
