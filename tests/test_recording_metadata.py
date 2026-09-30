import json, tempfile, unittest
from pathlib import Path
import test_caseflow
from caseflow import recording_inputs

class RecordingMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.case=Path(self.tmp.name).resolve()
        (self.case/'evidence').mkdir(); (self.case/'web').mkdir()
        (self.case/'evidence/artifact-manifest.json').write_text(json.dumps({'ui_screenshots':[],'charts':[]}))
        (self.case/'web/app.js').write_text('actual browser application')
        self.note=self.case/'.caseflow-environment.json'
        self.note.write_text(json.dumps({'status':'ready','reason':'old environment check'}))
    def tearDown(self):self.tmp.cleanup()
    def test_environment_diagnostic_update_does_not_require_browser_rerecord(self):
        before=recording_inputs(self.case)
        self.note.write_text(json.dumps({'status':'ready','reason':'new successful write probe'}))
        self.assertEqual(recording_inputs(self.case),before)
    def test_actual_browser_code_and_business_data_still_require_rerecord(self):
        before=recording_inputs(self.case)
        (self.case/'web/app.js').write_text('changed browser application')
        self.assertNotEqual(recording_inputs(self.case),before)
        before=recording_inputs(self.case)
        (self.case/'business.json').write_text('{"threshold":0.2}')
        self.assertNotEqual(recording_inputs(self.case),before)
