"""Source-bound Word placement regression, without model or renderer claims."""
import copy
import sys
from pathlib import Path
import unittest
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_contracts as fixtures
from common import digest, write_json
from contracts import chart_snapshot, EXPLANATION_CONTEXT_POLICY
from proflow import prepare


class ExplanationContextTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ContractTests()
        self.f.setUp()
        self.prose = [
            '实施例一：对相同输入执行计算并记录其条件。',
            '步骤二：由上述结果选择下一操作，随后核对状态。',
            '图9 原有结构',
        ]
        self.reset_source()
        self.f.run['explanation_context_policy'] = EXPLANATION_CONTEXT_POLICY
        for i, figure in enumerate(self.f.figures):
            figure['explanation_after_source_block'] = i
        self.references = [
            fixtures.p('请参考图1。上述输入在相同条件下得到对应结果，供下一步骤选择。'),
            fixtures.p('请参考图2。状态变化与本步骤选择一致，失败时保留原状态。'),
        ]
        self.write()

    def tearDown(self):
        self.f.tearDown()

    def reset_source(self):
        with zipfile.ZipFile(self.f.source, 'w') as z:
            z.writestr('word/document.xml', fixtures.doc(''.join(map(fixtures.p, self.prose))))
        self.f.run['source_docx_sha256'] = digest(self.f.source)
        self.f.run.pop('chart_numbering_policy', None)

    def images(self):
        return ''.join(
            f'<w:p><w:r><w:drawing><a:blip r:embed="rId{f["figure_id"]}"/></w:drawing></w:r></w:p>'
            + fixtures.p(f['caption']) for f in self.f.figures)

    def write(self, body=None):
        write_json(self.f.work / '.product-v2/chart-manifest.json', {'figures': self.f.figures})
        write_json(self.f.work / '.product-v2/run.json', self.f.run)
        if body is None:
            body = (fixtures.p(self.prose[0]) + self.references[0]
                    + fixtures.p(self.prose[1]) + self.references[1]
                    + fixtures.p(self.prose[2]))
        self.f.make_word(body + self.images())

    def snapshot(self):
        return chart_snapshot(self.f.work, self.f.word, self.f.run)

    def test_contextual_prose_preserves_originals_and_appended_images(self):
        result = self.snapshot()
        self.assertEqual(result['explanation_context_policy'], EXPLANATION_CONTEXT_POLICY)
        contexts = result['explanation_contexts']
        self.assertEqual(contexts['1']['placements'][0]['source_text'], self.prose[0])
        self.assertEqual(contexts['1']['placements'][0]['next_source_text'], self.prose[1])
        self.assertEqual(contexts['2']['placements'][0]['reference_blocks'], [3])

    def test_appendix_explanations_fail_even_with_references_before_images(self):
        self.write(''.join(map(fixtures.p, self.prose)) + ''.join(self.references))
        with self.assertRaisesRegex(ValueError, 'outside its declared'):
            self.snapshot()

    def test_appendix_heading_does_not_turn_tail_into_original_body(self):
        self.write(''.join(map(fixtures.p, self.prose))
                   + fixtures.p('实施例补充分析') + ''.join(self.references))
        with self.assertRaisesRegex(ValueError, 'outside its declared'):
            self.snapshot()

    def test_missing_anchor_fails(self):
        self.f.figures[0].pop('explanation_after_source_block')
        self.write()
        with self.assertRaisesRegex(ValueError, 'source body anchor'):
            self.snapshot()

    def test_anchor_rejects_bool_out_of_range_blank_and_caption(self):
        for anchor in (True, -1, 3, 2):
            with self.subTest(anchor=anchor):
                self.f.figures[0]['explanation_after_source_block'] = anchor
                self.write()
                with self.assertRaises(ValueError):
                    self.snapshot()
        self.prose[0] = ''
        self.reset_source()
        self.f.figures[0]['explanation_after_source_block'] = 0
        self.write()
        with self.assertRaisesRegex(ValueError, 'body prose'):
            self.snapshot()

    def test_reference_without_prose_does_not_cover_explanation_elsewhere(self):
        self.references[0] = fixtures.p('请参考图1。')
        self.write()
        with self.assertRaisesRegex(ValueError, 'without its explanation'):
            self.snapshot()

    def test_repeated_reference_is_valid_but_digit_prefix_is_not(self):
        self.references[0] += fixtures.p('请参考图1。另一段重复引用。')
        self.write()
        self.assertEqual(self.snapshot()['explanation_contexts']['1']['placements'][0]['reference_blocks'], [1, 2])
        self.references[0] = fixtures.p('请参考图10。不能替代图1的独立说明。')
        self.write()
        with self.assertRaisesRegex(ValueError, 'at least one'):
            self.snapshot()

    def test_one_gap_can_hold_two_related_explanations(self):
        self.f.figures[1]['explanation_after_source_block'] = 0
        self.write(fixtures.p(self.prose[0]) + ''.join(self.references)
                   + ''.join(map(fixtures.p, self.prose[1:])))
        contexts = self.snapshot()['explanation_contexts']
        # Joint explanation paragraphs may discuss both figures in the same gap.
        self.assertEqual(contexts['1']['placements'][0]['explanation_blocks'], [1, 2])
        self.assertEqual(contexts['2']['placements'][0]['explanation_blocks'], [1, 2])

    def test_standalone_reference_can_have_multiple_explanation_paragraphs(self):
        self.references[0] = (fixtures.p('请参考图1。')
                              + fixtures.p('同一输入和条件决定结果。')
                              + fixtures.p('该结果衔接下一步骤。'))
        self.write()
        self.assertEqual(self.snapshot()['explanation_contexts']['1']['placements'][0]['explanation_blocks'], [1, 2, 3])

    def test_last_original_prose_is_a_valid_anchor_without_forcing_new_source_content(self):
        self.prose.pop()
        self.reset_source()
        self.write(fixtures.p(self.prose[0]) + self.references[0]
                   + fixtures.p(self.prose[1]) + self.references[1])
        self.assertIsNone(self.snapshot()['explanation_contexts']['2']['placements'][0]['next_source_text'])

    def test_body_placeholder_cannot_hide_unreferenced_tail_explanation(self):
        body = (fixtures.p(self.prose[0]) + fixtures.p('请参考图1。见下文分析。')
                + fixtures.p(self.prose[1]) + fixtures.p('请参考图2。见下文分析。')
                + fixtures.p(self.prose[2]) + fixtures.p('真正完整的结果分析仍错误地留在文末。'))
        self.write(body)
        with self.assertRaisesRegex(ValueError, 'outside every declared'):
            self.snapshot()

    def test_unbound_native_formula_also_fails(self):
        body = (fixtures.p(self.prose[0]) + self.references[0]
                + fixtures.p(self.prose[1]) + self.references[1] + fixtures.p(self.prose[2])
                + '<w:p><m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
                '<m:r><m:t>x=2</m:t></m:r></m:oMath></w:p>')
        self.write(body)
        with self.assertRaisesRegex(ValueError, 'outside every declared'):
            self.snapshot()

    def test_same_figure_can_span_two_source_contexts_with_or_without_repeated_reference(self):
        self.prose.insert(2, '结果分析：汇总上述条件和状态的关系。')
        self.reset_source()
        self.f.figures[0]['explanation_after_source_block'] = [0, 2]
        for prefix in ('请参考图1。', ''):
            self.write(fixtures.p(self.prose[0]) + self.references[0]
                       + fixtures.p(self.prose[1]) + self.references[1]
                       + fixtures.p(self.prose[2]) + fixtures.p(prefix + '前述计算结果用于汇总判断。')
                       + fixtures.p(self.prose[3]))
            contexts = self.snapshot()['explanation_contexts']['1']['placements']
            self.assertEqual([p['explanation_blocks'] for p in contexts], [[1], [5]])
        self.f.figures[0]['explanation_after_source_block'] = 0
        self.write(fixtures.p(self.prose[0]) + self.references[0]
                   + fixtures.p(self.prose[1]) + self.references[1]
                   + fixtures.p(self.prose[2]) + fixtures.p('未登记的后半段说明。')
                   + fixtures.p(self.prose[3]))
        with self.assertRaisesRegex(ValueError, 'outside every declared'):
            self.snapshot()

    def test_last_body_anchor_does_not_cover_prose_after_appended_images(self):
        self.prose.pop()
        self.reset_source()
        body = fixtures.p(self.prose[0]) + self.references[0] + fixtures.p(self.prose[1]) + self.references[1]
        self.write(body)
        self.f.make_word(body + self.images() + fixtures.p('附图后不应残留的解释。'))
        with self.assertRaisesRegex(ValueError, 'outside every declared'):
            self.snapshot()

    def test_legacy_snapshot_and_idempotent_prepare_do_not_gain_new_contract(self):
        self.f.run.pop('explanation_context_policy')
        self.write(''.join(map(fixtures.p, self.prose)) + ''.join(self.references))
        self.assertNotIn('explanation_contexts', self.snapshot())
        self.assertNotIn('explanation_context_policy',
                        prepare(self.f.work, self.f.out, '设备运行控制', self.f.source))

    def test_fresh_prepare_freezes_context_policy(self):
        work = self.f.root / 'fresh'
        work.mkdir()
        result = prepare(work, self.f.root / 'fresh-out', '设备运行控制', self.f.source)
        self.assertEqual(result['explanation_context_policy'], EXPLANATION_CONTEXT_POLICY)

    def test_unknown_policy_fails_closed(self):
        self.f.run['explanation_context_policy'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'Unknown explanation'):
            self.snapshot()

    def test_neutral_review_facts_use_actual_context_not_a_semantic_pass(self):
        from evidence_index import create, review_input
        log = self.f.work / 'observed.txt'
        log.write_text('fixture evidence', encoding='utf-8')
        inputs = self.f.work / 'evidence-files.json'
        index = self.f.work / 'index.json'
        write_json(inputs, {'files': ['observed.txt']})
        create(self.f.work, inputs, index)
        out = self.f.work / 'facts.json'
        review_input(self.f.work, index, out)
        import json
        facts = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(facts['current_charts']['explanation_contexts']['1']['placements'][0]['source_text'], self.prose[0])
        self.assertNotIn('decision', facts)
        self.assertIn('material document defect', facts['chart_review_requirements']['context_instruction'])


if __name__ == '__main__':
    unittest.main()
