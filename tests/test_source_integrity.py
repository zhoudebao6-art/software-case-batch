"""Source-parts policy rejects real OOXML mutations, without a visual-pass claim."""
import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_contracts as fixtures
from common import digest, write_json
from contracts import chart_snapshot, SOURCE_INTEGRITY_POLICY

V = 'urn:schemas-microsoft-com:vml'
MC = 'http://schemas.openxmlformats.org/markup-compatibility/2006'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'


def relationship(identity, target, kind='image', mode=None):
    return (f'<Relationship Id="{identity}" Target="{target}" '
            f'Type="{fixtures.R}/{kind}"' + (f' TargetMode="{mode}"' if mode else '') + '/>')


def vml(identity='rIdOriginal'):
    return (f'<w:pict xmlns:v="{V}"><v:shape id="original" style="width:120pt;height:80pt">'
            f'<v:imagedata r:id="{identity}"/></v:shape></w:pict>')


class SourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ContractTests()
        self.f.setUp()
        self.f.run['source_integrity_policy'] = SOURCE_INTEGRITY_POLICY
        self.source_blocks = [fixtures.p('原实施例文本'), fixtures.p('下一业务步骤保留原条件。')]
        self.extra_parts = {}
        self.original_relationships = []
        self.section = '<w:sectPr/>'
        self.write()

    def tearDown(self):
        self.f.tearDown()

    def parts(self, path=None):
        with zipfile.ZipFile(path or self.f.word) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def save(self, parts, path=None):
        with zipfile.ZipFile(path or self.f.word, 'w') as archive:
            for name, value in parts.items():
                archive.writestr(name, value)

    def write(self):
        original = {'word/document.xml': fixtures.doc(''.join(self.source_blocks)).replace('<w:sectPr/>', self.section),
                    **self.extra_parts}
        if self.original_relationships:
            original['word/_rels/document.xml.rels'] = (
                f'<Relationships xmlns="{REL}">' + ''.join(self.original_relationships) + '</Relationships>')
        self.save(original, self.f.source)
        self.f.run['source_docx_sha256'] = digest(self.f.source)
        write_json(self.f.work / '.product-v2/run.json', self.f.run)
        self.f.make_word(body=self.source_blocks[0]
                         + fixtures.p('请参考图1。当前条件的结果用于后续业务判断。')
                         + fixtures.p('请参考图2。对象状态与同一条件保持一致。')
                         + ''.join(self.source_blocks[1:])
                         + ''.join(self.image_block(f) + fixtures.p(f['caption']) for f in self.f.figures))
        current = self.parts()
        current.update(self.extra_parts)
        current['word/document.xml'] = current['word/document.xml'].replace(b'<w:sectPr/>', self.section.encode())
        if self.original_relationships:
            current['word/_rels/document.xml.rels'] = current['word/_rels/document.xml.rels'].replace(
                b'</Relationships>', ''.join(self.original_relationships).encode() + b'</Relationships>')
        self.save(current)

    @staticmethod
    def image_block(figure):
        return ('<w:p><w:r><w:drawing>'
                f'<a:blip r:embed="rId{figure["figure_id"]}"/>'
                '</w:drawing></w:r></w:p>')

    def snapshot(self):
        return chart_snapshot(self.f.work, self.f.word, self.f.run)

    def original_vml(self):
        self.source_blocks.insert(1, '<w:p><w:r>' + vml() + '</w:r></w:p>')
        self.original_relationships = [relationship('rIdOriginal', 'media/original.png')]
        self.extra_parts = {'word/media/original.png': b'original VML image bytes'}
        self.write()

    def mutate_document(self, function):
        parts = self.parts()
        root = ET.fromstring(parts['word/document.xml'])
        function(root.find('{' + fixtures.W + '}body'))
        parts['word/document.xml'] = ET.tostring(root)
        self.save(parts)

    def test_valid_appended_charts_keep_original_body_and_policy_snapshot(self):
        self.assertEqual(self.snapshot()['source_integrity_policy'], SOURCE_INTEGRITY_POLICY)
        self.section = '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:left="1440"/></w:sectPr>'
        self.write()
        self.assertEqual(self.snapshot()['source_integrity_policy'], SOURCE_INTEGRITY_POLICY)

    def test_original_vml_picture_and_custom_template_relationships_are_preserved(self):
        self.original_vml()
        self.original_relationships += [relationship('rIdHyperlink', 'https://example.invalid/original', 'hyperlink', 'External'),
                                        relationship('rIdCustom', '../customXml/item1.xml', 'customXml')]
        self.extra_parts['customXml/item1.xml'] = b'<original>retained</original>'
        self.write()
        self.snapshot()

    def test_original_relationship_attributes_cannot_change_even_with_old_bytes_retained(self):
        self.original_vml()
        original = self.parts()
        for attribute, value in [('Id','rIdOther'), ('Type', fixtures.R+'/hyperlink'),
                                 ('Target','media/replacement.png'), ('TargetMode','External')]:
            with self.subTest(attribute=attribute):
                parts = copy.deepcopy(original)
                rels = ET.fromstring(parts['word/_rels/document.xml.rels'])
                for record in rels:
                    if record.get('Id') == 'rIdOriginal':
                        record.set(attribute, value)
                parts['word/_rels/document.xml.rels'] = ET.tostring(rels)
                parts['word/media/replacement.png'] = b'replacement'
                self.save(parts)
                with self.assertRaisesRegex(ValueError, 'relationship Id/Type/Target/TargetMode'):
                    self.snapshot()

    def test_duplicate_relationship_ids_are_rejected(self):
        self.original_vml()
        parts = self.parts()
        parts['word/_rels/document.xml.rels'] = parts['word/_rels/document.xml.rels'].replace(
            b'</Relationships>', relationship('rIdOriginal', 'media/original.png').encode() + b'</Relationships>')
        self.save(parts)
        with self.assertRaisesRegex(ValueError, 'duplicate Word relationship'):
            self.snapshot()

    def test_original_non_word_resource_target_is_protected(self):
        self.original_relationships = [relationship('rIdCustom', '../customXml/item1.xml', 'customXml')]
        self.extra_parts = {'customXml/item1.xml': b'original resource'}
        self.write()
        parts = self.parts()
        parts['customXml/item1.xml'] = b'changed resource'
        self.save(parts)
        with self.assertRaisesRegex(ValueError, 'relationship resource changed'):
            self.snapshot()

    def test_original_package_root_relationship_target_cannot_change(self):
        self.extra_parts['_rels/.rels'] = (f'<Relationships xmlns="{REL}">'
                                           + relationship('rIdRoot', 'word/document.xml', 'officeDocument')
                                           + '</Relationships>')
        self.write()
        parts = self.parts()
        parts['_rels/.rels'] = parts['_rels/.rels'].replace(b'word/document.xml', b'word/alternate.xml')
        parts['word/alternate.xml'] = fixtures.doc(fixtures.p('Changed displayed document'))
        self.save(parts)
        with self.assertRaisesRegex(ValueError, 'relationship Id/Type/Target/TargetMode'):
            self.snapshot()

    def test_normal_core_edit_timestamp_change_does_not_change_source_content(self):
        self.extra_parts['_rels/.rels'] = (
            f'<Relationships xmlns="{REL}"><Relationship Id="core" Target="docProps/core.xml" '
            'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"/>'
            '</Relationships>')
        self.extra_parts['docProps/core.xml'] = (
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dcterms="http://purl.org/dc/terms/"><dcterms:modified>2026-10-19T00:00:00Z</dcterms:modified>'
            '</cp:coreProperties>')
        self.write()
        parts = self.parts()
        parts['docProps/core.xml'] = parts['docProps/core.xml'].replace(b'2026-10-19', b'2026-10-20')
        self.save(parts)
        self.snapshot()

    def test_final_section_dimensions_removal_and_duplicate_are_rejected(self):
        original = self.parts()
        mutations = [lambda body: body[-1].append(ET.Element('{'+fixtures.W+'}pgSz', {'{'+fixtures.W+'}w':'23812'})),
                     lambda body: body.remove(body[-1]),
                     lambda body: body.append(ET.Element('{'+fixtures.W+'}sectPr')),
                     lambda body: body.append(ET.Element('{'+fixtures.W+'}p'))]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.save(original)
                self.mutate_document(mutation)
                with self.assertRaisesRegex(ValueError, 'final section properties'):
                    self.snapshot()

    def test_original_in_body_section_is_retained_but_an_added_section_is_rejected(self):
        self.source_blocks[0] = ('<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906"/></w:sectPr></w:pPr>'
                                 '<w:r><w:t>原实施例文本</w:t></w:r></w:p>')
        self.write()
        self.snapshot()
        def add_section(body):
            properties = ET.Element('{'+fixtures.W+'}pPr')
            section = ET.SubElement(properties, '{'+fixtures.W+'}sectPr')
            ET.SubElement(section, '{'+fixtures.W+'}pgSz', {'{'+fixtures.W+'}w':'23812'})
            body[1].insert(0, properties)
        self.mutate_document(add_section)
        with self.assertRaisesRegex(ValueError, 'no added section breaks'):
            self.snapshot()

    def test_unregistered_drawing_before_or_after_registered_charts_is_rejected(self):
        original = self.parts()
        for position in (3, 8):
            with self.subTest(position=position):
                self.save(original)
                self.mutate_document(lambda body: body.insert(position, ET.fromstring(
                    f'<w:p xmlns:w="{fixtures.W}" xmlns:a="{fixtures.A}" xmlns:r="{fixtures.R}">'
                    '<w:r><w:drawing><a:blip r:embed="rId1"/></w:drawing></w:r></w:p>')))
                with self.assertRaisesRegex(ValueError, 'Every added graphical object'):
                    self.snapshot()

    def test_unregistered_vml_in_body_or_caption_is_rejected(self):
        original = self.parts()
        for target in ('body','caption'):
            with self.subTest(target=target):
                self.save(original)
                def add(body):
                    picture = ET.fromstring(f'<w:p xmlns:w="{fixtures.W}" xmlns:r="{fixtures.R}"><w:r>'
                                            + vml('rId1') + '</w:r></w:p>')
                    if target == 'body':
                        body.insert(3, picture)
                    else:
                        body[5].append(picture[0])
                self.mutate_document(add)
                with self.assertRaisesRegex(ValueError, 'Every added graphical object'):
                    self.snapshot()

    def test_same_paragraph_extra_drawing_or_vml_is_rejected(self):
        original = self.parts()
        for tag in ('drawing','vml'):
            with self.subTest(tag=tag):
                self.save(original)
                def add(body):
                    paragraph = body[4]
                    if tag == 'drawing':
                        paragraph[0].append(copy.deepcopy(paragraph[0][0]))
                    else:
                        extra = ET.fromstring(f'<w:p xmlns:w="{fixtures.W}" xmlns:r="{fixtures.R}"><w:r>'
                                              + vml('rId1') + '</w:r></w:p>')
                        paragraph.append(extra[0])
                self.mutate_document(add)
                with self.assertRaisesRegex(ValueError, 'exactly one graphical object'):
                    self.snapshot()

    def test_same_drawing_multiple_images_or_grouped_shape_are_rejected(self):
        original = self.parts()
        for mutation in ('second_png','grouped_shape'):
            with self.subTest(mutation=mutation):
                self.save(original)
                def add(body):
                    drawing = body[4][0][0]
                    if mutation == 'second_png':
                        drawing.append(copy.deepcopy(drawing[0]))
                    else:
                        drawing.append(ET.Element('{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}wsp'))
                self.mutate_document(add)
                with self.assertRaisesRegex(ValueError, 'exactly one embedded PNG|additional or grouped'):
                    self.snapshot()

    def test_equivalent_drawingml_vml_fallback_is_one_registered_image(self):
        def alternate(body):
            paragraph = body[4]
            drawing = paragraph[0][0]
            paragraph[0].remove(drawing)
            representation = ET.SubElement(paragraph[0], '{'+MC+'}AlternateContent')
            ET.SubElement(representation, '{'+MC+'}Choice', {'Requires':'a'}).append(drawing)
            fallback = ET.SubElement(representation, '{'+MC+'}Fallback')
            image = ET.fromstring(f'<w:p xmlns:w="{fixtures.W}" xmlns:r="{fixtures.R}"><w:r>'
                                  + vml('rId1') + '</w:r></w:p>')
            fallback.append(image[0][0])
        self.mutate_document(alternate)
        self.snapshot()
        original = self.parts()
        self.mutate_document(lambda body: body[4].find('.//{'+V+'}imagedata').set('{'+fixtures.R+'}id','rId2'))
        with self.assertRaisesRegex(ValueError, 'differs from its checked PNG'):
            self.snapshot()
        self.save(original)
        def duplicate_fallback(body):
            fallback = body[4].find('.//{'+MC+'}Fallback')
            fallback.append(copy.deepcopy(fallback[0]))
        self.mutate_document(duplicate_fallback)
        with self.assertRaisesRegex(ValueError, 'same single image'):
            self.snapshot()

    def test_none_legacy_policy_keeps_original_snapshot_shape_and_gate(self):
        self.original_vml()
        self.f.run.pop('source_integrity_policy')
        parts = self.parts()
        parts['word/_rels/document.xml.rels'] = parts['word/_rels/document.xml.rels'].replace(
            b'Target="media/original.png"', b'Target="media/replacement.png"')
        parts['word/media/replacement.png'] = b'legacy unprotected bytes'
        self.save(parts)
        self.assertNotIn('source_integrity_policy', self.snapshot())

    def test_unknown_policy_fails_closed(self):
        self.f.run['source_integrity_policy'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'Unknown source integrity policy'):
            self.snapshot()


if __name__ == '__main__':
    unittest.main()
