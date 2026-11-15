"""Target-language omissions through the real build/audit path; no rendering."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys
from test_contract_docx import mod as core, package, mutate

sys.path.insert(0, str(Path(core.__file__).parent))
spec = importlib.util.spec_from_file_location('name_review_run', core.__file__.replace('contract_docx.py', 'contract_run.py'))
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


class NameReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def build(self, source, translation, action='translate', in_table=False):
        src, mapping = self.root/'source.docx', self.root/'translations.json'
        out, manifest = self.root/'out.docx', self.root/'alignment.json'
        package(src)
        mutate(src, 'word/document.xml', lambda b: b.replace('甲方应支付100元。'.encode(), source.encode()))
        if in_table:
            def wrap_cell(data):
                document = core.parse(data)
                body = document.find('w:body', core.NS)
                paragraph = body.find('w:p', core.NS)
                table = core.E.Element(core.W+'tbl')
                core.E.SubElement(core.E.SubElement(table, core.W+'tr'), core.W+'tc').append(paragraph)
                body.insert(0, table)
                return core.E.tostring(document)
            mutate(src, 'word/document.xml', wrap_cell)
        original = src.read_bytes()
        doc = core.inspect(src)[2]['translation_template']
        doc['blocks'][0].update(translation=translation, action=action, reason='Numeric identifier unchanged')
        mapping.write_text(json.dumps(doc), encoding='utf-8')
        core.build(src, mapping, out, manifest)
        self.assertEqual(src.read_bytes(), original)
        return out, manifest, core.audit(out, manifest)

    def test_01_company_and_bank_copies_are_not_silent(self):
        for name in ('海岚示例咨询有限公司', '示例银行城南支行'):
            with self.subTest(name=name):
                _, _, report = self.build(name, name, in_table=True)
                self.assertTrue(report['structural_pass'])  # Format success is separate.
                self.assertTrue(report['target_language_review_required'])
                finding = report['target_language_findings'][0]
                self.assertTrue(finding['copies_entire_source'])
                self.assertEqual(finding['target'], name)
                self.assertEqual(finding['id'], 'b000001')
                self.assertEqual(finding['part'], 'word/document.xml')
                self.assertEqual(finding['source_paragraph_index'], 0)
                self.assertIn(finding, report['warnings'])

    def test_02_mixed_translation_and_quoted_names_are_located(self):
        for name in ('海岚示例咨询有限公司', '𠀀示例公司'):
            target = 'The account name is ' + name + '.'
            with self.subTest(name=name):
                _, _, report = self.build('开户名称：'+name, target)
                self.assertTrue(report['target_language_review_required'])
                finding = report['target_language_findings'][0]
                self.assertFalse(finding['copies_entire_source'])
                self.assertEqual(finding['chinese_fragments'], [name])

    def test_03_english_translation_and_numeric_retention_do_not_false_alarm(self):
        _, _, report = self.build('海岚示例咨询有限公司', 'Hailan Example Consulting Co., Ltd.')
        self.assertTrue(report['structural_pass'])
        self.assertFalse(report['target_language_review_required'])
        self.assertEqual(report['target_language_findings'], [])
        _, _, report = self.build('12345678', '', action='retain')
        self.assertTrue(report['structural_pass'])
        self.assertFalse(report['target_language_review_required'])
        self.assertEqual(len(report['retained_items']), 1)

    def test_04_actual_document_is_scanned_even_if_manifest_claims_english(self):
        name = '海岚示例咨询有限公司'
        english = 'Hailan Example Consulting Co., Ltd.'
        out, manifest, _ = self.build(name, english)
        mutate(out, 'word/document.xml', lambda b: b.replace(english.encode(), name.encode()))
        report = core.audit(out, manifest)
        self.assertFalse(report['structural_pass'])
        self.assertTrue(report['target_language_review_required'])
        self.assertEqual(report['target_language_findings'][0]['target'], name)

    def test_05_intentional_retention_still_needs_a_human_decision(self):
        target = 'Account name as registered: 海岚示例咨询有限公司'
        out, manifest, _ = self.build('开户名称：海岚示例咨询有限公司', target)
        data = json.loads(manifest.read_text())
        data['blocks'][0]['name_review'] = {'approved': True, 'reason': 'Retained registered account name'}
        data['target_language_review_required'] = False
        manifest.write_text(json.dumps(data))
        report = core.audit(out, manifest)
        self.assertTrue(report['structural_pass'])
        self.assertTrue(report['target_language_review_required'])
        self.assertTrue(report['target_language_findings'][0]['requires_manual_review'])
        # Merely relabelling Chinese as retain cannot bypass the existing guard.
        with self.assertRaisesRegex(ValueError, 'Chinese text cannot be silently retained'):
            self.build('海岚示例咨询有限公司', '', action='retain')

    def test_06_entry_summary_and_cache_keep_findings_and_legacy_is_unknown(self):
        _, _, report = self.build('示例银行城南支行', '示例银行城南支行')
        generation = self.root/'generation-01'
        generation.mkdir()
        audit_path = generation/'audit.json'
        audit_path.write_text(json.dumps(report))
        entry = {'directory': generation.name, 'status': 'complete', 'page_count': 1}
        data = {'renders': [entry], 'view_count': 1, 'policy': {}}
        for cached in (False, True):
            result = run.summary(self.root, data, entry, cached=cached)
            self.assertEqual(result['status'], 'complete')  # Visual record only.
            self.assertTrue(result['target_language_review_required'])
            self.assertEqual(result['target_language_findings'], report['target_language_findings'])
            self.assertIn('not automated', result['semantic_review'])
        audit_path.write_text(json.dumps({'structural_pass': True}))
        result = run.summary(self.root, data, entry, cached=True)
        self.assertIsNone(result['target_language_review_required'])


if __name__ == '__main__':
    unittest.main()
