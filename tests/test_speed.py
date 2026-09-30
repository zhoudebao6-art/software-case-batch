"""Keep review integrity while removing digest transcription and recording contention."""
import copy
import unittest
import threading
from unittest.mock import patch
from contextlib import contextmanager
import test_caseflow as fixtures
from test_caseflow import flow, FakeExecutor


def compact_response(report, request):
    reverse = {path: key for key, path in request['evidence'].items()}
    response = {k: report[k] for k in ('verdict', 'issues', 'coverage', 'limitations')}
    response.update(protocol='evidence-ids-v1', review_id=request['review_id'],
        reviewed_evidence=[reverse[row['path']] for row in report['reviewed_files']],
        chart_reviews=[{'figure_id': row['figure_id'], 'checks': row['checks'],
            'evidence_ids': [reverse[p] for p in row['evidence_files']]} for row in report['chart_reviews']])
    return response


class SpeedTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown
    make_source = fixtures.CaseflowTests.make_source
    run_fake = fixtures.CaseflowTests.run_fake

    def test_plain_repair_does_not_acquire_recording_slot(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        self.cfg['runner'].update(review_mode='combined_final')
        active = []
        real_slot = flow.stage_slot
        @contextmanager
        def slot(cfg, kind, **kwargs):
            with real_slot(cfg, kind, **kwargs):
                active.append(kind)
                try:
                    yield
                finally:
                    active.remove(kind)
        fake = FakeExecutor(revise_visual=True)
        observed = []
        def execute(cfg, case, stage, context, output=None):
            if stage == 'repair_final':
                observed.append(list(active))
            return fake(cfg, case, stage, context, output)
        with patch.object(flow, 'stage_slot', slot):
            result = self.run_fake(execute)
        self.assertEqual(result['cases'][0]['stage'], 'delivered')
        self.assertTrue(observed)
        self.assertTrue(all('recording' not in slots for slots in observed))

    def test_record_again_after_changed_ui_but_not_for_unchanged_word(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        self.cfg['runner'].update(review_mode='combined_final')
        fake = FakeExecutor(revise_visual=True)
        result = self.run_fake(fake)
        self.assertEqual(result['cases'][0]['stage'], 'delivered')
        stages = [s for _, s in fake.stages]
        self.assertEqual(stages.count('video'), 2)

    def test_word_only_repair_keeps_existing_recording(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        self.cfg['runner'].update(review_mode='combined_final')
        fake = FakeExecutor(revise_visual=True)
        def execute(cfg, case, stage, context, output=None):
            before = (case / 'evidence/ui/overview.png').read_bytes() if stage == 'repair_final' else None
            rec = fake(cfg, case, stage, context, output)
            if stage == 'repair_final':
                (case / 'evidence/ui/overview.png').write_bytes(before)
                (case / 'evidence/word-edit-notes.md').write_text('Revised paragraph connection.', encoding='utf-8')
            return rec
        result = self.run_fake(execute)
        self.assertEqual(result['cases'][0]['stage'], 'delivered')
        self.assertEqual([s for _, s in fake.stages].count('video'), 1)

    def test_compact_binding_rejects_wrong_scope_unknown_and_missing_ids(self):
        files = {'one.txt': 'a' * 64, 'two.txt': 'b' * 64}
        request = flow.review_request(files, set(files))
        raw = {'protocol': 'evidence-ids-v1', 'review_id': request['review_id'], 'verdict': 'pass', 'issues': [],
               'chart_reviews': [], 'reviewed_evidence': ['E001', 'E002'], 'coverage': 'Read two text files.', 'limitations': []}
        for key, value in [('review_id', 'old-request'), ('reviewed_evidence', ['E001']), ('reviewed_evidence', ['E001', 'E999']), ('reviewed_evidence', ['E001', 'E001', 'E002'])]:
            modified = {**raw, key: value}
            with self.subTest(key=key, value=value), self.assertRaises(flow.Blocked):
                flow.bind_review_response(modified, request, files, set(files), {'charts': []})

    def test_compact_response_binds_only_current_declared_evidence(self):
        self.make_source()
        m = flow.plan(self.cfg, self.source)
        self.cfg['runner'].update(review_mode='combined_final')
        fake = FakeExecutor()
        seen = []
        def execute(cfg, case, stage, context, output=None):
            rec = fake(cfg, case, stage, context, output)
            if stage == 'review_final':
                request = context.get('review_request')
                self.assertIsInstance(request, dict, 'Review needs parent-owned evidence IDs')
                report = flow.read_json(output)
                response = compact_response(report, request)
                flow.atomic_json(output, response)
                seen.append((output, copy.deepcopy(response)))
            return rec
        state = self.run_fake(execute)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual(len(seen), 1)
        self.assertEqual(flow.read_json(seen[0][0]), seen[0][1], 'Preserve raw reviewer output')
        bound = flow.read_json(__import__('pathlib').Path(state['final_review']['path']))
        self.assertEqual(bound['verdict'], 'pass')
        self.assertTrue(all(len(r['sha256']) == 64 for r in bound['reviewed_files']))
        self.assertNotEqual(str(seen[0][0]), state['final_review']['path'])

    def test_incomplete_revise_reaches_repair_without_inventing_reviewed_ids(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        self.cfg['runner'].update(review_mode='combined_final')
        fake = FakeExecutor(revise_visual=True)
        saved = []
        advice = []
        def execute(cfg, case, stage, context, output=None):
            if stage == 'repair_final':
                advice.append(context['review'])
            rec = fake(cfg, case, stage, context, output)
            if stage == 'review_final':
                raw = compact_response(flow.read_json(output), context['review_request'])
                if raw['verdict'] == 'revise':
                    omitted = next(k for k, p in context['review_request']['evidence'].items() if p.endswith('frame-001.png'))
                    raw['reviewed_evidence'].remove(omitted)
                    saved.append((output, copy.deepcopy(raw)))
                flow.atomic_json(output, raw)
            return rec
        state = self.run_fake(execute)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual(state['review_calls_started'], 2)
        self.assertEqual(len(advice), 1)
        self.assertFalse(any(row['path'].endswith('frame-001.png') for row in advice[0]['reviewed_files']))
        self.assertEqual(flow.read_json(saved[0][0]), saved[0][1])

    def test_incomplete_revise_retains_scope_and_chart_integrity_checks(self):
        files = {'one.txt': 'a' * 64, 'two.txt': 'b' * 64}
        request = flow.review_request(files, set(files))
        raw = {'protocol': 'evidence-ids-v1', 'review_id': request['review_id'], 'verdict': 'revise',
               'issues': [{'severity': 'minor', 'artifact': 'one.txt', 'evidence': 'Wrong value', 'fix': 'Correct value'}],
               'chart_reviews': [], 'reviewed_evidence': ['E001'], 'coverage': 'Read one file.', 'limitations': ['Second file unread']}
        bound = flow.bind_review_response(raw, request, files, set(files), {'charts': []})
        self.assertEqual([r['path'] for r in bound['reviewed_files']], ['one.txt'])
        with self.assertRaisesRegex(flow.Blocked, 'omits required'):
            flow.verify_review(bound, files, set(files), manifest={'charts': []})
        for key, value in [('review_id', 'old'), ('reviewed_evidence', ['E999']), ('reviewed_evidence', ['E001', 'E001']), ('issues', [])]:
            with self.subTest(key=key), self.assertRaises(flow.Blocked):
                flow.bind_review_response({**raw, key: value}, request, files, set(files), {'charts': []})
        with self.assertRaisesRegex(flow.Blocked, 'every chart'):
            flow.bind_review_response(raw, request, files, set(files), {'charts': [{'figure_id': 'fig-1'}]})

    def test_empty_python_package_file_is_valid_recording_input(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        self.cfg['runner'].update(review_mode='combined_final')
        fake = FakeExecutor(revise_visual=True)
        def execute(cfg, case, stage, context, output=None):
            rec = fake(cfg, case, stage, context, output)
            if stage == 'repair_final':
                fixtures.put(case / 'app/vendor/library/__init__.py', b'')
            return rec
        state = self.run_fake(execute)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual([s for _, s in fake.stages].count('video'), 2)

    def test_mapped_contacts_cover_samples_without_claiming_full_frame_reads(self):
        frames = [{'file': f'frames/{i}.jpg', 'type': t} for i, t in enumerate(['first', 'uniform_sample', 'last'])]
        sheets = [{'file': 'contact.jpg', 'frame_files': [f['file'] for f in frames]}]
        self.assertEqual(flow.contact_sample_coverage(frames, sheets), {'frames/1.jpg'})
        self.assertEqual(flow.contact_sample_coverage(frames, [{'file': 'legacy.jpg'}]), set())
        for names in [['frames/0.jpg'], ['frames/0.jpg', 'frames/1.jpg', 'frames/1.jpg', 'frames/2.jpg'], ['frames/0.jpg', 'frames/1.jpg', 'missing.jpg']]:
            with self.subTest(names=names), self.assertRaises(flow.Blocked):
                flow.contact_sample_coverage(frames, [{'file': 'contact.jpg', 'frame_files': names}])

    def test_parent_mapped_video_samples_still_hash_checked_but_not_duplicate_review_items(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        self.cfg['runner'].update(review_mode='combined_final')
        fake = FakeExecutor()
        captured = []
        def execute(cfg, case, stage, context, output=None):
            rec = fake(cfg, case, stage, context, output)
            if stage == 'video':
                path = case / 'recording/evidence/timeline.json'
                timeline = flow.read_json(path)
                timeline['contact_sheets'][0]['frame_files'] = [f['file'] for f in timeline['frames']]
                flow.atomic_json(path, timeline)
            if stage == 'review_final':
                captured.extend(context['required_review_files'])
            return rec
        state = self.run_fake(execute)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertIn('recording/evidence/contact.png', captured)
        self.assertIn('recording/evidence/first.png', captured)
        self.assertIn('recording/evidence/last.png', captured)
        self.assertNotIn('recording/evidence/frame-001.png', captured)
        self.assertIn('recording/evidence/frame-001.png', state['final_review']['snapshot_files'])
        case = __import__('pathlib').Path(state['workspace'])
        with (case / 'recording/evidence/frame-001.png').open('ab') as handle:
            handle.write(b'tampered')
        with self.assertRaisesRegex(flow.Blocked, 'timeline image hash'):
            manifest = flow.read_json(case / 'evidence/artifact-manifest.json')
            flow.validate_manifest(case, manifest['source_sha256'], video=True, cfg=self.cfg)

    def test_changed_file_during_compact_review_cannot_be_auto_bound(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        self.cfg['runner'].update(review_mode='combined_final')
        fake = FakeExecutor()
        def execute(cfg, case, stage, context, output=None):
            rec = fake(cfg, case, stage, context, output)
            if stage == 'review_final':
                flow.atomic_json(output, compact_response(flow.read_json(output), context['review_request']))
                with (case / 'evidence/ui/overview.png').open('ab') as f:
                    f.write(b'changed-during-review')
            return rec
        state = self.run_fake(execute)['cases'][0]
        self.assertEqual(state['stage'], 'blocked')
        self.assertIn('Artifacts changed during review', state['reason'])
        self.assertNotIn('final_review', state)

    def test_prompt_omits_previous_digest_transcription_but_keeps_issues(self):
        cfg = dict(self.cfg)
        cfg['_prompts'] = fixtures.MODULE.parent.parent / 'prompts'
        context = {'review_request': flow.review_request({'chart.png': 'a' * 64}, {'chart.png'}),
            'snapshot_files': {'chart.png': 'a' * 64}, 'snapshot_sha256': 'b' * 64,
            'final_review': {'verdict': 'revise', 'issues': [{'evidence': 'legend overlaps curve'}],
                'reviewed_files': [{'path': 'chart.png', 'sha256': 'a' * 64}]}}
        text = flow.prompt(cfg, 'review_final', context)
        self.assertIn('legend overlaps curve', text)
        self.assertIn('E001', text)
        self.assertNotIn('a' * 64, text)
        self.assertNotIn('提交前逐字符', text)

    def test_fourth_case_can_build_while_first_three_wait_for_review(self):
        for name in ('a', 'b', 'c', 'd'):
            self.make_source(name + '.docx')
        flow.plan(self.cfg, self.source)
        self.cfg['execution'] = {'case_concurrency': 3, 'review_concurrency': 1, 'recording_concurrency': 1}
        self.cfg['runner'].update(review_mode='combined_final')
        fourth_started = threading.Event()
        lock = threading.Lock()
        builds = []
        saw_fourth = []
        fake = FakeExecutor()
        def execute(cfg, case, stage, context, output=None):
            if stage == 'build':
                with lock:
                    builds.append(case.name)
                    if len(builds) == 4:
                        fourth_started.set()
            if stage == 'review_final' and not saw_fourth:
                saw_fourth.append(fourth_started.wait(4))
            return fake(cfg, case, stage, context, output)
        result = self.run_fake(execute)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(saw_fourth, [True], 'Review wait must not occupy a construction slot')


if __name__ == '__main__':
    unittest.main()
