"""Source numbering and preservation fixtures, not visual or domain validation."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from common import digest, read_json, write_json
from contracts import chart_snapshot
from proflow import prepare
from source_intake import source_figure_numbers

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'


def p(text):
    return f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>'


def document(body):
    return f'<w:document xmlns:w="{W}" xmlns:a="{A}" xmlns:r="{R}" xmlns:m="{M}"><w:body>{body}<w:sectPr/></w:body></w:document>'


def drawing(rid):
    return f'<w:p><w:r><w:drawing><a:blip r:embed="{rid}"/></w:drawing></w:r></w:p>'


def relationships(records):
    return '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(
        f'<Relationship Id="{rid}" Target="media/{name}"/>' for rid, name in records) + '</Relationships>'


class SourceIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.work = self.root/'work'
        self.work.mkdir()
        self.source = self.work/'新技术原件.docx'
        self.output = self.root/'out'
        self.old_media = {f'original{n}.png': b'\x89PNG\r\n\x1a\noriginal'+bytes([n]) for n in (1, 2, 3)}
        self.old_rels = [(f'old{n}', f'original{n}.png') for n in (1, 2, 3)]
        self.original_body = p('当前实施例') + '<w:p><m:oMath><m:r><m:t>δ</m:t></m:r></m:oMath></w:p>'
        self.original_body += ''.join(drawing(f'old{n}')+p(f'图{n} 原流程图') for n in (1, 2, 3))
        self.source_package(self.original_body, self.old_media, self.old_rels)
        self.run = prepare(self.work, self.output, '设备联动诊断', self.source)
        # Preserve r9 numbering/source-protection fixtures independently of r10 mix checks.
        self.run['chart_policy']='analytical-v1'
        self.run.pop('recording_policy_version',None)
        self.run.pop('data_policy_version',None)
        write_json(self.work/'.product-v2/run.json',self.run)
        self.word = self.output/self.source.name

    def tearDown(self):
        self.temp.cleanup()

    def source_package(self, body, media=None, rels=None):
        with zipfile.ZipFile(self.source, 'w') as package:
            package.writestr('word/document.xml', document(body))
            package.writestr('word/_rels/document.xml.rels', relationships(rels or []))
            for name, payload in (media or {}).items():
                package.writestr('word/media/'+name, payload)

    def candidate(self, numbers, reuse_original=False, body=None):
        figures = []
        media = dict(self.old_media)
        rels = list(self.old_rels)
        result_body = self.original_body if body is None else body
        split = result_body.index('</w:p>') + len('</w:p>')
        result_body = (result_body[:split] + ''.join(p(f'请参考图{n}。本案计算结果。') for n in numbers)
                       + result_body[split:])
        for n in numbers:
            payload = self.old_media[f'original{numbers.index(n)+1}.png'] if reuse_original else b'\x89PNG\r\n\x1a\nresult'+bytes([n])
            png = self.work/f'result{n}.png'
            png.write_bytes(payload)
            figure = {'figure_id': n, 'png': png.name, 'sha256': digest(png),
                      'caption': f'图{n} 当前计算结果', 'title_policy': 'none',
                      'explanation_after_source_block': 0,
                      'question': '本图回答独立边界问题', 'data_source': '原实施例与当前计算记录',
                      'chart_type': 'heatmap', 'labels': ['时间', '工况', '计算量']}
            figures.append(figure)
            rels.append((f'new{n}', png.name))
            media[png.name] = payload
            result_body += drawing(f'new{n}')+p(figure['caption'])
        write_json(self.work/'.product-v2/chart-manifest.json', {'figures': figures})
        with zipfile.ZipFile(self.word, 'w') as package:
            package.writestr('word/document.xml', document(result_body))
            package.writestr('word/_rels/document.xml.rels', relationships(rels))
            for name, payload in media.items():
                package.writestr('word/media/'+name, payload)

    def test_analytical_single_and_more_than_six_are_valid(self):
        for numbers in ([4], list(range(4,12))):
            with self.subTest(numbers=numbers):
                self.candidate(numbers)
                snapshot=chart_snapshot(self.work,self.word,self.run)
                self.assertEqual(len(snapshot['figures']),len(numbers))
                self.assertEqual(snapshot['chart_policy'],'analytical-v1')
    def test_empty_chart_list_is_rejected_by_both_policies(self):
        self.candidate([])
        for legacy in (False,True):
            run=dict(self.run)
            if legacy:run.pop('chart_policy')
            with self.subTest(legacy=legacy),self.assertRaisesRegex(ValueError,'At least one'):
                chart_snapshot(self.work,self.word,run)
    def test_legacy_count_limits_stay_frozen(self):
        run=dict(self.run);run.pop('chart_policy')
        for numbers in ([4],list(range(4,11))):
            self.candidate(numbers)
            with self.assertRaisesRegex(ValueError,'Two to six'):chart_snapshot(self.work,self.word,run)
        self.candidate([4,5]);snapshot=chart_snapshot(self.work,self.word,run)
        self.assertNotIn('chart_policy',snapshot)
    def test_unknown_or_null_policy_cannot_relax_count_gate(self):
        self.candidate([4])
        for value in ('unknown',None,''):
            run=dict(self.run);run['chart_policy']=value
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'Unknown chart policy'):
                chart_snapshot(self.work,self.word,run)
    def test_added_caption_and_actual_labels_cannot_contain_schematic(self):
        self.candidate([4]);path=self.work/'.product-v2/chart-manifest.json';original=read_json(path)
        for field,value in [('caption','图4 当前计算示意'),('labels',['工况示意']),('labels',['示意'])]:
            spec=__import__('copy').deepcopy(original);spec['figures'][0][field]=value;write_json(path,spec)
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'must not contain 示意'):
                chart_snapshot(self.work,self.word,self.run)
    def test_analytical_manifest_requires_question_source_type_and_actual_labels(self):
        self.candidate([4]);path=self.work/'.product-v2/chart-manifest.json';original=read_json(path)
        for field,value in [('question',' '),('data_source',None),('chart_type',True),('labels',[]),('labels',[' ']),('labels','axis')]:
            spec=__import__('copy').deepcopy(original);spec['figures'][0][field]=value;write_json(path,spec)
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'Analytical chart requires'):
                chart_snapshot(self.work,self.word,self.run)
    def test_source_schematic_text_and_caption_are_preserved(self):
        self.original_body=self.original_body.replace('当前实施例','当前示意实施例').replace('原流程图','原流程示意图')
        self.source_package(self.original_body,self.old_media,self.old_rels)
        self.run['source_docx_sha256']=digest(self.source);before=digest(self.source)
        self.candidate([4]);self.assertEqual(len(chart_snapshot(self.work,self.word,self.run)['figures']),1)
        self.assertEqual(digest(self.source),before)
    def test_legacy_manifest_does_not_require_analytical_fields_or_new_wording(self):
        self.candidate([4,5]);path=self.work/'.product-v2/chart-manifest.json';spec=read_json(path)
        for figure in spec['figures']:
            for key in ('question','data_source','chart_type','labels'):figure.pop(key)
        write_json(path,spec);run=dict(self.run);run.pop('chart_policy')
        self.assertEqual(len(chart_snapshot(self.work,self.word,run)['figures']),2)
    def test_new_source_without_result_charts_accepts_four_and_five(self):
        before = digest(self.source)
        self.candidate([4, 5])
        snapshot = chart_snapshot(self.work, self.word, self.run)
        self.assertEqual(set(snapshot['figures']), {'4', '5'})
        self.assertEqual(digest(self.source), before)
        with zipfile.ZipFile(self.source) as original, zipfile.ZipFile(self.word) as final:
            for name in self.old_media:
                self.assertEqual(original.read('word/media/'+name), final.read('word/media/'+name))

    def test_original_figure_number_collision_is_rejected(self):
        self.candidate([1, 2])
        with self.assertRaisesRegex(ValueError, 'source figure numbers'):
            chart_snapshot(self.work, self.word, self.run)

    def test_gap_after_source_or_between_results_is_rejected(self):
        for numbers in ([5, 6], [4, 6]):
            with self.subTest(numbers=numbers):
                self.candidate(numbers)
                with self.assertRaisesRegex(ValueError, 'sequentially'):
                    chart_snapshot(self.work, self.word, self.run)

    def test_original_flowchart_cannot_be_counted_as_new_result(self):
        self.candidate([4, 5], reuse_original=True)
        with self.assertRaisesRegex(ValueError, 'cannot reuse original embedded images'):
            chart_snapshot(self.work, self.word, self.run)

    def test_current_source_omml_cannot_be_changed(self):
        self.candidate([4, 5], body=self.original_body.replace('δ', 'x'))
        with self.assertRaisesRegex(ValueError, 'body blocks'):
            chart_snapshot(self.work, self.word, self.run)

    def test_fullwidth_subfigure_and_split_runs_reserve_main_numbers(self):
        body = p('请参考图１(a)及图3(b)。')
        body += '<w:p><w:r><w:t>图</w:t></w:r><w:r><w:t> ２</w:t></w:r><w:r><w:t> 流程图</w:t></w:r></w:p>'
        self.source_package(body)
        self.assertEqual(source_figure_numbers(self.source), [1, 2, 3])

    def test_reference_without_media_still_reserves_number(self):
        self.source_package(p('请参考图9，图像需人工核对。'))
        self.assertEqual(source_figure_numbers(self.source), [9])

    def test_no_source_figures_starts_at_one(self):
        self.source_package(p('无原图的技术实施例'))
        self.run['source_docx_sha256'] = digest(self.source)
        self.original_body = p('无原图的技术实施例')
        self.old_media, self.old_rels = {}, []
        self.candidate([1, 2])
        self.assertEqual(set(chart_snapshot(self.work, self.word, self.run)['figures']), {'1', '2'})

    def test_historical_contract_is_not_retroactively_renumbered(self):
        self.candidate([4, 6])
        historical_run = dict(self.run)
        historical_run.pop('chart_numbering_policy')
        before = hashlib.sha256(str(historical_run).encode()).hexdigest()
        self.assertEqual(set(chart_snapshot(self.work, self.word, historical_run)['figures']), {'4', '6'})
        self.assertEqual(hashlib.sha256(str(historical_run).encode()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
