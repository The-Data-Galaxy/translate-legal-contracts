#!/usr/bin/env python3
"""Inspect Word structure, append supplied English translations, audit alignment.

Requires Python 3.10+ and lxml. No translation service or network access is used.
The builder deliberately supports only simple, field-free DOCX packages.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile
from lxml import etree as E

_layout_spec = importlib.util.spec_from_file_location('contract_word_layout', Path(__file__).with_name('word_layout.py'))
layout = importlib.util.module_from_spec(_layout_spec)
_layout_spec.loader.exec_module(layout)

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W = '{' + NS['w'] + '}'
STORY = re.compile(r'word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$')
NUMBER = re.compile(r'(?<![A-Za-z])\d+(?:[,.]\d+)*(?:%|％)?')


def parse(data):
    return E.fromstring(data, E.XMLParser(resolve_entities=False, no_network=True))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def paths_alias(first, second):
    a, b = Path(first), Path(second)
    if a.resolve() == b.resolve():
        return True
    try:
        return a.samefile(b)
    except FileNotFoundError:
        return False


def validate_output_paths(inputs, outputs):
    """Reject collisions before writing; samefile also detects hard links."""
    checked = []
    for name, path in outputs:
        for other_name, other_path in [*inputs, *checked]:
            if paths_alias(path, other_path):
                raise ValueError(name + ' must not overwrite ' + other_name)
        checked.append((name, path))


def value(parent, path, default=None):
    if parent is None:
        return default
    el = parent.find(path, NS)
    return el.get(W + 'val', default) if el is not None else default


def ptext(p):
    result = []
    for el in p.iter():
        if any(a.tag == W + 'p' for a in el.iterancestors() if a is not p
               and p in list(a.iterancestors())):
            continue
        if any(a.tag in (W + 'del', W + 'moveFrom') for a in el.iterancestors()):
            continue
        if el.tag == W + 't':
            result.append(el.text or '')
        elif el.tag == W + 'tab':
            result.append('\t')
        elif el.tag in (W + 'br', W + 'cr'):
            result.append('\n')
    return ''.join(result)


def ppr_hash(p):
    pp = p.find('w:pPr', NS)
    return digest(E.tostring(pp, method='c14n') if pp is not None else b'')


def load_package(path):
    with ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def style_map(pkg):
    if 'word/styles.xml' not in pkg:
        return {}
    return {s.get(W + 'styleId'): s for s in parse(pkg['word/styles.xml']).findall('w:style', NS)}


def numbering(p, styles, nums):
    sid = value(p, 'w:pPr/w:pStyle')
    if sid is None:
        sid = next((key for key, st in styles.items()
                    if st.get(W + 'type') == 'paragraph' and st.get(W + 'default') == '1'), None)
    chain, seen = [], set()
    current = sid
    while current and current not in seen:
        seen.add(current)
        s = styles.get(current)
        if s is None:
            break
        chain.insert(0, s.find('w:pPr/w:numPr', NS))
        current = value(s, 'w:basedOn')
    chain.append(p.find('w:pPr/w:numPr', NS))
    fields = {}
    for np in chain:
        if np is not None:
            for key in ('numId', 'ilvl'):
                v = value(np, 'w:' + key)
                if v is not None:
                    fields[key] = v
    nid = fields.get('numId')
    if nid in (None, '0'):
        return None
    level = fields.get('ilvl', '0')
    result = {'num_id': nid, 'level': level, 'style_id': sid,
              'display_label': None, 'display_requires_render_verification': True}
    if nums is None:
        result['definition_missing'] = True
        return result
    num = nums.find("w:num[@w:numId='%s']" % nid, NS)
    aid = value(num, 'w:abstractNumId')
    abstract = nums.find("w:abstractNum[@w:abstractNumId='%s']" % aid, NS) if aid else None
    lvl = abstract.find("w:lvl[@w:ilvl='%s']" % level, NS) if abstract is not None else None
    over = num.find("w:lvlOverride[@w:ilvl='%s']" % level, NS) if num is not None else None
    override_lvl = over.find('w:lvl', NS) if over is not None else None
    if override_lvl is not None:
        lvl = override_lvl
    result.update(abstract_id=aid, num_format=value(lvl, 'w:numFmt'),
                  level_text=value(lvl, 'w:lvlText'), start=value(lvl, 'w:start'),
                  start_override=value(over, 'w:startOverride'),
                  restart=value(lvl, 'w:lvlRestart'),
                  style_link=value(abstract, 'w:numStyleLink'))
    if lvl is None:
        result['definition_missing'] = True
    return result


def inspect(path):
    pkg = load_package(path)
    styles = style_map(pkg)
    nums = parse(pkg['word/numbering.xml']) if 'word/numbering.xml' in pkg else None
    blocks, roots, features = [], {}, Counter()
    tags = {
        'fldChar': 'fields', 'fldSimple': 'fields', 'instrText': 'field_instructions',
        'ins': 'revisions', 'del': 'revisions', 'moveFrom': 'revisions',
        'moveTo': 'revisions', 'pPrChange': 'revisions', 'rPrChange': 'revisions',
        'tblPrChange': 'revisions', 'numPrChange': 'revisions',
        'commentRangeStart': 'comments', 'commentReference': 'comments',
        'txbxContent': 'textboxes', 'sdt': 'content_controls',
        'drawing': 'drawings', 'pict': 'drawings', 'object': 'objects',
        'altChunk': 'alternative_content', 'tbl': 'tables',
    }
    for part in sorted(n for n in pkg if STORY.fullmatch(n)):
        root = parse(pkg[part])
        roots[part] = root
        for tag, feature in tags.items():
            features[feature] += len(root.findall('.//w:' + tag, NS))
        if part == 'word/comments.xml':
            features['comments'] += len(root.findall('w:comment', NS))
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            if el.tag.startswith(W):
                local = E.QName(el).localname
                if local.endswith('Change') and local not in tags:
                    features['revisions'] += 1
                if local in ('cellIns', 'cellDel', 'cellMerge', 'customXmlDelRangeStart',
                             'customXmlInsRangeStart', 'moveFromRangeStart', 'moveToRangeStart'):
                    features['revisions'] += 1
                if local in ('sym', 'subDoc', 'control'):
                    features['special_content'] += 1
            elif el.tag.startswith('{http://schemas.openxmlformats.org/officeDocument/2006/math}'):
                features['equations'] += 1
        for i, p in enumerate(root.findall('.//w:p', NS)):
            text = ptext(p)
            if not text.strip():
                continue
            block = {'id': 'b%06d' % (len(blocks) + 1), 'part': part,
                     'paragraph_index': i, 'xpath': root.getroottree().getpath(p),
                     'source_text': text, 'ppr_sha256': ppr_hash(p),
                     'in_table': any(a.tag == W + 'tc' for a in p.iterancestors()),
                     'numbering': numbering(p, styles, nums)}
            blocks.append(block)
    if 'word/document.xml' not in roots:
        raise ValueError('Not a supported Word document: word/document.xml is missing')
    blockers = {k: v for k, v in features.items() if v and k not in ('tables',)}
    result = {'source_sha256': digest(Path(path).read_bytes()), 'blocks': blocks,
              'features': dict(features), 'simple_builder_blockers': blockers,
              'translation_template': {'source_sha256': digest(Path(path).read_bytes()), 'blocks': [
                  {'id': b['id'], 'source_text': b['source_text'], 'translation': '',
                   'display_number': None, 'action': 'translate'} for b in blocks]},
              'limits': ['Display numbering is not computed; verify against rendered source.',
                         'Inventory is structural, not a complete visual or semantic review.']}
    return pkg, roots, result


def bookmark(p, name, ident):
    start = E.Element(W + 'bookmarkStart', {W + 'id': str(ident), W + 'name': name})
    end = E.Element(W + 'bookmarkEnd', {W + 'id': str(ident)})
    p.insert(1 if p.find('w:pPr', NS) is not None else 0, start)
    p.append(end)


def english_p(source, text, styles=None):
    return layout.english_paragraph(source, text, styles)


def build(source, translations, output, manifest_path):
    return _build(source, translations, output, manifest_path)


def compose(source, translations, output, manifest_path, layout_plan):
    plan = json.loads(Path(layout_plan).read_text(encoding='utf-8'))
    if not isinstance(plan,dict):
        raise ValueError('layout-plan must be an object')
    return _build(source, translations, output, manifest_path, plan, layout_plan)


def _build(source, translations, output, manifest_path, plan=None, plan_path=None):
    inputs = [('Source', source), ('Translation map', translations)]
    if plan_path is not None:
        inputs.append(('Layout plan', plan_path))
    validate_output_paths(
        inputs,
        [('Word output', output), ('Manifest output', manifest_path)])
    pkg, roots, info = inspect(source)
    blockers = info['simple_builder_blockers']
    if plan is None and blockers:
        raise ValueError('Complex Word features require the full document workflow: ' +
                         json.dumps(blockers, ensure_ascii=False))
    if plan is not None:
        if plan.get('source_sha256') != info['source_sha256']:
            raise ValueError('Layout plan belongs to a different source file')
        if set(blockers) - {'fields','field_instructions'}:
            raise ValueError('compose supports only plain text, tables and header/footer PAGE/NUMPAGES fields')
        for part, root in roots.items():
            for p in root.findall('.//w:p',NS):
                if not any(p.findall('.//w:'+tag,NS) for tag in ('fldChar','fldSimple','instrText')):
                    continue
                if not re.fullmatch(r'word/(header|footer)\d*\.xml',part):
                    raise ValueError('compose rejects fields outside headers/footers')
                codes = layout.field_codes(p)
                simple = len(p.findall('.//w:fldSimple',NS))
                markers = p.findall('.//w:fldChar',NS)
                starts = sum(x.get(W+'fldCharType')=='begin' for x in markers)
                ends = sum(x.get(W+'fldCharType')=='end' for x in markers)
                if not codes or starts != ends or starts+simple != len(codes):
                    raise ValueError('Unsupported page field structure')
    translation_doc = json.loads(Path(translations).read_text(encoding='utf-8'))
    if translation_doc.get('source_sha256') != info['source_sha256']:
        raise ValueError('Translation map belongs to a different source file; inspect the exact source again')
    supplied = translation_doc['blocks']
    mapping = {x['id']: x for x in supplied}
    expected = {b['id'] for b in info['blocks']}
    if len(mapping) != len(supplied) or set(mapping) != expected:
        raise ValueError('Translation IDs must exactly cover the inventory, with no duplicates')
    pnodes = {part: root.findall('.//w:p', NS) for part, root in roots.items()}
    styles = style_map(pkg)
    source_nodes = {b['id']: pnodes[b['part']][b['paragraph_index']] for b in info['blocks']}
    ids = [int(e.get(W + 'id')) for root in roots.values()
           for e in root.findall('.//w:bookmarkStart', NS)
           if (e.get(W + 'id') or '').isdigit()]
    seq = max(ids, default=0) + 1
    existing_names = {e.get(W + 'name') for root in roots.values()
                      for e in root.findall('.//w:bookmarkStart', NS)}
    entries = []
    for b in info['blocks']:
        item = mapping[b['id']]
        if item.get('source_text') != b['source_text']:
            raise ValueError('Stale or changed source: ' + b['id'])
        action = item.get('action', 'translate')
        if action not in ('translate', 'retain'):
            raise ValueError('Unsupported action: ' + b['id'])
        if action == 'retain' and not str(item.get('reason', '')).strip():
            raise ValueError('A retained item needs a reason: ' + b['id'])
        if action == 'retain' and re.search(r'[\u3400-\u9fff]', b['source_text']):
            raise ValueError('Chinese text cannot be silently retained by the simple builder: ' + b['id'])
        translation = item.get('translation', '')
        if action == 'translate' and (not isinstance(translation, str) or not translation.strip()):
            raise ValueError('Missing translation: ' + b['id'])
        label = str(item.get('display_number') or '').strip()
        if action == 'translate' and b['numbering'] and not label:
            raise ValueError('Verify and supply the displayed list label: ' + b['id'])
        if label and not b['numbering']:
            raise ValueError('Do not add a new list label to an unnumbered paragraph: ' + b['id'])
        p = pnodes[b['part']][b['paragraph_index']]
        srcname, dstname = 'stcSrc_' + b['id'], 'stcDst_' + b['id']
        if srcname in existing_names or dstname in existing_names:
            raise ValueError('Translation bookmark already exists; use the original source')
        bookmark(p, srcname, seq)
        seq += 1
        full_target = (label + ' ' if label else '') + translation
        if action == 'translate':
            has_fields = any(p.findall('.//w:'+tag,NS) for tag in ('fldChar','fldSimple','instrText'))
            target = layout.page_field_paragraph(p,item,styles) if has_fields else english_p(p, full_target,styles)
            full_target = ptext(target)
            bookmark(target, dstname, seq)
            seq += 1
            p.addnext(target)
        entries.append({**b, 'action': action, 'reason': item.get('reason'),
                        'source_bookmark': srcname,
                        'target_bookmark': dstname if action == 'translate' else None,
                        'target_text': full_target if action == 'translate' else None,
                        'translation': translation if action == 'translate' else None,
                        'display_number': label, 'numeric_review': item.get('numeric_review')})
    if plan is not None:
        layout.apply_table_plan(roots['word/document.xml'],source_nodes,plan)
        if info['features'].get('fields'):
            if 'word/settings.xml' not in pkg:
                raise ValueError('Page-field compose needs the original settings part')
            settings = parse(pkg['word/settings.xml'])
            update = settings.find('w:updateFields',NS)
            if update is None:
                update = E.SubElement(settings,W+'updateFields')
            update.set(W+'val','true')
            pkg['word/settings.xml'] = E.tostring(settings,xml_declaration=True,encoding='UTF-8',standalone=True)
    for part, root in roots.items():
        pkg[part] = E.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w') as out, ZipFile(source) as original:
        for entry in original.infolist():
            out.writestr(entry, pkg[entry.filename])
    manifest = {'schema_version': 1, 'direction': 'to-english',
                'source_sha256': info['source_sha256'], 'blocks': entries,
                'numbering_sha256': digest(pkg.get('word/numbering.xml', b'')),
                'semantic_review': 'required', 'visual_review': 'required'}
    write_json(manifest_path, manifest)
    return {'output': str(Path(output).resolve()), 'translated': sum(
        e['action'] == 'translate' for e in entries), 'retained': sum(
        e['action'] == 'retain' for e in entries), 'semantic_review': 'required', 'visual_review': 'required'}


def audit(path, manifest_path):
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    pkg = load_package(path)
    styles = style_map(pkg)
    nums = parse(pkg['word/numbering.xml']) if 'word/numbering.xml' in pkg else None
    roots = {n: parse(data) for n, data in pkg.items() if STORY.fullmatch(n)}
    found = {}
    for part, root in roots.items():
        for p in root.findall('.//w:p', NS):
            for mark in p.findall('w:bookmarkStart', NS):
                name = mark.get(W + 'name', '')
                if name.startswith(('stcSrc_', 'stcDst_')):
                    found.setdefault(name, []).append((part, p))
    errors, warnings, retained = [], [], []
    if digest(pkg.get('word/numbering.xml', b'')) != manifest['numbering_sha256']:
        errors.append('Original numbering definitions changed')
    for b in manifest['blocks']:
        src = found.get(b['source_bookmark'], [])
        if len(src) != 1:
            errors.append(b['id'] + ': missing or duplicate source bookmark')
            continue
        part, sp = src[0]
        if part != b['part'] or ptext(sp) != b['source_text']:
            errors.append(b['id'] + ': source text or story changed')
        if ppr_hash(sp) != b['ppr_sha256']:
            errors.append(b['id'] + ': original paragraph/numbering properties changed')
        if numbering(sp, styles, nums) != b['numbering']:
            errors.append(b['id'] + ': original effective numbering changed (including style inheritance)')
        if b['action'] == 'retain':
            retained.append({'id': b['id'], 'text': b['source_text'], 'reason': b['reason']})
            continue
        dst = found.get(b['target_bookmark'], [])
        if len(dst) != 1:
            errors.append(b['id'] + ': missing or duplicate translation bookmark')
            continue
        dpart, tp = dst[0]
        if dpart != part or sp.getnext() is not tp:
            errors.append(b['id'] + ': translation is not adjacent to its source')
        if ptext(tp) != b['target_text']:
            errors.append(b['id'] + ': translation or displayed list label changed')
        if value(tp, 'w:pPr/w:numPr/w:numId') != '0':
            errors.append(b['id'] + ': translation can advance the original numbering')
        for run in tp.findall('.//w:r', NS):
            if run.find('w:t', NS) is not None and (
                value(run, 'w:rPr/w:sz') != '22' or value(run, 'w:rPr/w:szCs') != '22'):
                errors.append(b['id'] + ': English is not explicitly 11 pt')
        a, z = Counter(NUMBER.findall(b['source_text'])), Counter(NUMBER.findall(b['translation']))
        if a != z:
            warnings.append({'id': b['id'], 'issue': 'Numeric tokens differ; check units, dates and amounts',
                             'source': dict(a), 'translation': dict(z), 'review': b.get('numeric_review')})
    return {'structural_pass': not errors, 'errors': errors, 'warnings': warnings,
            'retained_items': retained, 'semantic_review': 'not_automated', 'visual_review': 'not_automated'}


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    i = sub.add_parser('inspect')
    i.add_argument('source')
    i.add_argument('--out', required=True)
    b = sub.add_parser('build')
    b.add_argument('source')
    b.add_argument('--translations', required=True)
    b.add_argument('--out', required=True)
    b.add_argument('--manifest', required=True)
    c = sub.add_parser('compose', help='Bounded page-field and table layout composition')
    c.add_argument('source')
    c.add_argument('--translations', required=True)
    c.add_argument('--layout-plan', required=True)
    c.add_argument('--out', required=True)
    c.add_argument('--manifest', required=True)
    a = sub.add_parser('audit')
    a.add_argument('source')
    a.add_argument('--manifest', required=True)
    a.add_argument('--out', required=True)
    args = ap.parse_args()
    try:
        if args.command == 'inspect':
            validate_output_paths([('Source', args.source)], [('Inventory output', args.out)])
            result = inspect(args.source)[2]
            write_json(args.out, result)
            print(json.dumps({'blocks': len(result['blocks']), 'features': result['features'],
                              'simple_builder_blockers': result['simple_builder_blockers']}, ensure_ascii=False))
        elif args.command == 'build':
            print(json.dumps(build(args.source, args.translations, args.out, args.manifest), ensure_ascii=False))
        elif args.command == 'compose':
            print(json.dumps(compose(args.source,args.translations,args.out,args.manifest,args.layout_plan),ensure_ascii=False))
        else:
            validate_output_paths(
                [('Source', args.source), ('Manifest', args.manifest)],
                [('Audit output', args.out)])
            result = audit(args.source, args.manifest)
            write_json(args.out, result)
            print(json.dumps(result, ensure_ascii=False))
            if not result['structural_pass']:
                return 1
    except (ValueError, KeyError, OSError, E.XMLSyntaxError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
