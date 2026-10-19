import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import simplified_closure as closure
from common import file_map, write_json


class WholeCaseIOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.work = self.root / 'work'
        (self.work / '.product-v2').mkdir(parents=True)
        self.product = self.root / 'case'
        self.product.mkdir()
        for name in ['original.docx', 'source.zip', 'video.mp4', 'data.csv']:
            (self.product / name).write_bytes((name + '\n').encode() * 100)
        self.publication = {'files': file_map(self.product)}
        write_json(self.work / '.product-v2/publish-receipt.json', self.publication)
        self.archive = self.root / 'packages/case.zip'

    def tearDown(self):
        self.temp.cleanup()

    def run_pack(self):
        return closure.whole_case(self.work, self.product, self.archive, self.publication)

    def test_single_member_read_preserves_crc_and_sha(self):
        original = zipfile.ZipFile.open
        reads = []
        def observe(stream, name, mode='r', *args, **kwargs):
            if mode == 'r':
                reads.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
            return original(stream, name, mode, *args, **kwargs)
        with patch.object(zipfile.ZipFile, 'open', observe):
            result = self.run_pack()
        self.assertEqual(len(reads), len(self.publication['files']))
        self.assertTrue(result['crc_and_each_member_sha256_verified'])
        with zipfile.ZipFile(self.archive) as package:
            for info in package.infolist():
                content = package.read(info)
                self.assertEqual(hashlib.sha256(content).hexdigest(), result['members'][info.filename])
                self.assertEqual(info.compress_type, zipfile.ZIP_DEFLATED if info.filename.endswith('.csv') else zipfile.ZIP_STORED)
        self.assertEqual(self.run_pack(), result)

    def test_failed_write_preserves_original_and_can_resume(self):
        original = zipfile.ZipFile.write
        def interrupt(stream, *args, **kwargs):
            original(stream, *args, **kwargs)
            raise OSError('interrupted archive creation')
        with patch.object(zipfile.ZipFile, 'write', interrupt), self.assertRaises(OSError):
            self.run_pack()
        self.assertFalse(self.archive.exists())
        self.assertEqual(file_map(self.product), self.publication['files'])
        self.assertFalse(self.archive.with_name(self.archive.name+'.new').exists())
        self.assertEqual(list(self.archive.parent.glob('.scb-whole-*.tmp')), [])
        result = self.run_pack()
        self.assertTrue(self.archive.exists())
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(file_map(self.product), self.publication['files'])

    def test_member_crc_failure_in_recovery_is_rejected(self):
        original = closure.write_json
        def interrupt(path, value):
            if Path(path).name == 'whole-case-package.json':
                raise OSError('after rename')
            original(path, value)
        with patch.object(closure, 'write_json', interrupt), self.assertRaises(OSError):
            self.run_pack()
        contents = bytearray(self.archive.read_bytes())
        with zipfile.ZipFile(self.archive) as package:
            item = next(i for i in package.infolist() if i.filename.endswith('.mp4'))
        position = item.header_offset
        name_len = int.from_bytes(contents[position+26:position+28], 'little')
        extra_len = int.from_bytes(contents[position+28:position+30], 'little')
        contents[position+30+name_len+extra_len] ^= 1
        self.archive.write_bytes(contents)
        with self.assertRaises(zipfile.BadZipFile):
            self.run_pack()
        self.assertFalse((self.work / '.product-v2/whole-case-package.json').exists())


if __name__ == '__main__':
    unittest.main()
