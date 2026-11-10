import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from word_title import POLICY, W, check_title, normalize_written_word, normalized_part
from common import digest, write_json
from proflow import prepare
import test_contracts as fixtures
import test_source_integrity

TITLE = '直升机电机供电逆变器死区补偿方法'


def write_package(path, parts):
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in parts.items():
            archive.writestr(name, data)


class WordTitleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / '原件.docx'
        self.output = self.root / '交付.docx'
        split = '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>在一个实施例中，一</w:t></w:r><w:r><w:t>种直升机电机供电</w:t></w:r><w:r><w:t>逆变器死区补偿方法，包括步骤。</w:t></w:r></w:p>'
        self.parts = {'word/document.xml': fixtures.doc(fixtures.p(TITLE) + split + fixtures.p('一种已有三相电压型供电逆变器。') + fixtures.p('一种' + TITLE + '扩展算法。')),
                      'word/header1.xml': f'<w:hdr xmlns:w="{W}">' + fixtures.p('一种' + TITLE) + '</w:hdr>',
                      'word/footer1.xml': f'<w:ftr xmlns:w="{W}">' + fixtures.p('一种' + TITLE) + '</w:ftr>',
                      'word/media/image1.png': b'unchanged-image', 'customXml/data.xml': b'unchanged-data'}
        write_package(self.source, self.parts)
        write_package(self.output, self.parts)

    def tearDown(self):
        self.temp.cleanup()

    def test_split_runs_body_header_footer_only_prefix_and_idempotence(self):
        source_hash = digest(self.source)
        with self.assertRaisesRegex(ValueError, 'redundant'):
            check_title(self.output, self.source, TITLE)
        result = normalize_written_word(self.output, self.source, TITLE)
        self.assertEqual(result['replacements'], 3)
        self.assertEqual(check_title(self.output, self.source, TITLE)['cover_title'], TITLE)
        self.assertEqual(digest(self.source), source_hash)
        with zipfile.ZipFile(self.output) as archive:
            document = ET.fromstring(archive.read('word/document.xml'))
            text = ''.join(n.text or '' for n in document.iter('{' + W + '}t'))
            self.assertIn('一种已有三相电压型供电逆变器', text)
            self.assertIn('一种' + TITLE + '扩展算法', text)
            self.assertIn('在一个实施例中，' + TITLE + '，', text)
            self.assertIsNotNone(document.find('.//{' + W + '}b'))
            for name in ('word/media/image1.png', 'customXml/data.xml'):
                self.assertEqual(archive.read(name), self.parts[name])
        before = digest(self.output)
        self.assertEqual(normalize_written_word(self.output, self.source, TITLE)['replacements'], 0)
        self.assertEqual(before, digest(self.output))

    def test_cover_itself_has_prefix_preserved(self):
        self.parts['word/document.xml'] = fixtures.doc(fixtures.p('一种' + TITLE) + fixtures.p('一种' + TITLE + '。'))
        write_package(self.source, self.parts)
        write_package(self.output, self.parts)
        before = digest(self.output)
        self.assertEqual(normalize_written_word(self.output, self.source, TITLE)['replacements'], 0)
        self.assertEqual(before, digest(self.output))

    def test_natural_sentence_suffixes_and_repeated_prefix(self):
        for suffix in ('能够降低误差。', '的适用范围如下。', '可包括以下步骤。', '中采用统一缩放。', '所产生的结果。'):
            data = fixtures.doc(fixtures.p('一种' + TITLE + suffix)).encode()
            changed, total = normalized_part(data, TITLE)
            self.assertEqual(total, 1, suffix)
            text = ''.join(ET.fromstring(changed).itertext())
            self.assertEqual(text, TITLE + suffix)
        data = fixtures.doc(fixtures.p('一种一种' + TITLE + '。')).encode()
        self.assertEqual(''.join(ET.fromstring(normalized_part(data, TITLE)[0]).itertext()), TITLE + '。')
        self.assertEqual(normalized_part(data, '一种' + TITLE), (data, 0))

    def test_source_write_and_changed_or_missing_cover_rejected(self):
        with self.assertRaisesRegex(ValueError, 'read-only'):
            normalize_written_word(self.source, self.source, TITLE)
        self.parts['word/document.xml'] = fixtures.doc(fixtures.p('一种' + TITLE))
        write_package(self.output, self.parts)
        with self.assertRaisesRegex(ValueError, 'differs'):
            normalize_written_word(self.output, self.source, TITLE)
        self.parts['word/document.xml'] = fixtures.doc(fixtures.p('实施方式') + fixtures.p(TITLE))
        write_package(self.output, self.parts)
        with self.assertRaisesRegex(ValueError, 'locate'):
            normalize_written_word(self.output, self.source, TITLE)

    def test_new_prepare_freezes_policy_and_actual_builder_call(self):
        (self.root / 'work').mkdir()
        run = prepare(self.root / 'work', self.root / 'out', TITLE, self.source)
        self.assertEqual(run['word_title_policy'], POLICY)
        prompt = (self.root / 'work/.product-v2/深化命令词.txt').read_text(encoding='utf-8')
        self.assertIn('normalize_written_word', prompt)
        self.assertIn('渲染/计算hash/提交首审之前', prompt)

    def test_existing_chart_snapshot_catches_omission_and_accepts_only_allowed_edit(self):
        f = test_source_integrity.SourceIntegrityTests()
        f.setUp()
        try:
            f.source_blocks = [fixtures.p(TITLE), fixtures.p('一种' + TITLE + '，采用原控制。'), fixtures.p('一种普通装置保持不变。')]
            f.write()
            f.f.run.update(title=TITLE, word_title_policy=POLICY)
            with self.assertRaisesRegex(ValueError, 'redundant'):
                f.snapshot()
            normalize_written_word(f.f.word, f.f.source, TITLE)
            snapshot = f.snapshot()
            self.assertEqual(snapshot['word_title']['cover_title'], TITLE)
            parts = f.parts()
            parts['word/document.xml'] = parts['word/document.xml'].replace('原控制'.encode(), '其他控制'.encode())
            f.save(parts)
            with self.assertRaisesRegex(ValueError, 'body blocks'):
                f.snapshot()
        finally:
            f.tearDown()


if __name__ == '__main__':
    unittest.main()
