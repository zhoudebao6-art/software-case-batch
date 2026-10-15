"""Compact neutral facts retain every original evidence item and zero view claims."""
import json
import unittest
import test_review_packet as helpers
from common import digest, read_json, write_json
from evidence_index import check, create, index_summary, review_input
from review_packet import draft


class CompactEvidenceTests(unittest.TestCase):
    setUp = helpers.ReviewPacketTests.setUp

    def test_1177_item_index_stays_complete_but_is_not_duplicated_into_model_facts(self):
        directory = self.work / 'evidence'; directory.mkdir()
        files = []
        for number in range(1177):
            path = directory / ('page-' + str(number) + '.png'); path.write_bytes(b'fixture evidence')
            files.append(path.relative_to(self.work).as_posix())
        manifest = self.work / 'manifest.json'; write_json(manifest, {'files': files})
        index = self.work / 'full-index.json'; original = create(self.work, manifest, index)
        initial = index.read_bytes()
        normal = self.control / 'normal-facts.json'; review_input(self.work, index, normal)
        result = draft(self.work, self.execution, self.target, index=index, compact=True)
        self.assertEqual(result['status'], 'draft_created')
        compact = self.target / 'facts.json'; facts = read_json(compact)
        self.assertNotIn('evidence', facts)
        self.assertEqual(facts['evidence_directory']['evidence_items'], 1177)
        self.assertFalse(facts['evidence_directory']['coverage_claim'])
        self.assertLess(compact.stat().st_size, normal.stat().st_size / 10)
        self.assertEqual(read_json(self.target / 'index.json')['evidence'], original['evidence'])
        self.assertEqual(read_json(self.target / 'review-draft.json')['reviewed_evidence'], [])
        self.assertFalse(check(index, [], self.work)['complete'])
        self.assertTrue(check(index, [row['id'] for row in original['evidence']], self.work)['complete'])
        self.assertEqual(index.read_bytes(), initial)

    def test_compact_mode_still_rejects_changed_evidence_and_does_not_write_partial_draft(self):
        manifest = self.work / 'manifest.json'; write_json(manifest, {'files': ['chart.png', 'app.py']})
        index = self.work / 'index.json'; create(self.work, manifest, index)
        self.png.write_bytes(b'changed figure')
        report = draft(self.work, self.execution, self.target, index=index, compact=True)
        self.assertEqual(report['status'], 'blocked'); self.assertFalse(self.target.exists())


if __name__ == '__main__': unittest.main()
