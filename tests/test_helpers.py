import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from verify_docx import verify
from video_evidence import generate, media_tool

class HelperTests(unittest.TestCase):
    def test_explicit_media_tool_configuration_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = Path(tmp) / 'custom-ffmpeg.exe'
            tool.write_bytes(b'fixture executable path')
            self.assertEqual(media_tool('ffmpeg', {'ffmpeg': str(tool)}), str(tool.resolve()))

    def test_formula_preservation_checks_content_not_only_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(name,symbol):
                p=root/name
                with zipfile.ZipFile(p,'w') as z:
                    z.writestr('word/document.xml',f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><w:body><w:p><w:r><w:t>Original paragraph</w:t></w:r></w:p><w:p><m:oMath><m:r><m:t>{symbol}</m:t></m:r></m:oMath></w:p></w:body></w:document>')
                    z.writestr('word/media/original.png',b'original-media')
                return p
            a=write('a.docx','x');b=write('b.docx','y')
            r=verify(a,b)
            self.assertEqual(r['original_omml'],r['revised_omml'])
            self.assertEqual(r['changed_or_missing_original_formula_count'],1)
            self.assertFalse(r['structural_preservation_ok'])
            self.assertEqual(r['rendered_visual_status'],'not_checked')

    def test_wrong_final_figure_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'a.docx';figure=root/'expected.png';figure.write_bytes(b'latest-version')
            with zipfile.ZipFile(a,'w') as z:
                z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>')
                z.writestr('word/media/fig.png',b'old-version')
            r=verify(a,a,[figure])
            self.assertTrue(r['structural_preservation_ok'])
            self.assertFalse(r['all_requested_figures_embedded'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_video_full_timeline_endpoints_and_no_auto_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);video=root/'fixture.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=30','-t','1.2','-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True,capture_output=True)
            before=hashlib.sha256(video.read_bytes()).hexdigest()
            r=generate(video,root/'proof',sample_fps=5,min_seconds=1,max_seconds=2)
            self.assertTrue(r['decode_ok'])
            self.assertTrue(r['duration_in_requested_range'])
            self.assertEqual(r['visual_review_status'],'pending_astra')
            self.assertEqual({f['type'] for f in r['frames']},{'first','last','uniform_sample'})
            self.assertEqual(next(f for f in r['frames'] if f['type']=='last')['source_frame_index'],r['source_frame_count']-1)
            self.assertEqual(len([f for f in r['frames'] if f['type']=='uniform_sample']),6)
            self.assertEqual([p for sheet in r['contact_sheets'] for p in sheet['frame_files']], [f['file'] for f in r['frames']])
            self.assertEqual(before,hashlib.sha256(video.read_bytes()).hexdigest())
            self.assertTrue((root/'proof'/'timeline.json').is_file())
            with self.assertRaises(ValueError):generate(video,root/'proof')

if __name__=='__main__':unittest.main()
