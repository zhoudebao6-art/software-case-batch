"""Declared key facts bind real source files and exact contextual Word excerpts.

Fixtures exercise structural failures, not OCR or independent semantic review.
"""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_explanation_context as context_fixtures
import test_contracts as fixtures
from common import digest, read_json, write_json
from contracts import EXPLANATION_FACT_POLICY
from proflow import prepare


class ExplanationFactTests(unittest.TestCase):
    def setUp(self):
        self.context = context_fixtures.ExplanationContextTests()
        self.context.setUp()
        self.f = self.context.f
        self.f.run['explanation_fact_policy'] = EXPLANATION_FACT_POLICY
        self.basis = self.f.work / 'evidence/calculation.csv'
        self.basis.parent.mkdir(exist_ok=True)
        self.basis.write_text('时刻_s,温度_℃,事件\n12,80,阀门开启\n20,65,恢复稳态\n', encoding='utf-8')
        self.context.references = [
            fixtures.p('请参考图1。相同工况下，12 s时温度达到80 ℃并触发阀门开启；该变化用于下一步骤。'),
            fixtures.p('请参考图2。20 s时温度降至65 ℃并恢复稳态，随后核对状态。'),
        ]
        for i, figure in enumerate(self.f.figures):
            figure['key_facts'] = [{
                'fact_id': 'event-1', 'kind': 'event',
                'chart_text': '12 s / 80 ℃ / 阀门开启' if i == 0 else '20 s / 65 ℃ / 恢复稳态',
                'basis': {'path': 'evidence/calculation.csv', 'locator': f'数据行{i + 1}，时刻/温度/事件列'},
                'after_source_block': i, 'explanation_block': 2*i + 1,
                'explanation_excerpt': '12 s时温度达到80 ℃并触发阀门开启' if i == 0 else '20 s时温度降至65 ℃并恢复稳态',
            }]
        self.context.write()

    def tearDown(self):
        self.context.tearDown()

    def snapshot(self):
        self.context.write()
        return self.context.snapshot()

    def first(self):
        return self.f.figures[0]['key_facts'][0]

    def test_valid_facts_locate_specific_text_and_hash_real_basis(self):
        result = self.snapshot()
        self.assertEqual(result['explanation_fact_policy'], EXPLANATION_FACT_POLICY)
        fact = result['explanation_key_facts']['1'][0]
        self.assertEqual(fact['matches'][0]['block'], 1)
        self.assertIn('触发阀门开启', fact['matches'][0]['text'])
        self.assertEqual(fact['basis']['sha256'], digest(self.basis))
        self.assertNotIn('decision', result)

    def test_wrong_value_time_unit_or_event_cannot_match(self):
        original = self.context.references[0]
        for value in ('312 s', '12 min', '80 kPa', '阀门关闭'):
            with self.subTest(value=value):
                self.context.references[0] = original.replace(
                    '12 s' if value in ('312 s', '12 min') else '80 ℃' if value == '80 kPa' else '阀门开启', value)
                with self.assertRaisesRegex(ValueError, 'absent from its declared'):
                    self.snapshot()

    def test_number_or_decimal_substring_does_not_count(self):
        for excerpt, actual in (('12 s', '312 s'), ('结果为12', '结果为12.5'), ('0.12 MPa', '10.12 MPa')):
            with self.subTest(excerpt=excerpt, actual=actual):
                self.first()['explanation_excerpt'] = excerpt
                self.context.references[0] = fixtures.p('请参考图1。相同工况的结果为' + actual + '，供下一步判断。')
                with self.assertRaisesRegex(ValueError, 'absent from its declared'):
                    self.snapshot()

    def test_word_runs_spaces_fullwidth_and_compatible_unit_glyph_are_tolerated(self):
        self.context.references[0] = (fixtures.p('请参考图1。相同工况下，１２ s时温度达到８０ ℃并触发阀门开启；')
                                      .replace('１２ s时温度', '１２ s</w:t></w:r><w:r><w:t>时温度'))
        self.first()['explanation_excerpt'] = '12s时温度达到80°C并触发阀门开启'
        self.assertTrue(self.snapshot()['explanation_key_facts']['1'])

    def test_unsigned_value_cannot_match_a_signed_value(self):
        original = self.context.references[0]
        for value in ('-12 s', '−12 s', '+12 s'):
            with self.subTest(value=value):
                self.context.references[0] = original.replace('12 s', value)
                with self.assertRaisesRegex(ValueError, 'absent from its declared'):
                    self.snapshot()

    def test_scientific_notation_cannot_supply_only_its_exponent_or_mantissa(self):
        for excerpt, actual in (('12 s', '1e12 s'), ('-12 s', '1e-12 s'),
                                ('+12 s', '1e+12 s'), ('结果为12', '结果为12e3')):
            with self.subTest(excerpt=excerpt, actual=actual):
                self.first()['explanation_excerpt'] = excerpt
                self.context.references[0] = fixtures.p('请参考图1。相同工况的结果为' + actual + '，用于后续判断。')
                with self.assertRaisesRegex(ValueError, 'absent from its declared'):
                    self.snapshot()

    def test_same_text_elsewhere_or_original_source_does_not_cover_own_anchor(self):
        excerpt = self.first()['explanation_excerpt']
        self.context.references[0] = fixtures.p('请参考图1。只说明总体变化，关键事件遗漏。')
        self.context.references[1] += fixtures.p(excerpt)
        with self.assertRaisesRegex(ValueError, 'absent from its declared'):
            self.snapshot()

    def test_same_gap_requires_specific_block_and_rejects_other_figure_reference(self):
        self.f.figures[1]['explanation_after_source_block'] = 0
        self.f.figures[1]['key_facts'][0].update(after_source_block=0, explanation_block=2)
        self.f.figures[0]['key_facts'][0].update(explanation_block=2,
            explanation_excerpt='20 s时温度降至65 ℃并恢复稳态')
        self.context.write(fixtures.p(self.context.prose[0]) + ''.join(self.context.references)
                           + ''.join(map(fixtures.p, self.context.prose[1:])))
        with self.assertRaisesRegex(ValueError, 'different figure'):
            self.context.snapshot()

    def test_same_gap_cannot_search_another_unselected_explanation_block(self):
        self.context.references[0] = (fixtures.p('请参考图1。此处为变化原因。')
                                      + fixtures.p(self.first()['explanation_excerpt']))
        with self.assertRaisesRegex(ValueError, 'absent from its declared'):
            self.snapshot()
        self.first()['explanation_block'] = 2
        self.f.figures[1]['key_facts'][0]['explanation_block'] = 4
        self.assertTrue(self.snapshot()['explanation_key_facts']['1'])

    def test_fact_anchor_and_block_must_belong_to_this_figure(self):
        for anchor, block in ((1, 3), (True, 1), (0, 0), (0, True), (0, 3)):
            with self.subTest(anchor=anchor, block=block):
                self.first().update(after_source_block=anchor, explanation_block=block)
                with self.assertRaises(ValueError):
                    self.snapshot()

    def test_missing_empty_duplicate_and_invalid_fact_fields_fail(self):
        original = copy.deepcopy(self.f.figures[0]['key_facts'])
        variants = [None, [], [None], [dict(original[0], fact_id='')],
                    original + original, [dict(original[0], kind='anything')],
                    [dict(original[0], chart_text=' ')],
                    [dict(original[0], explanation_excerpt=' ')],
                    [dict(original[0], explanation_excerpt='12')],
                    [dict(original[0], explanation_excerpt='。')],
                    [dict(original[0], basis={'path':'evidence/calculation.csv', 'locator':' '})]]
        for facts in variants:
            with self.subTest(facts=facts):
                self.f.figures[0]['key_facts'] = facts
                with self.assertRaises(ValueError):
                    self.snapshot()

    def test_basis_rejects_outside_missing_and_empty_file(self):
        empty = self.f.work / 'evidence/empty.csv'
        empty.touch()
        outside = self.f.root / 'outside.csv'
        outside.write_text('not this workspace', encoding='utf-8')
        for path in ('../outside.csv', str(outside), 'evidence/missing.csv', 'evidence/empty.csv'):
            with self.subTest(path=path):
                self.first()['basis']['path'] = path
                with self.assertRaises(ValueError):
                    self.snapshot()

    def test_current_basis_change_changes_snapshot_without_new_evidence_ledger(self):
        before = self.snapshot()
        self.basis.write_text('时刻_s,温度_℃,事件\n12,81,阀门开启\n', encoding='utf-8')
        after = self.snapshot()
        self.assertNotEqual(before['explanation_key_facts'], after['explanation_key_facts'])
        # Exact text bindings deliberately do not assert data or semantic agreement.
        self.assertNotIn('passed', after['explanation_key_facts']['1'][0])

    def test_continuous_series_is_not_required_to_transcribe_every_sample_or_tick(self):
        with self.basis.open('a', encoding='utf-8') as stream:
            stream.writelines(f'{i / 100},70,连续采样\n' for i in range(1000))
        self.assertEqual(len(self.snapshot()['explanation_key_facts']['1']), 1)

    def test_historical_context_only_run_does_not_gain_new_contract(self):
        self.f.run.pop('explanation_fact_policy')
        self.f.figures[0].pop('key_facts')
        self.assertNotIn('explanation_key_facts', self.snapshot())
        before = digest(self.f.work / '.product-v2/run.json')
        result = prepare(self.f.work, self.f.out, '设备运行控制', self.f.source)
        self.assertNotIn('explanation_fact_policy', result)
        self.assertEqual(digest(self.f.work / '.product-v2/run.json'), before)

    def test_unknown_policy_or_missing_context_fails(self):
        for policy, context in (('unknown', 'source-context-v2'), (EXPLANATION_FACT_POLICY, None)):
            self.f.run['explanation_fact_policy'] = policy
            self.f.run['explanation_context_policy'] = context
            with self.assertRaises(ValueError):
                self.snapshot()

    def test_new_prepare_freezes_policy_and_explicit_build_prompt(self):
        work = self.f.root / 'fresh-facts'
        work.mkdir()
        result = prepare(work, self.f.root/'fresh-facts-out', '设备运行控制', self.f.source)
        self.assertEqual(result['explanation_fact_policy'], EXPLANATION_FACT_POLICY)
        prompt = (work/'.product-v2/深化命令词.txt').read_text(encoding='utf-8')
        self.assertIn('key_facts', prompt)

    def test_document_revision_adopts_new_policy_package_inherits_original(self):
        base, _, _ = self.f.revision_fixture()
        path = base / '.product-v2/run.json'
        previous = read_json(path)
        for i, policy in enumerate((None, EXPLANATION_FACT_POLICY)):
            prior = dict(previous)
            if policy:
                prior['explanation_fact_policy'] = policy
            write_json(path, prior)
            for scope in ('document', 'package'):
                work = self.f.root / f'facts-{i}-{scope}'
                work.mkdir()
                result = prepare(work, self.f.root/f'out-facts-{i}-{scope}', '设备运行控制',
                                 self.f.source, base, revision_scope=scope)
                self.assertEqual(result.get('explanation_fact_policy'),
                                 EXPLANATION_FACT_POLICY if scope == 'document' else policy)
                before = digest(work / '.product-v2/run.json')
                prepare(work, self.f.root/f'out-facts-{i}-{scope}', '设备运行控制',
                        self.f.source, base, revision_scope=scope)
                self.assertEqual(digest(work / '.product-v2/run.json'), before)

    def test_neutral_review_input_preserves_fact_bindings_and_human_completeness_scope(self):
        from evidence_index import create, review_input
        self.snapshot()
        inputs = self.f.work/'evidence-files.json'
        index = self.f.work/'index.json'
        write_json(inputs, {'files':['evidence/calculation.csv']})
        create(self.f.work, inputs, index)
        output = self.f.work/'facts.json'
        review_input(self.f.work, index, output)
        facts = read_json(output)
        self.assertEqual(facts['current_charts']['explanation_key_facts']['1'][0]['matches'][0]['block'], 1)
        self.assertIn('do not prove completeness', facts['chart_review_requirements']['key_fact_instruction'])
        self.assertNotIn('decision', facts)


if __name__ == '__main__':
    unittest.main()
