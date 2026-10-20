"""Frozen coverage claims only; no real source/visual review or model invocation."""
import copy
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import test_review_packet as helpers
from common import digest, file_map, read_json, write_json
from evidence_index import REVIEW_COVERAGE_POLICY, check, validate_review_coverage
from review_packet import draft, inspect


class ReviewCoverageTests(unittest.TestCase):
    def setUp(self):
        helpers.ReviewPacketTests.setUp(self)
        self.run = read_json(self.control / 'run.json')
        self.word = self.out / '技术材料.docx'; self.word.write_bytes(b'synthetic final Word')
        self.run.update(word_name=self.word.name, source_docx_sha256='1' * 64,
                        review_coverage_policy=REVIEW_COVERAGE_POLICY)
        write_json(self.control / 'run.json', self.run)
        for name in ('page-1.png', 'page-2.png', 'source-map.json', 'first.png', 'last.png',
                     'uniform.png', 'contact.png', 'interaction.png'):
            (self.work / name).write_bytes(('synthetic ' + name).encode())
        def frame(name, **extra): return {'file': str(self.work / name), 'sha256': digest(self.work / name), **extra}
        write_json(self.timeline, {'frames': [frame('first.png', type='first'), frame('uniform.png', type='uniform_sample'), frame('last.png', type='last')],
                                  'contact_sheets': [frame('contact.png')], 'interaction_frames': [frame('interaction.png')]})
        write_json(self.control / 'controlled-video.json', {'timeline': str(self.timeline), 'sha256': digest(self.timeline)})
        self.proof['video_timeline_sha256'] = digest(self.timeline); write_json(self.execution, self.proof)
        self.scope = {'word': {'sha256': digest(self.word), 'page_count': 2,
                               'pages': [{'page': 1, 'path': 'page-1.png'}, {'page': 2, 'path': 'page-2.png'}]},
                      'source_mappings': ['source-map.json']}
        self.manifest = self.work / 'required.json'
        write_json(self.manifest, {'files': ['page-1.png', 'page-2.png', 'source-map.json'], 'review_scope': self.scope})
        write_json(self.control / 'model-dispatch.json', {'stages': {'build': {}}})

    def prepared(self):
        result = draft(self.work, self.execution, self.target, manifest=self.manifest, compact=True)
        self.assertEqual(result['status'], 'draft_created', result)
        self.index = self.target / 'index.json'; self.spec = read_json(self.index)
        proof = read_json(self.target / 'review-draft.json')
        proof['chart_snapshot'] = read_json(self.target / 'facts.json')['current_charts']
        proof.update(reviewed_evidence=list(self.spec['required_evidence']), coverage='Opened every declared Word page, current chart and required video contact/endpoint/action evidence.')
        return proof, {'review_index': proof['review_index']}

    def rewrite_index(self, proof, stage, spec):
        write_json(self.index, spec)
        proof['review_index'] = {'path': str(self.index), 'sha256': digest(self.index)}
        stage['review_index'] = proof['review_index']

    def test_draft_freezes_neutral_reference_without_inventing_viewed_ids(self):
        proof, stage = self.prepared()
        neutral = read_json(self.target / 'review-draft.json')
        self.assertEqual(neutral['reviewed_evidence'], []); self.assertNotIn('coverage', neutral)
        self.assertEqual(neutral['review_index'], {'path': str(self.index), 'sha256': digest(self.index)})
        result = validate_review_coverage(self.work, self.run, proof, stage)
        self.assertEqual(result['status'], 'bound-reviewer-coverage')
        self.assertIn('do not prove actual viewing', result['note'])

    def test_complete_contact_sheets_do_not_require_each_uniform_original_frame_viewed(self):
        proof, stage = self.prepared(); rows = {row['path']: row['id'] for row in self.spec['evidence']}
        self.assertIn('uniform.png', rows); self.assertNotIn(rows['uniform.png'], proof['reviewed_evidence'])
        for path in ('contact.png', 'first.png', 'last.png', 'interaction.png', 'page-1.png', 'page-2.png', 'source-map.json'):
            self.assertIn(rows[path], proof['reviewed_evidence'])
        self.assertTrue(check(self.index, proof['reviewed_evidence'], self.work)['complete'])
        self.assertFalse(check(self.index, proof['reviewed_evidence'] + ['unknown'], self.work)['complete'])
        self.assertTrue(validate_review_coverage(self.work, self.run, proof, stage)['required'])

    def test_existing_visual_notes_and_limits_need_no_duplicate_coverage_narrative(self):
        proof, stage = self.prepared(); proof.pop('coverage', None)
        proof.update(visual_notes=['Existing actual review notes'], limitations=['Synthetic fixture'])
        self.assertTrue(validate_review_coverage(self.work, self.run, proof, stage)['required'])

    def test_current_validation_hashes_each_frozen_evidence_file_once(self):
        proof, stage = self.prepared()
        with patch('evidence_index.digest', wraps=digest) as hasher:
            validate_review_coverage(self.work, self.run, proof, stage)
        paths = [Path(call.args[0]) for call in hasher.call_args_list]
        for row in self.spec['evidence']:
            self.assertEqual(paths.count(self.work / row['path']), 1, row['path'])

    def test_incomplete_or_empty_explicit_index_cannot_shrink_declared_scope(self):
        for rows in ([], [{'id': 'E001', 'path': 'chart.png', 'sha256': digest(self.png)}]):
            with self.subTest(rows=rows):
                path = self.work / 'incomplete-index.json'
                write_json(path, {'workspace': str(self.work), 'review_id': 'partial', 'evidence': rows, 'review_scope': self.scope})
                result = inspect(self.work, self.execution, index=path)
                self.assertEqual(result['status'], 'blocked')
                self.assertTrue(result['errors'])
                if not rows:
                    with self.assertRaisesRegex(ValueError, 'Nonempty'): check(path, [], self.work)

    def test_declared_source_logs_pages_and_timeline_cannot_be_removed_from_final_index(self):
        proof, stage = self.prepared()
        for path in ('app.py', 'algorithm.log', 'page-2.png', '.product-v2/timeline.json', 'uniform.png'):
            with self.subTest(path=path):
                spec = copy.deepcopy(self.spec); dropped = next(row['id'] for row in spec['evidence'] if row['path'] == path)
                spec['evidence'] = [row for row in spec['evidence'] if row['path'] != path]
                spec['required_evidence'] = [value for value in spec['required_evidence'] if value != dropped]
                changed = copy.deepcopy(proof); changed['reviewed_evidence'] = list(spec['required_evidence']); record = copy.deepcopy(stage)
                self.rewrite_index(changed, record, spec)
                with self.assertRaisesRegex(ValueError, 'omits.*required'):
                    validate_review_coverage(self.work, self.run, changed, record)
        write_json(self.index, self.spec)

    def test_review_ids_and_parent_stage_binding_are_exact(self):
        proof, stage = self.prepared()
        mutations = [lambda p: p.update(reviewed_evidence=[]),
                     lambda p: p['reviewed_evidence'].append('unknown'),
                     lambda p: p['reviewed_evidence'].append(p['reviewed_evidence'][0]),
                     lambda p: p.update(review_id='other')]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                changed = copy.deepcopy(proof); mutate(changed)
                with self.assertRaises(ValueError): validate_review_coverage(self.work, self.run, changed, stage)
        with self.assertRaisesRegex(ValueError, 'same frozen review_index'):
            validate_review_coverage(self.work, self.run, proof, {'review_index': {'path': str(self.index), 'sha256': '0' * 64}})

    def test_word_scope_binds_current_hash_and_consecutive_actual_pages(self):
        for mutate in (lambda s: s['word'].update(sha256='0' * 64),
                       lambda s: s['word'].update(page_count=3),
                       lambda s: s['word']['pages'].reverse(),
                       lambda s: s.update(source_mappings=[])):
            with self.subTest(mutate=mutate):
                scope = copy.deepcopy(self.scope); mutate(scope)
                write_json(self.manifest, {'files': ['page-1.png', 'page-2.png', 'source-map.json'], 'review_scope': scope})
                self.assertEqual(inspect(self.work, self.execution, manifest=self.manifest)['status'], 'blocked')

    def test_appending_real_review_dispatch_after_draft_does_not_stale_index(self):
        proof, stage = self.prepared()
        self.assertNotIn('.product-v2/model-dispatch.json', {row['path'] for row in self.spec['evidence']})
        write_json(self.control / 'model-dispatch.json', {'stages': {'build': {}, 'review': stage}})
        self.assertTrue(validate_review_coverage(self.work, self.run, proof, stage)['required'])

    def test_explicit_dynamic_dispatch_file_is_rejected_with_repairable_scope_error(self):
        spec = read_json(self.manifest); spec['files'].append('.product-v2/model-dispatch.json'); write_json(self.manifest, spec)
        result = inspect(self.work, self.execution, manifest=self.manifest)
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(any('authenticated separately' in item['message'] for item in result['errors']))

    def test_targeted_repair_keeps_authenticated_first_snapshot_without_rehashing_old_source(self):
        proof, stage = self.prepared()
        (self.work / 'app.py').write_text('legitimate targeted repair')
        (self.work / 'page-1.png').unlink()
        self.assertEqual(validate_review_coverage(self.work, self.run, proof, stage, current=False)['status'], 'bound-reviewer-coverage')
        with self.assertRaises((ValueError, OSError)): validate_review_coverage(self.work, self.run, proof, stage, current=True)
        self.index.write_text(self.index.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'index changed'): validate_review_coverage(self.work, self.run, proof, stage, current=False)

    def test_frozen_first_revise_still_requires_its_original_video_reading_ids(self):
        proof, stage = self.prepared(); proof['decision'] = 'revise'
        video_id = next(row['id'] for row in self.spec['evidence'] if row['path'] == 'contact.png')
        proof['reviewed_evidence'].remove(video_id)
        (self.work / 'app.py').write_text('legitimate targeted repair')
        with self.assertRaisesRegex(ValueError, 'complete required evidence coverage'):
            validate_review_coverage(self.work, self.run, proof, stage, current=False)

    def test_first_revise_cannot_freeze_known_sources_charts_or_video_out_of_required_set(self):
        proof, stage = self.prepared(); proof['decision'] = 'revise'
        for path in ('app.py', 'chart.png', 'contact.png', '.product-v2/timeline.json'):
            with self.subTest(path=path):
                spec = copy.deepcopy(self.spec)
                dropped = next(row['id'] for row in spec['evidence'] if row['path'] == path)
                spec['required_evidence'].remove(dropped)
                changed = copy.deepcopy(proof); changed['reviewed_evidence'] = list(spec['required_evidence'])
                record = copy.deepcopy(stage); self.rewrite_index(changed, record, spec)
                with self.assertRaisesRegex(ValueError, 'known required'):
                    validate_review_coverage(self.work, self.run, changed, record, current=False)

    def test_historical_absence_and_unknown_policy_are_distinct(self):
        old = dict(self.run); old.pop('review_coverage_policy')
        self.assertFalse(validate_review_coverage(self.work, old, {}, {})['required'])
        self.assertFalse(validate_review_coverage(self.work, dict(old, review_coverage_policy=None), {}, {})['required'])
        for value in ('', 'future-version'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Unknown'):
                validate_review_coverage(self.work, dict(old, review_coverage_policy=value), {}, {})

    def test_new_document_revision_reviews_word_scope_without_new_system_or_video_evidence(self):
        self.run.update(revision_of={'workspace': str(self.root / 'previous')}, revision_scope='document')
        write_json(self.control / 'run.json', self.run)
        write_json(self.control / 'controlled-video.json', {'timeline': str(self.root / 'previous/timeline.json'), 'sha256': '2' * 64})
        write_json(self.execution, {'checks': []})
        proof, stage = self.prepared()
        paths = {row['path'] for row in self.spec['evidence']}
        self.assertNotIn('algorithm.log', paths); self.assertNotIn('contact.png', paths)
        self.assertNotIn('.product-v2/source-package.json', paths)
        self.assertIn('page-1.png', paths); self.assertIn('source-map.json', paths)
        self.assertNotIn('video', read_json(self.target / 'facts.json')['visual_navigation'])
        self.assertTrue(validate_review_coverage(self.work, self.run, proof, stage)['required'])

    def test_package_revision_inherits_frozen_visual_scope_without_rereading_parent_sources(self):
        previous, previous_stage = self.prepared()
        previous_path = self.control / 'accepted-review.json'; write_json(previous_path, previous)
        write_json(self.control / 'model-dispatch.json', {'stages': {'review': previous_stage}})
        receipt_path = self.control / 'final-receipt.json'
        write_json(receipt_path, {'status': 'complete', 'files': file_map(self.out), 'execution_evidence': str(previous_path), 'evidence_sha256': digest(previous_path)})
        chain = [{'workspace': str(self.work), 'receipt_sha256': digest(receipt_path), 'proof_sha256': digest(previous_path)}]
        work = self.root / 'package-work'; output = self.root / 'package-output'
        shutil.copytree(self.work, work); shutil.copytree(self.out, output)
        run = dict(self.run, workspace=str(work), output=str(output), run_id='package-revision',
                   revision_of={'workspace': str(self.work)}, revision_scope='package')
        write_json(work / '.product-v2/run.json', run)
        log = work / 'package.log'; log.write_text('current package startup fixture')
        checks = [{'kind': 'package_startup', 'log': 'package.log', 'command': 'fixture startup', 'exit_code': 0, 'sha256': digest(log)}]
        execution = work / 'package-execution.json'
        write_json(execution, {'checks': checks, 'source_zip_sha256': digest(output / '模拟系统/项目源码.zip'), 'inherited_evidence_chain': chain})
        manifest = work / 'package-manifest.json'; write_json(manifest, {'files': []})
        target = work / '.product-v2/review-inputs/package'
        result = draft(work, execution, target, manifest=manifest, compact=True)
        self.assertEqual(result['status'], 'draft_created', result)
        spec = read_json(target / 'index.json'); proof = read_json(target / 'review-draft.json')
        self.assertEqual(spec['review_scope'], {})
        self.assertNotIn('video', read_json(target / 'facts.json')['visual_navigation'])
        proof.update(reviewed_evidence=spec['required_evidence'], chart_snapshot=previous['chart_snapshot'])
        reference = proof['review_index']
        (self.work / 'app.py').write_text('later legitimate parent workspace repair')
        self.assertTrue(validate_review_coverage(work, run, proof, {'review_index': reference})['required'])
        previous_path.write_text(previous_path.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'Inherited independent review proof changed'):
            validate_review_coverage(work, run, proof, {'review_index': reference})


if __name__ == '__main__': unittest.main()
