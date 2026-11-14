#!/usr/bin/env python3
"""Compose, audit and render with a persistent per-source budget.

The ledger controls this entry point, not arbitrary commands run by a host.
Visual acknowledgements are reviewer declarations, not proof of image reading.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

import contract_docx as core


class StopRun(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def packed(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def save(path, value):
    temp = path.with_suffix('.pending')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, path)


def location(source):
    source = Path(source).resolve(strict=True)
    return source, source.parent / ('.contract-run-' + sha(source)[:12])


@contextmanager
def locked(source):
    source, folder = location(source)
    folder.mkdir(exist_ok=True)
    with (folder / 'run.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StopRun('RUN_BUSY: another invocation holds this source run')
        try:
            yield source, folder
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def default_renderer():
    # Never bypass this macOS entry point and its CJK font configuration.
    if sys.platform == 'darwin':
        return str(Path.home() / '.local/bin/codex-render-docx')
    return None


def initialize(source, folder, max_renders=1, max_pages=30, max_views=30, renderer=None):
    path = folder / 'run.json'
    if path.exists():
        raise StopRun('ALREADY_INITIALIZED: reuse the existing budget; do not reset or relocate the run')
    if min(max_renders, max_pages, max_views) < 1:
        raise StopRun('Budgets must be positive integers')
    data = {'schema_version': 1, 'source_sha256': sha(source),
            'policy': {'max_renders': max_renders, 'max_pages': max_pages,
                       'max_views': max_views, 'renderer': renderer or default_renderer()},
            'translations_sha256': None, 'renders': [], 'view_count': 0}
    save(path, data)
    return data


def load(source, folder):
    path = folder / 'run.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else initialize(source, folder)
    if data['source_sha256'] != sha(source):
        raise StopRun('SOURCE_CHANGED: do not reuse a budget or evidence for a different original')
    return data


def renderer_identity(policy):
    if not policy['renderer']:
        raise StopRun('RENDERER_MISSING: configure an existing renderer at init; do not install repeatedly')
    renderer = Path(policy['renderer']).expanduser().resolve(strict=True)
    if not os.access(renderer, os.X_OK):
        raise StopRun('RENDERER_NOT_EXECUTABLE')
    identity = {'path': str(renderer), 'sha256': sha(renderer), 'platform': sys.platform}
    # Include the adapter's dispatched renderer and Fontconfig, not just its wrapper.
    if renderer.name == 'codex-render-docx' and sys.platform == 'darwin':
        runtime = Path.home() / '.codex/plugins/cache/openai-primary-runtime/documents'
        targets = sorted(runtime.glob('*/skills/documents/render_docx.py'))
        config = Path.home() / '.config/codex-docs/fontconfig-macos-cjk.conf'
        if not targets or not config.is_file():
            raise StopRun('RENDERER_CONFIG_MISSING')
        identity.update(runtime_sha256=sha(targets[-1]), fontconfig_sha256=sha(config))
    return renderer, identity


def artifacts_valid(folder, entry):
    files = entry.get('files', {})
    return bool(files) and all((folder / name).is_file() and sha(folder / name) == digest
                               for name, digest in files.items())


def summary(folder, data, entry=None, cached=False):
    entry = entry or (data['renders'][-1] if data['renders'] else {})
    result = {'status': entry.get('status', 'initialized'), 'cached': cached,
              'ledger': str(folder / 'run.json'), 'renders_used': len(data['renders']),
              'pages_rendered': sum(x.get('page_count', 0) for x in data['renders']),
              'views_recorded': data['view_count'], 'policy': data['policy'],
              'semantic_review': 'required; not automated',
              'visual_review': 'reviewer declaration; host image-reading evidence required'}
    if entry.get('directory'):
        out = folder / entry['directory']
        result.update(output=str(out / 'bilingual.docx'), manifest=str(out / 'alignment.json'),
                      audit=str(out / 'audit.json'), pages_dir=str(out / 'pages'),
                      page_count=entry.get('page_count', 0), findings=entry.get('findings', []))
    return result


def execute(source, folder, translations, layout_plan=None, timeout=180):
    data = load(source, folder)
    mapping_hash = sha(translations)
    if data['translations_sha256'] and data['translations_sha256'] != mapping_hash:
        raise StopRun('TRANSLATIONS_FROZEN: layout retries must reuse the original translations')
    renderer, identity = renderer_identity(data['policy'])
    code = {p.name: sha(p) for p in Path(__file__).parent.glob('*.py')}
    key = packed({'source': data['source_sha256'], 'translations': mapping_hash,
                  'layout': sha(layout_plan) if layout_plan else None,
                  'renderer': identity, 'code': code})
    if any(x['status'] == 'rendering' for x in data['renders']):
        raise StopRun('INTERRUPTED_RENDER: attempt already charged; inspect its log, do not auto-retry')
    for entry in data['renders']:
        if entry['key'] == key and entry['status'] in ('visual_pending', 'visual_failed', 'complete'):
            if not artifacts_valid(folder, entry):
                raise StopRun('ARTIFACT_CHANGED: cached document or page images no longer match; do not reuse evidence')
            return summary(folder, data, entry, cached=True)
    used_pages = sum(x.get('page_count', 0) for x in data['renders'])
    if len(data['renders']) >= data['policy']['max_renders'] or used_pages >= data['policy']['max_pages']:
        raise StopRun('BUDGET_EXHAUSTED: stop; a new render requires explicit approval, not a reset')
    if any(x['status'] in ('render_failed', 'page_limit') for x in data['renders']):
        raise StopRun('PREVIOUS_RENDER_FAILED: stop and inspect logs; no automatic fallback or retry')
    if data['renders'] and data['renders'][-1]['status'] != 'visual_failed':
        raise StopRun('REVIEW_REQUIRED: inspect the current version and record a concrete failure before a layout retry')
    out = folder / ('generation-%02d' % (len(data['renders']) + 1))
    out.mkdir(exist_ok=False)
    doc, manifest, audit = (out / x for x in ('bilingual.docx', 'alignment.json', 'audit.json'))
    # Snapshot inputs so a later layout edit cannot relabel this generation.
    (out / 'translations.json').write_bytes(Path(translations).read_bytes())
    plan = None
    if layout_plan:
        plan = out / 'layout-plan.json'
        plan.write_bytes(Path(layout_plan).read_bytes())
    try:
        if plan:
            core.compose(source, out / 'translations.json', doc, manifest, plan)
        else:
            core.build(source, out / 'translations.json', doc, manifest)
        result = core.audit(doc, manifest)
        core.write_json(audit, result)
        if not result['structural_pass']:
            raise StopRun('STRUCTURAL_FAILED: renderer not called; see ' + str(audit))
        if sha(source) != data['source_sha256'] or sha(out / 'translations.json') != mapping_hash:
            raise StopRun('INPUT_CHANGED: renderer not called')
    except Exception:
        # Preserve failed build evidence while allowing corrected input on the next call.
        out.rename(out.with_name(out.name + '-build-failed-' + os.urandom(3).hex()))
        raise
    data['translations_sha256'] = mapping_hash
    generated_sha = sha(doc)
    entry = {'key': key, 'directory': out.name, 'status': 'rendering',
             'renderer': identity, 'page_count': 0, 'reviewed_pages': [], 'findings': []}
    data['renders'].append(entry)
    save(folder / 'run.json', data)  # Reserve BEFORE the external renderer starts.
    try:
        with (out / 'renderer.log').open('w') as log:
            result = subprocess.run([str(renderer), str(doc), '--output_dir', str(out / 'pages'), '--emit_pdf'],
                                    stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        images = sorted((out / 'pages').glob('page-*.png'),
                        key=lambda p: int(re.fullmatch(r'page-(\d+)\.png', p.name)[1]))
        entry['page_count'] = len(images)
        if result.returncode or not images:
            raise StopRun('RENDER_FAILED: inspect renderer.log; attempt charged, no fallback')
        if [int(re.fullmatch(r'page-(\d+)\.png', p.name)[1]) for p in images] != list(range(1, len(images) + 1)):
            raise StopRun('INCOMPLETE_PAGES')
        for image in images:
            header = image.read_bytes()[:24]
            if header[:8] != b'\x89PNG\r\n\x1a\n' or len(header) < 24 or min(struct.unpack('>II', header[16:24])) < 1:
                raise StopRun('INVALID_PAGE_IMAGE')
        pdf = out / 'pages/bilingual.pdf'
        if not pdf.is_file() or not pdf.stat().st_size:
            raise StopRun('PDF_MISSING')
        if sha(source) != data['source_sha256']:
            raise StopRun('SOURCE_CHANGED_DURING_RENDER')
        if sha(doc) != generated_sha:
            raise StopRun('OUTPUT_CHANGED_DURING_RENDER: regenerate, do not accept a renderer-side document patch')
        files = [doc, manifest, audit, pdf, *images]
        entry['files'] = {str(p.relative_to(folder)): sha(p) for p in files}
        entry['status'] = ('page_limit' if sum(x['page_count'] for x in data['renders']) >
                           data['policy']['max_pages'] else 'visual_pending')
    except Exception as exc:
        entry.update(status='render_failed', error=str(exc))
        save(folder / 'run.json', data)
        raise StopRun(str(exc)) from exc
    save(folder / 'run.json', data)
    if entry['status'] == 'page_limit':
        raise StopRun('PAGE_LIMIT: actual count known after export; stop, not a pre-export hard page cap')
    return summary(folder, data, entry)


def review(source, folder, pages, verdict, note):
    data = load(source, folder)
    if not data['renders']:
        raise StopRun('NO_RENDER')
    entry = data['renders'][-1]
    if entry['status'] not in ('visual_pending', 'visual_failed', 'complete') or not artifacts_valid(folder, entry):
        raise StopRun('REVIEW_VERSION_MISMATCH: do not approve stale or incomplete output')
    selected = set()
    for item in pages.split(','):
        bounds = item.split('-')
        if len(bounds) > 2:
            raise StopRun('INVALID_PAGE_RANGE')
        first, last = int(bounds[0]), int(bounds[-1])
        if not 1 <= first <= last <= entry['page_count']:
            raise StopRun('INVALID_PAGE_RANGE')
        selected.update(range(first, last + 1))
    if data['view_count'] + len(selected) > data['policy']['max_views']:
        raise StopRun('VIEW_BUDGET_EXHAUSTED')
    if not note.strip():
        raise StopRun('A concrete review note is required')
    data['view_count'] += len(selected)
    entry['reviewed_pages'] = sorted(set(entry['reviewed_pages']) | selected)
    entry['findings'].append({'pages': sorted(selected), 'verdict': verdict, 'note': note})
    # A failed version never becomes clean by relabelling a later partial review.
    if verdict == 'fail' or entry['status'] == 'visual_failed':
        entry['status'] = 'visual_failed'
    elif len(entry['reviewed_pages']) == entry['page_count']:
        entry['status'] = 'complete'
    save(folder / 'run.json', data)
    return summary(folder, data, entry)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init', help='Set an explicitly approved budget once, before the task')
    init.add_argument('source')
    init.add_argument('--max-renders', type=int, default=1)
    init.add_argument('--max-pages', type=int, default=30)
    init.add_argument('--max-views', type=int, default=30)
    init.add_argument('--renderer')
    run = sub.add_parser('run')
    run.add_argument('source')
    run.add_argument('--translations', required=True)
    run.add_argument('--layout-plan')
    check = sub.add_parser('review', help='Record pages actually viewed; not an automated visual verdict')
    check.add_argument('source')
    check.add_argument('--pages', required=True, help='e.g. 1-8,9,10-21')
    check.add_argument('--verdict', choices=('pass', 'fail'), required=True)
    check.add_argument('--note', required=True)
    status = sub.add_parser('status')
    status.add_argument('source')
    args = parser.parse_args()
    try:
        with locked(args.source) as (source, folder):
            if args.command == 'init':
                data = initialize(source, folder, args.max_renders, args.max_pages, args.max_views, args.renderer)
                result = summary(folder, data)
            elif args.command == 'run':
                result = execute(source, folder, args.translations, args.layout_plan)
            elif args.command == 'review':
                result = review(source, folder, args.pages, args.verdict, args.note)
            else:
                result = summary(folder, load(source, folder))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'stopped', 'reason': str(exc)}, ensure_ascii=False))
        return 3


if __name__ == '__main__':
    sys.exit(main())
