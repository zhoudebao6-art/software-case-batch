"""Contract fixtures only; no real source/visual review or media decode claimed."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from common import digest, read_json, write_json
from evidence_index import create
from review_packet import EXECUTION_KINDS, draft, execution_checks, inspect, main
from proflow import finalize


class ReviewPacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.work = self.root / 'work'; self.work.mkdir()
        self.control = self.work / '.product-v2'; self.control.mkdir()
        self.out = self.root / 'output'; (self.out / '模拟系统').mkdir(parents=True)
        self.archive = self.out / '模拟系统/项目源码.zip'; self.archive.write_bytes(b'fixture ZIP bytes')
        self.source = self.work / 'app.py'; self.source.write_text('fixture source')
        self.png = self.work / 'chart.png'; self.png.write_bytes(b'fixture PNG bytes')
        self.checks = []
        for kind in EXECUTION_KINDS:
            log = self.work / (kind + '.log'); log.write_text('actual fixture result ' + kind)
            self.checks.append({'kind': kind, 'command': 'fixture ' + kind, 'exit_code': 0,
                                'log': log.name, 'sha256': digest(log)})
        write_json(self.control / 'run.json', {'workspace': str(self.work), 'run_id': 'fixture', 'output': str(self.out)})
        write_json(self.control / 'chart-manifest.json', {'figures': [{'figure_id': 1, 'png': self.png.name, 'sha256': digest(self.png)}]})
        write_json(self.control / 'source-package.json', {'sha256': digest(self.archive), 'files': {'app.py': digest(self.source)}})
        self.timeline = self.control / 'timeline.json'
        item = {'file': str(self.png), 'sha256': digest(self.png)}
        write_json(self.timeline, {'frames': [item], 'contact_sheets': [item], 'interaction_frames': [item]})
        write_json(self.control / 'controlled-video.json', {'timeline': str(self.timeline), 'sha256': digest(self.timeline)})
        self.execution = self.work / 'execution.json'
        self.proof = {'checks': self.checks, 'source_zip_sha256': digest(self.archive), 'video_timeline_sha256': digest(self.timeline)}
        write_json(self.execution, self.proof)
        self.target = self.control / 'review-inputs/first'

    def test_deterministic_discovery_and_read_only_preflight(self):
        before = {p: digest(p) for p in self.root.rglob('*') if p.is_file()}
        first = inspect(self.work, self.execution); second = inspect(self.work, self.execution)
        self.assertEqual(first, second); self.assertEqual(first['status'], 'inputs_ready')
        self.assertEqual(before, {p: digest(p) for p in self.root.rglob('*') if p.is_file()})
        self.assertIn('app.py', [row['path'] for row in first['evidence']])
        self.assertEqual(len(first['evidence']), len({row['path'] for row in first['evidence']}))

    def test_checks_dictionary_fails_before_any_expensive_finalization(self):
        self.proof['checks'] = {item['kind']: item for item in self.checks}; write_json(self.execution, self.proof)
        with patch('contracts.chart_snapshot', side_effect=AssertionError('Expensive work must not run')):
            with self.assertRaisesRegex(ValueError, 'checks must be a list'):
                finalize(self.work, self.out, self.execution)
        report = inspect(self.work, self.execution)
        self.assertEqual(report['errors'][0]['location'], 'checks')
        self.assertEqual(draft(self.work, self.execution, self.target)['status'], 'blocked')
        self.assertFalse(self.target.exists())

    def test_exact_check_types_and_no_duplicate_unknown_or_nonobject(self):
        for bad in (None, 'checks', {}, self.checks[:-1], self.checks + [self.checks[0]],
                    list(EXECUTION_KINDS), [dict(item, kind='wrong') for item in self.checks],
                    [dict(item, kind=[]) for item in self.checks]):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'Six distinct execution checks'):
                execution_checks(bad)
        self.assertIs(execution_checks(self.checks), self.checks)

    def test_missing_stale_failed_checks_all_reported_without_writing(self):
        (self.work / 'api.log').unlink(); (self.work / 'build.log').write_text('changed log')
        self.proof['checks'][0]['exit_code'] = 1; write_json(self.execution, self.proof)
        report = draft(self.work, self.execution, self.target)
        self.assertTrue({'missing', 'stale', 'failed'}.issubset({row['code'] for row in report['errors']}))
        self.assertFalse(self.target.exists())

    def test_empty_log_and_boolean_exit_cannot_qualify(self):
        (self.work / 'api.log').write_text('')
        self.proof['checks'][0]['exit_code'] = False; write_json(self.execution, self.proof)
        errors = inspect(self.work, self.execution)['errors']
        self.assertTrue(any('empty' in row['message'] for row in errors))
        self.assertTrue(any(row['code'] == 'failed' for row in errors))

    def test_current_archive_and_frame_changes_block_preflight(self):
        self.archive.write_bytes(b'changed final archive'); self.png.write_bytes(b'changed frame')
        errors = inspect(self.work, self.execution)['errors']
        self.assertTrue(any(row['location'] == 'source_zip_sha256' for row in errors))
        self.assertTrue(any('chart.png' in row['location'] for row in errors))

    def test_private_new_directory_only_and_no_review_authority(self):
        result = draft(self.work, self.execution, self.target)
        self.assertEqual(result['status'], 'draft_created')
        value = read_json(self.target / 'review-draft.json')
        self.assertEqual(value['checks'], self.checks)
        for key in ('decision', 'reviewer_agent_id', 'passed', 'review_evidence_sha256'):
            self.assertNotIn(key, value)
        for key in ('reviewed_evidence', 'chart_reviews', 'visual_notes', 'limitations'):
            self.assertEqual(value[key], [])
        before = digest(self.target / 'review-draft.json')
        with self.assertRaisesRegex(ValueError, 'never overwrite'):
            draft(self.work, self.execution, self.target)
        self.assertEqual(before, digest(self.target / 'review-draft.json'))
        with self.assertRaisesRegex(ValueError, 'private'):
            draft(self.work, self.execution, self.work / 'review.json')

    def test_explicit_manifest_adds_pages_without_scanning_unrelated_files(self):
        page = self.work / 'word-page-1.png'; page.write_bytes(b'fixture page')
        unrelated = self.work / 'secret.env'; unrelated.write_text('never include')
        manifest = self.work / 'required-evidence.json'; write_json(manifest, {'files': [page.name]})
        rows = inspect(self.work, self.execution, manifest=manifest)['evidence']
        self.assertIn(page.name, [row['path'] for row in rows])
        self.assertNotIn(unrelated.name, [row['path'] for row in rows])

    def test_existing_index_preserves_actual_ids_and_stale_is_rejected(self):
        manifest = self.work / 'manifest.json'; write_json(manifest, {'files': ['chart.png', 'app.py']})
        index = self.work / 'original-index.json'; original = create(self.work, manifest, index)
        draft(self.work, self.execution, self.target, index=index)
        self.assertEqual(read_json(self.target / 'index.json')['evidence'], original['evidence'])
        self.source.write_text('changed')
        report = inspect(self.work, self.execution, index=index)
        self.assertTrue(any(row['location'] == 'index' for row in report['errors']))

    def test_explicit_scope_cannot_be_silently_ignored(self):
        report = inspect(self.work, self.execution, index=self.execution, manifest=self.execution)
        self.assertTrue(any(row['location'] == 'scope' for row in report['errors']))

    def test_bad_json_and_unsafe_declared_paths_are_structured(self):
        self.execution.write_text('[')
        self.assertTrue(any(row['code'] == 'schema' for row in inspect(self.work, self.execution)['errors']))
        self.proof['checks'][0]['log'] = '../escape.log'; write_json(self.execution, self.proof)
        self.assertTrue(any('Unsafe' in row['message'] for row in inspect(self.work, self.execution)['errors']))

    def test_cli_no_output_defaults_and_blocked_exit(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(['draft', '--workspace', str(self.work), '--execution', str(self.execution)])
        self.assertEqual(code, 2); self.assertEqual(json.loads(output.getvalue())['status'], 'blocked')
        self.assertFalse(self.target.exists())


if __name__ == '__main__':
    unittest.main()
