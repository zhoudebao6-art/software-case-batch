import unittest
from test_caseflow import flow


class ReviewChecklistTests(unittest.TestCase):
    def test_missing_pdf_reports_exact_id_and_path_without_filling_it(self):
        files = {'page.png': 'a'*64, 'word.pdf': 'b'*64}
        req = flow.review_request(files, set(files))
        raw = dict(protocol='evidence-ids-v1', review_id=req['review_id'], verdict='pass', issues=[],
                   chart_reviews=[], reviewed_evidence=['E001'], coverage='Read PNG only', limitations=[])
        with self.assertRaises(flow.Blocked) as error:
            flow.bind_review_response(raw, req, files, set(files), {'charts': []})
        self.assertIn('E002', str(error.exception))
        self.assertIn('word.pdf', str(error.exception))
        self.assertEqual(raw['reviewed_evidence'], ['E001'])

    def test_checklist_does_not_certify_content_or_modify_ids(self):
        from review_check import check_ids
        req = flow.review_request({'word.pdf':'a'*64, 'page.png':'b'*64}, {'word.pdf','page.png'})
        self.assertTrue(check_ids(req, ['E001', 'E002'])['complete'])
        for ids in (['E001'], ['E001','E002','E002'], ['E001','E999']):
            with self.subTest(ids=ids):
                before = ids[:]
                result = check_ids(req, ids)
                self.assertFalse(result['complete'])
                self.assertEqual(ids, before)
