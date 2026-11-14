"""Shared bounded Word layout operations. No document-specific identifiers."""
from copy import deepcopy
import re
from lxml import etree as E

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W = '{' + NS['w'] + '}'


def on_off(element, default=None):
    if element is None:
        return default
    raw = element.get(W+'val', 'true').lower()
    if raw in ('true', '1', 'on'):
        return True
    if raw in ('false', '0', 'off'):
        return False
    raise ValueError('Invalid Word on/off value: ' + raw)


def style_chain(sid, styles):
    chain, seen = [], set()
    while sid and sid in styles:
        if sid in seen:
            raise ValueError('Cyclic Word style inheritance')
        seen.add(sid)
        style = styles[sid]
        chain.insert(0, style)
        parent = style.find('w:basedOn', NS)
        sid = parent.get(W+'val') if parent is not None else None
    return chain


def paragraph_is_bold(p, styles):
    """Uniform emphasis only: style bold toggles, direct formatting overrides."""
    state = False
    if styles:
        root = next(iter(styles.values())).getroottree().getroot()
        state = on_off(root.find('w:docDefaults/w:rPrDefault/w:rPr/w:b', NS), False)
    sid = p.find('w:pPr/w:pStyle', NS)
    sid = sid.get(W+'val') if sid is not None else next((k for k, s in styles.items()
        if s.get(W+'type') == 'paragraph' and s.get(W+'default') in ('1', 'true')), None)
    for style in style_chain(sid, styles):
        if on_off(style.find('w:rPr/w:b', NS), False):
            state = not state
    states = []
    for run in p.findall('.//w:r', NS):
        if not ''.join(t.text or '' for t in run.findall('w:t', NS)).strip():
            continue
        current = state
        char = run.find('w:rPr/w:rStyle', NS)
        for style in style_chain(char.get(W+'val') if char is not None else None, styles):
            if on_off(style.find('w:rPr/w:b', NS), False):
                current = not current
        states.append(on_off(run.find('w:rPr/w:b', NS), current))
    return bool(states) and all(states)


def english_paragraph(source, text, styles=None):
    styles = styles or {}
    p = E.Element(W+'p')
    old = source.find('w:pPr', NS)
    pp = deepcopy(old) if old is not None else E.Element(W+'pPr')
    in_margin = any(a.tag in (W+'hdr', W+'ftr') for a in source.iterancestors())
    removed = ('numPr', 'outlineLvl', 'sectPr', 'pageBreakBefore', 'rPr')
    for tag in removed + (() if in_margin else ('pStyle',)):
        for el in pp.findall('w:'+tag, NS):
            pp.remove(el)
    np = E.Element(W+'numPr')
    E.SubElement(np, W+'numId', {W+'val':'0'})
    early = {W+t for t in ('pStyle','keepNext','keepLines','framePr','widowControl')}
    pp.insert(next((i for i,e in enumerate(pp) if e.tag not in early),len(pp)),np)
    outline = E.Element(W+'outlineLvl',{W+'val':'9'})
    late = {W+t for t in ('divId','cnfStyle','rPr','sectPr','pPrChange')}
    pp.insert(next((i for i,e in enumerate(pp) if e.tag in late),len(pp)),outline)
    if in_margin:
        # A removed Footer style otherwise falls back to the body's exact line
        # height/grid. Give the added 11pt line independent, compact metrics.
        spacing = pp.find('w:spacing', NS)
        if spacing is None:
            spacing = E.Element(W+'spacing')
            following = {W+t for t in ('ind','contextualSpacing','mirrorIndents',
                'suppressOverlap','jc','textDirection','textAlignment',
                'textboxTightWrap','outlineLvl','divId','cnfStyle','pPrChange')}
            pp.insert(next((i for i,e in enumerate(pp) if e.tag in following),len(pp)),spacing)
        spacing.attrib.clear()
        spacing.attrib.update({W+'before':'0', W+'after':'0', W+'line':'240', W+'lineRule':'auto'})
        grid = pp.find('w:snapToGrid', NS)
        if grid is None:
            grid = E.Element(W+'snapToGrid')
            pp.insert(list(pp).index(spacing), grid)
        grid.set(W+'val', '0')
    if any(a.tag == W+'tc' for a in source.iterancestors()):
        jc = pp.find('w:jc', NS)
        if jc is None:
            jc = E.Element(W+'jc')
            before = {W+t for t in ('textDirection','textAlignment','textboxTightWrap','outlineLvl','divId','cnfStyle')}
            pp.insert(next((i for i,e in enumerate(pp) if e.tag in before),len(pp)),jc)
        jc.set(W+'val','left')
    p.append(pp)
    run = E.SubElement(p,W+'r')
    rp = E.SubElement(run,W+'rPr')
    E.SubElement(rp,W+'rFonts',{W+'ascii':'Times New Roman',W+'hAnsi':'Times New Roman'})
    E.SubElement(rp,W+'b',{W+'val':'1' if paragraph_is_bold(source,styles) else '0'})
    E.SubElement(rp,W+'sz',{W+'val':'22'})
    E.SubElement(rp,W+'szCs',{W+'val':'22'})
    E.SubElement(rp,W+'lang',{W+'val':'en-US'})
    E.SubElement(run,W+'t',{'{http://www.w3.org/XML/1998/namespace}space':'preserve'}).text=text
    return p


def field_codes(p):
    codes = [x.get(W+'instr','') for x in p.findall('.//w:fldSimple',NS)]
    codes += [x.text or '' for x in p.findall('.//w:instrText',NS)]
    result = []
    for code in codes:
        # Deliberately bounded, not a general Word field interpreter.
        match = re.fullmatch(r'\s*(PAGE|NUMPAGES)\s*(?:\\\*\s+MERGEFORMAT\s*)?',code)
        if not match:
            raise ValueError('Unsupported field: use the full document workflow')
        result.append(match.group(1))
    return result


def page_field_paragraph(source, item, styles):
    codes = field_codes(source)
    template = item.get('field_template')
    if not isinstance(template,str):
        raise ValueError('Page fields need an explicit field_template with {PAGE}/{NUMPAGES}')
    tokens = re.split(r'(\{PAGE\}|\{NUMPAGES\})',template)
    if [t[1:-1] for t in tokens if t in ('{PAGE}','{NUMPAGES}')] != codes:
        raise ValueError('Field template must preserve field order and count')
    static = ''.join(t for t in tokens if t not in ('{PAGE}','{NUMPAGES}'))
    if static != item['translation']:
        raise ValueError('Field template static text must equal the supplied translation')
    target = english_paragraph(source,'',styles)
    prototype = target.find('w:r/w:rPr',NS)
    for run in target.findall('w:r',NS):
        target.remove(run)
    for token in tokens:
        if not token:
            continue
        if token in ('{PAGE}','{NUMPAGES}'):
            field = E.SubElement(target,W+'fldSimple',{W+'instr':token[1:-1]})
            run = E.SubElement(field,W+'r')
        else:
            run = E.SubElement(target,W+'r')
        run.append(deepcopy(prototype))
        E.SubElement(run,W+'t',{'{http://www.w3.org/XML/1998/namespace}space':'preserve'}).text = '' if token in ('{PAGE}','{NUMPAGES}') else token
    return target


def starts_new_page(start):
    """Reuse an explicit source page boundary instead of stacking hard breaks."""
    if on_off(start.find('w:pPr/w:pageBreakBefore', NS), False):
        return True
    previous = start.getprevious()
    if previous is None:
        return True
    if previous.tag != W+'p':
        return False
    content = [e for e in previous.iter() if e.tag in
        {W+t for t in ('t','br','cr','tab','drawing','pict','object','fldChar','fldSimple','sym')}]
    return bool(content) and all(e.tag == W+'br' and e.get(W+'type') == 'page' for e in content)


def apply_page_break_plan(root, source_nodes, plan):
    """Apply explicitly approved flow across a standalone source page break."""
    items = plan.get('page_breaks', [])
    if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
        raise ValueError('page_breaks must be a list of layout objects')
    body = root.find('w:body', NS)
    pending, seen = [], set()
    for item in items:
        anchor = item.get('before')
        if not isinstance(anchor, str) or anchor in seen:
            raise ValueError('Invalid or duplicate page-break anchor')
        seen.add(anchor)
        if item.get('policy') != 'allow_flow' or not str(item.get('reason', '')).strip():
            raise ValueError('Page-break flow needs policy=allow_flow and an explicit reason')
        start = source_nodes.get(anchor)
        if start is None or start.getparent() is not body:
            raise ValueError('Page-break anchor must be a top-level source paragraph')
        if on_off(start.find('w:pPr/w:pageBreakBefore', NS), False):
            raise ValueError('Page-break flow does not alter paragraph pageBreakBefore')
        previous = start.getprevious()
        if previous is None or previous.tag != W+'p':
            raise ValueError('Page-break flow needs an immediately preceding standalone page break')
        content = [e for e in previous.iter() if e is not previous and
            e.tag not in (W+'r', W+'pPr', W+'rPr') and
            not any(a.tag in (W+'pPr', W+'rPr') for a in e.iterancestors())]
        if (len(content) != 1 or content[0].tag != W+'br' or
                content[0].get(W+'type') != 'page' or
                previous.find('.//w:sectPr', NS) is not None or
                any(previous is node for node in source_nodes.values())):
            raise ValueError('Only a single standalone page break without content, bookmarks or section properties may flow')
        if any(x.get('policy') == 'new_page_block' and x.get('start_before') == anchor
               for x in plan.get('tables', [])):
            raise ValueError('Conflicting page-break and table layout policies')
        pending.append(previous)
    for paragraph in pending:
        body.remove(paragraph)


def apply_table_plan(root, source_nodes, plan):
    body = root.find('w:body',NS)
    tables = body.findall('w:tbl',NS)
    seen = set()
    items = plan.get('tables',[])
    if not isinstance(items,list) or not all(isinstance(x,dict) for x in items):
        raise ValueError('tables must be a list of layout objects')
    apply_page_break_plan(root, source_nodes, plan)
    for item in items:
        index = item['table_index']
        if not isinstance(index,int) or index < 0 or index >= len(tables) or index in seen:
            raise ValueError('Invalid or duplicate top-level table_index')
        seen.add(index)
        table = tables[index]
        rows = table.findall('w:tr',NS)
        policy = item['policy']
        if policy == 'new_page_block':
            if len(rows) > 4:
                raise ValueError('Long tables must use flow, not the short-block policy')
            if not str(item.get('reason','')).strip():
                raise ValueError('A critical short block needs a recorded reason')
            start = source_nodes.get(item.get('start_before'))
            if start is None or start.getparent() is not body:
                raise ValueError('Block start must be a source paragraph before its table')
            siblings = list(body)
            if not 0 < siblings.index(table)-siblings.index(start) <= 12:
                raise ValueError('Block start must precede the selected table nearby')
            if starts_new_page(start):
                continue
            br = E.Element(W+'p')
            ident = max((int(x.get(W+'id')) for x in root.findall('.//w:bookmarkStart',NS)
                         if (x.get(W+'id') or '').isdigit()),default=0)+1
            name = 'stcLayout_table_'+str(index)
            if root.findall('.//w:bookmarkStart[@w:name="'+name+'"]',NS):
                raise ValueError('Layout bookmark already exists')
            E.SubElement(br,W+'bookmarkStart',{W+'id':str(ident),W+'name':name})
            E.SubElement(E.SubElement(br,W+'r'),W+'br',{W+'type':'page'})
            E.SubElement(br,W+'bookmarkEnd',{W+'id':str(ident)})
            start.addprevious(br)
        elif policy == 'flow':
            header_rows = item.get('repeat_header_rows',0)
            if not isinstance(header_rows,int) or not 0 <= header_rows < len(rows):
                raise ValueError('Invalid repeat_header_rows')
            for number,row in enumerate(rows):
                props = row.find('w:trPr',NS)
                if props is None:
                    props = E.Element(W+'trPr');row.insert(0,props)
                for existing in props.findall('w:tblHeader',NS):
                    props.remove(existing)
                if number < header_rows:
                    E.SubElement(props,W+'tblHeader')
                if item.get('prevent_row_split',False) and props.find('w:cantSplit',NS) is None:
                    E.SubElement(props,W+'cantSplit')
        else:
            raise ValueError('Unknown table layout policy')
