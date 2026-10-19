"""Visual paths shorten lookup without changing first-review scope or IDs."""
import unittest
import test_review_packet as helpers
from common import digest, read_json, write_json
from evidence_index import create, review_input


class NavigationTests(unittest.TestCase):
    setUp=helpers.ReviewPacketTests.setUp
    def prepare(self):
        for name in ('contact.jpg','action.jpg','first.jpg','last.jpg','uniform.jpg'):
            (self.work/name).write_bytes(name.encode())
        def row(name,**extra):return {'file':str(self.work/name),'sha256':digest(self.work/name),**extra}
        write_json(self.timeline,{'frames':[row('first.jpg',type='first'),row('uniform.jpg',type='uniform_sample'),row('last.jpg',type='last')],
                                  'contact_sheets':[row('contact.jpg')],'interaction_frames':[row('action.jpg')]})
        write_json(self.control/'controlled-video.json',{'timeline':str(self.timeline),'sha256':digest(self.timeline)})
        files=['chart.png','app.py','contact.jpg','action.jpg','first.jpg','last.jpg','uniform.jpg']
        manifest=self.work/'manifest.json';write_json(manifest,{'files':files})
        index=self.work/'index.json';create(self.work,manifest,index);return index
    def test_direct_visual_paths_keep_complete_index_and_zero_coverage(self):
        index=self.prepare();before=index.read_bytes();facts=self.control/'facts.json'
        review_input(self.work,index,facts,compact=True);result=read_json(facts)
        nav=result['visual_navigation'];self.assertFalse(nav['coverage_claim'])
        self.assertEqual(nav['charts'][0]['path'],str(self.png));self.assertEqual(nav['charts'][0]['evidence_id'],'E001')
        self.assertEqual(len(nav['video']['contact_sheets']),1);self.assertEqual(len(nav['video']['interaction_frames']),1)
        self.assertEqual([r['type'] for r in nav['video']['endpoints']],['first','last'])
        self.assertNotIn('uniform.jpg',str(nav));self.assertEqual(index.read_bytes(),before)
        self.assertEqual(result['evidence_directory']['evidence_items'],7)
        self.assertNotIn('reviewed_evidence',result);self.assertNotIn('decision',result)
        self.assertIn('stable Word/video',result['review_sequence']['on_blocking_defect'])
    def test_changed_navigation_hash_rejected_even_when_index_itself_is_valid(self):
        index=self.prepare();report=read_json(self.timeline);report['contact_sheets'][0]['sha256']='0'*64
        write_json(self.timeline,report);write_json(self.control/'controlled-video.json',{'timeline':str(self.timeline),'sha256':digest(self.timeline)})
        facts=self.control/'facts.json'
        with self.assertRaisesRegex(ValueError,'navigation input changed'):review_input(self.work,index,facts,True)
        self.assertFalse(facts.exists())
    def test_external_navigation_path_rejected(self):
        index=self.prepare();outside=self.root/'external.jpg';outside.write_bytes(b'external')
        report=read_json(self.timeline);report['contact_sheets']=[{'file':str(outside),'sha256':digest(outside)}]
        write_json(self.timeline,report);write_json(self.control/'controlled-video.json',{'timeline':str(self.timeline),'sha256':digest(self.timeline)})
        with self.assertRaises(ValueError):review_input(self.work,index,self.control/'facts.json',True)

if __name__=='__main__':unittest.main()
