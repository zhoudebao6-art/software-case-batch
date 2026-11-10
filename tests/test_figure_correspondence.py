"""Bindings and single-review coverage, not automatic geometric verification."""
import copy
import unittest
import test_explanation_facts as fact_fixtures
from contracts import validate_correspondence_review
from common import read_json, write_json


class FigureCorrespondenceTests(unittest.TestCase):
    def setUp(self):
        self.fx = fact_fixtures.ExplanationFactTests()
        self.fx.setUp()

    def tearDown(self):
        self.fx.tearDown()

    def test_symbol_prose_alone_is_not_a_depiction(self):
        self.fx.symbol()
        self.fx.first().pop('depiction')
        with self.assertRaisesRegex(ValueError, 'Figure correspondence'):
            self.fx.snapshot()

    def test_matrix_and_spatial_relation_bind_distinct_panel_representations(self):
        self.fx.symbol('<m:r><m:t>B</m:t></m:r>', 'B')
        mapping = {'panel':'b / second sample', 'quantity_type':'matrix',
                   'visible_objects':'eL and eT arrows from b',
                   'relationship':'columns are the two tangent basis vectors, not a position point'}
        self.fx.first()['depiction'] = mapping
        snapshot = self.fx.snapshot()
        self.assertEqual(snapshot['explanation_key_facts']['1'][0]['depiction'], mapping)
        fact = copy.deepcopy(self.fx.first())
        fact.update(fact_id='tangent-relation', kind='spatial_relation')
        fact['depiction'] = dict(mapping, quantity_type='relation')
        self.fx.f.figures[0]['key_facts'].append(fact)
        self.assertEqual(len(self.fx.snapshot()['explanation_key_facts']['1']), 2)

    def test_empty_or_invalid_depiction_does_not_pass(self):
        self.fx.symbol()
        original = copy.deepcopy(self.fx.first()['depiction'])
        for key in original:
            self.fx.first()['depiction'] = dict(original, **{key:' '})
            with self.assertRaisesRegex(ValueError, 'Figure correspondence'):
                self.fx.snapshot()
        self.fx.first()['depiction'] = dict(original, quantity_type='unknown')
        with self.assertRaisesRegex(ValueError, 'quantity_type'):
            self.fx.snapshot()

    def test_existing_review_records_all_actual_fact_ids_without_new_round(self):
        chart = self.fx.snapshot()
        reviews = [{'figure_id':i, 'explanation':{'checked_fact_ids':['event-1'],
                     'evidence':'Read actual plot and its surrounding source/explanation; time, unit and event agree.'}}
                   for i in (1, 2)]
        validate_correspondence_review(chart, reviews)
        for ids in (None, [], ['missing'], ['event-1','event-1'], [True]):
            reviews[0]['explanation']['checked_fact_ids'] = ids
            with self.assertRaisesRegex(ValueError, 'checked fact IDs'):
                validate_correspondence_review(chart, reviews)

    def test_v1_history_and_package_revision_keep_original_contract(self):
        self.fx.symbol()
        self.fx.first().pop('depiction')
        self.fx.f.run['explanation_fact_policy'] = 'key-facts-v1'
        snapshot = self.fx.snapshot()
        self.assertNotIn('depiction', snapshot['explanation_key_facts']['1'][0])
        validate_correspondence_review(snapshot, [])
        from proflow import prepare
        base, _, _ = self.fx.f.revision_fixture()
        run_path = base/'.product-v2/run.json'
        old = read_json(run_path)
        old['explanation_fact_policy'] = 'key-facts-v1'
        write_json(run_path, old)
        work = self.fx.f.root/'legacy-package'
        work.mkdir()
        result = prepare(work, self.fx.f.root/'legacy-out', '设备运行控制',
                         self.fx.f.source, base, revision_scope='package')
        self.assertEqual(result['explanation_fact_policy'], 'key-facts-v1')

    def test_review_packet_contains_actual_pixel_scope_and_no_prefilled_attestation(self):
        from evidence_index import create, review_input
        self.fx.snapshot()
        work = self.fx.f.work
        write_json(work/'files.json', {'files':['evidence/calculation.csv']})
        create(work, work/'files.json', work/'index.json')
        review_input(work, work/'index.json', work/'facts.json')
        facts = read_json(work/'facts.json')
        requirement = facts['chart_review_requirements']['correspondence_instruction']
        self.assertIn('Do not add another review round', requirement)
        self.assertIn('actual', requirement)
        self.assertNotIn('chart_reviews', facts)
        self.assertIn('matrix is not a point', facts['chart_review_requirements']['key_fact_instruction'])


class SimplifiedCorrespondenceTests(unittest.TestCase):
    def setUp(self):
        import test_simplified_closure as closure_fixtures
        self.fx = closure_fixtures.SimplifiedClosureTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        f = self.fx.f
        f.charts.update(explanation_fact_policy='key-facts-v2', explanation_key_facts={
            str(n): [{'fact_id':'basis', 'kind':'spatial_relation', 'basis':{'sha256':'fixture'},
                      'depiction':{'panel':'whole', 'quantity_type':'relation',
                                   'visible_objects':'two arrows', 'relationship':'basis directions'}}]
            for n in (1, 2)})
        # Synthetic first-review dispatch still authenticates its actual fixture
        # bytes; no current production run or independent judgment is fabricated.
        write_json(f.work/'.product-v2/first-dispatch.json', f.dispatch)
        self.fx.proof['first_dispatch'] = __import__('simplified_closure').reference(
            f.work/'.product-v2/first-dispatch.json')
        self.fx.refresh_first()

    def test_real_simplified_entry_rejects_missing_correspondence_coverage(self):
        with self.assertRaisesRegex(ValueError, 'checked fact IDs'):
            self.fx.close()

    def test_real_simplified_entry_merges_original_reading_and_current_affected_check(self):
        from common import digest
        self.fx.f.proof['chart_reviews'][0]['explanation']['checked_fact_ids']=['basis']
        self.fx.refresh_first()
        f=self.fx.f; name=f.run['word_name']
        log=f.work/'affected-correspondence.log'
        log.write_text('Synthetic existing affected Word reading; no second independent review')
        self.fx.proof['affected_checks']=[{
            'kind':'word_visual','command':'existing affected Word selfcheck', 'exit_code':0,
            'log':log.name,'sha256':digest(log),'artifact_hashes':{name:self.fx.current[name]},
            'visual_notes':['Opened the current affected figure and surrounding paragraph'],
            'chart_reviews':[{'figure_id':2,'png_sha256':f.charts['figures']['2'],
                'explanation':{'passed':True,'checked_fact_ids':['basis'],
                    'evidence':'Two arrows correspond to the stated two basis directions in this panel.'}}]}]
        self.fx.save()
        result=self.fx.close()
        self.assertFalse(result.get('independent_pass_claimed', False))

    def test_changed_fact_cannot_reuse_old_reading_with_same_id(self):
        from simplified_closure import correspondence_coverage
        first=copy.deepcopy(self.fx.f.proof)
        for review in first['chart_reviews']:
            review['explanation']['checked_fact_ids']=['basis']
        current=copy.deepcopy(first['chart_snapshot'])
        current['explanation_key_facts']['1'][0]['depiction']['relationship']='different projection'
        with self.assertRaisesRegex(ValueError, 'checked fact IDs'):
            correspondence_coverage(first,current,{},self.fx.f.run['word_name'],self.fx.current)


if __name__ == '__main__':
    unittest.main()
