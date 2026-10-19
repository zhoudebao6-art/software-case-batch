import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import delivery_index as index


class DeliveryIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_case(self, base):
        (base / '系统材料/数据').mkdir(parents=True)
        for rel in ('原名.docx', '系统材料/源代码.zip', '系统材料/操作视频.mp4', '系统材料/数据/结果.csv'):
            (base / rel).write_bytes(b'opaque content must not be decoded or reviewed')
        return base

    def test_shallow_scan_excludes_staging_source_and_center(self):
        case = self.make_case(self.root / '批次' / '（重写）案件')
        self.make_case(self.root / '.staging' / '候选')
        self.make_case(self.root / index.CENTER / '候选')
        (self.root / '交付包').mkdir()
        (self.root / '交付包' / '整案.zip').write_bytes(b'zip')
        result = index.refresh(self.root)
        self.assertEqual(result['case_directories'], 1)
        self.assertEqual(result['packages'], 1)
        page = Path(result['page']).read_text(encoding='utf-8')
        self.assertIn('（重写）案件', page)
        self.assertIn(case.as_uri(), page)
        self.assertNotIn('候选', page)

    def test_refresh_never_reads_artifact_bytes_and_does_not_claim_pass(self):
        self.make_case(self.root / '批次' / '案件')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('No artifact hashing or reads allowed')):
            result = index.refresh(self.root)
        self.assertFalse(result['acceptance_or_customer_delivery_inferred'])
        self.assertFalse(result['artifact_contents_read'])

    def test_missing_files_remain_visible_not_passed(self):
        case = self.make_case(self.root / '批次' / '案件')
        (case / '系统材料/操作视频.mp4').unlink()
        result = index.refresh(self.root)
        page = Path(result['page']).read_text(encoding='utf-8')
        self.assertIn('未找到', page)
        self.assertNotIn((case / '系统材料/操作视频.mp4').as_uri(), page)

    def test_refresh_updates_removed_paths_and_preserves_unrelated_page(self):
        case = self.make_case(self.root / '批次' / '案件')
        result = index.refresh(self.root)
        video = case / '系统材料/操作视频.mp4'
        video.unlink()
        index.refresh(self.root)
        self.assertNotIn(video.as_uri(), Path(result['page']).read_text(encoding='utf-8'))
        Path(result['page']).write_text('user-authored page', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Preserve unrelated'):
            index.refresh(self.root)
        self.assertEqual(Path(result['page']).read_text(encoding='utf-8'), 'user-authored page')

    def test_collection_and_escaped_titles(self):
        self.make_case(self.root / '交付包' / '加急合集' / '批次' / 'A&B')
        result = index.refresh(self.root)
        self.assertEqual(result['case_directories'], 1)
        self.assertIn('A&amp;B', Path(result['page']).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
