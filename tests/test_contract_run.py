"""One small group: fake renderer subprocesses, no model calls or real rendering."""
import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_contract_docx import package

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/contract_run.py'
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location('contract_run', SCRIPT)
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


class RunRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.docx'
        package(self.source)
        mapping = run.core.inspect(self.source)[2]['translation_template']
        mapping['blocks'][0]['translation'] = 'Party A shall pay CNY 100.'
        self.mapping = self.root / 'translations.json'
        self.mapping.write_text(json.dumps(mapping))
        self.plan = self.root / 'layout.json'
        self.plan.write_text(json.dumps({'source_sha256': run.sha(self.source), 'tables': []}))
        self.renderer = self.root / 'fake-renderer'
        self.renderer.write_text('#!' + sys.executable + '\n' + '''
import base64, pathlib, sys
out = pathlib.Path(sys.argv[sys.argv.index('--output_dir') + 1])
out.mkdir(parents=True)
png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN5sAAAAASUVORK5CYII=')
(out / 'page-1.png').write_bytes(png)
(out / 'page-2.png').write_bytes(png)
(out / 'bilingual.pdf').write_bytes(b'%PDF-fake-test-only')
''')
        self.renderer.chmod(0o755)
        self.source, self.folder = run.location(self.source)
        self.folder.mkdir()
        run.initialize(self.source, self.folder, 2, 5, 8, str(self.renderer))

    def execute(self):
        return run.execute(self.source, self.folder, self.mapping, self.plan)

    def change_plan(self):
        self.plan.write_text(json.dumps({'source_sha256': run.sha(self.source), 'tables': [], 'note': 'changed layout input'}))

    def test_01_real_compose_audit_then_cache_and_all_page_review(self):
        original = self.source.read_bytes()
        first = self.execute()
        self.assertEqual(first['status'], 'visual_pending')
        self.assertEqual(first['page_count'], 2)
        self.assertTrue(self.execute()['cached'])
        self.assertEqual(self.execute()['renders_used'], 1)
        partial = run.review(self.source, self.folder, '1', 'pass', 'Page 1 clear')
        self.assertEqual(partial['status'], 'visual_pending')
        done = run.review(self.source, self.folder, '2', 'pass', 'Page 2 clear')
        self.assertEqual(done['status'], 'complete')
        self.assertEqual(self.source.read_bytes(), original)

    def test_02_structural_failure_never_calls_renderer_or_charges(self):
        with patch.object(run.core, 'audit', return_value={'structural_pass': False, 'errors': ['bad']}), \
                patch.object(run.subprocess, 'run') as renderer:
            with self.assertRaisesRegex(run.StopRun, 'STRUCTURAL_FAILED'):
                self.execute()
            renderer.assert_not_called()
        self.assertEqual(len(run.load(self.source, self.folder)['renders']), 0)

    def test_03_failed_attempt_is_reserved_before_process_and_cannot_retry(self):
        def fail(*args, **kwargs):
            ledger = run.load(self.source, self.folder)
            self.assertEqual(ledger['renders'][0]['status'], 'rendering')
            return subprocess.CompletedProcess(args, 1)
        with patch.object(run.subprocess, 'run', side_effect=fail):
            with self.assertRaisesRegex(run.StopRun, 'RENDER_FAILED'):
                self.execute()
        self.assertEqual(len(run.load(self.source, self.folder)['renders']), 1)
        with self.assertRaisesRegex(run.StopRun, 'PREVIOUS_RENDER_FAILED'):
            self.execute()

    def test_04_budget_persists_across_processes_and_cannot_reinitialize(self):
        self.execute()
        run.review(self.source, self.folder, '1', 'fail', 'Synthetic layout failure')
        self.change_plan()
        self.execute()
        run.review(self.source, self.folder, '1', 'fail', 'Second synthetic failure')
        with self.assertRaisesRegex(run.StopRun, 'ALREADY_INITIALIZED'):
            run.initialize(self.source, self.folder, 100, 100, 100)
        self.plan.write_text(self.plan.read_text() + ' ')
        result = subprocess.run([sys.executable, str(SCRIPT), 'run', str(self.source),
                                 '--translations', str(self.mapping), '--layout-plan', str(self.plan)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 3)
        self.assertIn('BUDGET_EXHAUSTED', result.stdout)
        self.assertEqual(len(run.load(self.source, self.folder)['renders']), 2)

    def test_05_document_or_page_tampering_cannot_reuse_or_approve(self):
        result = self.execute()
        image = Path(result['pages_dir']) / 'page-1.png'
        image.write_bytes(image.read_bytes() + b'changed')
        with self.assertRaisesRegex(run.StopRun, 'ARTIFACT_CHANGED'):
            self.execute()
        with self.assertRaisesRegex(run.StopRun, 'REVIEW_VERSION_MISMATCH'):
            run.review(self.source, self.folder, '1-2', 'pass', 'Must be rejected')

    def test_06_translations_frozen_but_failed_layout_may_rebuild(self):
        self.execute()
        self.change_plan()
        with self.assertRaisesRegex(run.StopRun, 'REVIEW_REQUIRED'):
            self.execute()
        run.review(self.source, self.folder, '1', 'fail', 'Table split')
        self.assertEqual(self.execute()['renders_used'], 2)
        self.mapping.write_text(self.mapping.read_text() + ' ')
        with self.assertRaisesRegex(run.StopRun, 'TRANSLATIONS_FROZEN'):
            self.execute()

    def test_07_actual_page_overrun_stops_and_does_not_claim_visual_pass(self):
        data = run.load(self.source, self.folder)
        data['policy']['max_pages'] = 1  # Test setup only, before any run.
        run.save(self.folder / 'run.json', data)
        with self.assertRaisesRegex(run.StopRun, 'PAGE_LIMIT'):
            self.execute()
        data = run.load(self.source, self.folder)
        self.assertEqual(data['renders'][0]['status'], 'page_limit')
        self.assertEqual(data['renders'][0]['page_count'], 2)
        with self.assertRaises(run.StopRun):
            run.review(self.source, self.folder, '1-2', 'pass', 'Cannot approve')

    def test_08_interruption_and_view_budget_stop_without_more_work(self):
        self.execute()
        data = run.load(self.source, self.folder)
        data['policy']['max_views'] = 1
        run.save(self.folder / 'run.json', data)
        with self.assertRaisesRegex(run.StopRun, 'VIEW_BUDGET_EXHAUSTED'):
            run.review(self.source, self.folder, '1-2', 'pass', 'Rejected overrun')
        data['renders'][0]['status'] = 'rendering'
        run.save(self.folder / 'run.json', data)
        with self.assertRaisesRegex(run.StopRun, 'INTERRUPTED_RENDER'):
            self.execute()


if __name__ == '__main__':
    unittest.main()
