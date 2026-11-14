"""Focused regression checks. Synthetic OOXML only; no render or model calls."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/contract_docx.py'
spec = importlib.util.spec_from_file_location('reviewed_contract_docx', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
W = mod.NS['w']


def package(path, *, numbered=False, field=False):
    props = '<w:pPr><w:pStyle w:val="Clause"/></w:pPr>' if numbered else ''
    extra = '<w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple>' if field else ''
    document = f'<w:document xmlns:w="{W}"><w:body><w:p>{props}<w:r><w:t>甲方应支付100元。</w:t></w:r>{extra}</w:p><w:sectPr/></w:body></w:document>'
    styles = f'<w:styles xmlns:w="{W}"><w:style w:type="paragraph" w:styleId="Clause"><w:name w:val="Clause"/><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr></w:style></w:styles>'
    nums = f'<w:numbering xmlns:w="{W}"><w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num></w:numbering>'
    cts = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/></Types>'
    rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    docrels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/></Relationships>'
    with ZipFile(path, 'w') as z:
        for name, text in {'[Content_Types].xml': cts, '_rels/.rels': rels,
                           'word/document.xml': document, 'word/styles.xml': styles,
                           'word/numbering.xml': nums, 'word/_rels/document.xml.rels': docrels}.items():
            z.writestr(name, text)


def mutate(path, part, transform):
    with ZipFile(path) as z:
        data = {n: z.read(n) for n in z.namelist()}
    data[part] = transform(data[part])
    with ZipFile(path, 'w') as z:
        for name, blob in data.items():
            z.writestr(name, blob)


class Probes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='contract-review-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src, self.mapping = self.root/'source.docx', self.root/'translations.json'
        self.out, self.manifest = self.root/'bilingual.docx', self.root/'alignment.json'

    def prepare(self, **kwargs):
        package(self.src, **kwargs)
        doc = mod.inspect(self.src)[2]['translation_template']
        doc['blocks'][0]['translation'] = 'Party A shall pay CNY 100.'
        if kwargs.get('numbered'):
            doc['blocks'][0]['display_number'] = '1.'
        self.mapping.write_text(json.dumps(doc), encoding='utf-8')
        return doc

    def build(self):
        return mod.build(self.src, self.mapping, self.out, self.manifest)

    def test_01_simple_build_and_audit(self):
        self.prepare()
        before = self.src.read_bytes()
        self.assertEqual(self.build()['translated'], 1)
        self.assertEqual(self.src.read_bytes(), before)
        self.assertTrue(mod.audit(self.out, self.manifest)['structural_pass'])

    def test_02_stale_source_rejected(self):
        doc = self.prepare()
        doc['source_sha256'] = '0'*64
        self.mapping.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'different source'):
            self.build()

    def test_03_missing_block_rejected(self):
        doc = self.prepare()
        doc['blocks'] = []
        self.mapping.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'exactly cover'):
            self.build()

    def test_04_number_label_required(self):
        doc = self.prepare(numbered=True)
        self.assertEqual(mod.inspect(self.src)[2]['blocks'][0]['numbering']['num_id'], '1')
        doc['blocks'][0]['display_number'] = None
        self.mapping.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'displayed list label'):
            self.build()

    def test_05_complex_field_rejected(self):
        self.prepare(field=True)
        with self.assertRaisesRegex(ValueError, 'Complex Word features'):
            self.build()

    def test_06_font_tamper_detected(self):
        self.prepare()
        self.build()
        mutate(self.out, 'word/document.xml', lambda b: b.replace(b'w:val="22"', b'w:val="20"'))
        result = mod.audit(self.out, self.manifest)
        self.assertFalse(result['structural_pass'])
        self.assertTrue(any('11 pt' in e for e in result['errors']))

    def test_07_inherited_numbering_tamper_must_be_detected(self):
        self.prepare(numbered=True)
        self.build()
        self.assertTrue(mod.audit(self.out, self.manifest)['structural_pass'])
        mutate(self.out, 'word/styles.xml', lambda b: b.replace(b'<w:numId w:val="1"/>', b'<w:numId w:val="0"/>'))
        # The source now inherits numId=0: its automatic numbering is cancelled.
        self.assertIsNone(mod.inspect(self.out)[2]['blocks'][0]['numbering'])
        result = mod.audit(self.out, self.manifest)
        self.assertFalse(result['structural_pass'], f'False pass after inherited source numbering was cancelled: {result}')

    def test_08_all_commands_must_protect_source_from_json_output_collision(self):
        # Each subcase uses its own disposable source. No user documents touched.
        for command in ('inspect', 'build', 'audit'):
            with self.subTest(command=command):
                self.prepare()
                if command == 'audit':
                    self.build()
                    src = self.out
                    args = ['audit', str(src), '--manifest', str(self.manifest), '--out', str(src)]
                elif command == 'build':
                    src = self.src
                    args = ['build', str(src), '--translations', str(self.mapping), '--out', str(self.out), '--manifest', str(src)]
                else:
                    src = self.src
                    args = ['inspect', str(src), '--out', str(src)]
                before = src.read_bytes()
                proc = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
                unchanged = src.read_bytes() == before
                self.assertTrue(unchanged, f'{command}: exit={proc.returncode}; source overwritten as JSON={src.read_bytes().startswith(b"{")}')
                self.assertNotEqual(proc.returncode, 0)


    def test_09_aliases_and_output_roles_preserve_inputs(self):
        for kind in ('symlink', 'hardlink', 'word_over_map', 'manifest_over_map',
                     'outputs_same', 'audit_over_manifest', 'direct_build_alias'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=self.root) as dirname:
                root = Path(dirname)
                src, mapping = root/'src.docx', root/'map.json'
                out, manifest = root/'out.docx', root/'manifest.json'
                package(src)
                doc = mod.inspect(src)[2]['translation_template']
                doc['blocks'][0]['translation'] = 'Party A shall pay CNY 100.'
                mapping.write_text(json.dumps(doc), encoding='utf-8')
                protected = [src, mapping]
                absent = [out, manifest]
                if kind in ('symlink', 'hardlink', 'direct_build_alias'):
                    alias = root/'alias.docx'
                    if kind == 'symlink':
                        alias.symlink_to(src)
                    else:
                        alias.hardlink_to(src)
                    protected.append(alias)
                    args = ['inspect', str(src), '--out', str(alias)]
                elif kind == 'audit_over_manifest':
                    mod.build(src, mapping, out, manifest)
                    protected += [out, manifest]
                    absent = []
                    args = ['audit', str(out), '--manifest', str(manifest), '--out', str(manifest)]
                else:
                    dst = mapping if kind == 'word_over_map' else out
                    man = mapping if kind == 'manifest_over_map' else out if kind == 'outputs_same' else manifest
                    args = ['build', str(src), '--translations', str(mapping), '--out', str(dst), '--manifest', str(man)]
                before = {p: p.read_bytes() for p in protected}
                if kind == 'direct_build_alias':
                    with self.assertRaises(ValueError):
                        mod.build(src, mapping, alias, manifest)
                else:
                    proc = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
                    self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                for p, blob in before.items():
                    self.assertEqual(p.read_bytes(), blob, f'{kind} changed {p.name}')
                for p in absent:
                    self.assertFalse(p.exists(), f'{kind} created {p.name} before rejection')


    def test_10_style_chain_change_detected_but_unrelated_format_allowed(self):
        self.prepare(numbered=True)
        # Clause inherits numbering through BaseClause, rather than a direct numPr.
        def inherit(blob):
            root = mod.parse(blob)
            clause = root.find("w:style[@w:styleId='Clause']", mod.NS)
            base = mod.E.SubElement(root, mod.W + 'style', {mod.W + 'type': 'paragraph', mod.W + 'styleId': 'BaseClause'})
            base.append(clause.find('w:pPr', mod.NS))
            mod.E.SubElement(clause, mod.W + 'basedOn', {mod.W + 'val': 'BaseClause'})
            return mod.E.tostring(root)
        mutate(self.src, 'word/styles.xml', inherit)
        doc = mod.inspect(self.src)[2]['translation_template']
        doc['blocks'][0].update(translation='Party A shall pay CNY 100.', display_number='1.')
        self.mapping.write_text(json.dumps(doc), encoding='utf-8')
        self.build()
        self.assertTrue(mod.audit(self.out, self.manifest)['structural_pass'])
        mutate(self.out, 'word/styles.xml', lambda b: b.replace(b'</w:styles>', b'<w:style w:type="character" w:styleId="Unused"><w:rPr><w:sz w:val="20"/></w:rPr></w:style></w:styles>'))
        self.assertTrue(mod.audit(self.out, self.manifest)['structural_pass'])
        mutate(self.out, 'word/styles.xml', lambda b: b.replace(b'<w:ilvl w:val="0"/>', b'<w:ilvl w:val="1"/>'))
        self.assertFalse(mod.audit(self.out, self.manifest)['structural_pass'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
