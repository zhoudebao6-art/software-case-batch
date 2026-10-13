"""Build-time figure coverage gates preserve frozen older runs."""
import copy
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from contracts import chart_records,chart_policy,check_word_chart_width,NS


def figure(number,role='professional_analysis',palette='color'):
    sha=f'{number:064x}'
    return {'figure_id':number,'sha256':sha,'caption':f'图{number} 约束分布',
            'question':'边界条件如何改变可行区域','data_source':'当前实施例的约束求解',
            'chart_type':'feasibility','labels':['负荷','余量'],
            'analysis_role':role,'palette':palette,
            'build_selfcheck':{'geometry_status':'pass','collisions':[],
                'png_sha256':sha,'final_width_mm':155,
                'visual_review':{'inspected':True,'png_sha256':sha,'final_width_mm':155,
                                 'evidence':'已查看最终宽度，数值与边界及阶梯转折分离'}}}


class BuildPolicyTests(unittest.TestCase):
    def setUp(self):
        self.run={'chart_policy':'analytical-v2'}
        self.spec={'figures':[figure(1,'baseline_result','monochrome')]+[figure(i) for i in (2,3,4)]}

    def test_mix_is_coverage_not_upper_cap(self):
        self.assertEqual(len(chart_records(self.spec,self.run)),4)
        self.spec['figures'] += [figure(i) for i in range(5,10)]
        self.assertEqual(len(chart_records(self.spec,self.run)),9)

    def test_missing_monochrome_insufficient_count_and_equal_mix_rejected(self):
        for change in ('all_color','too_few','equal_mix'):
            spec=copy.deepcopy(self.spec)
            if change=='all_color':spec['figures'][0]['palette']='color'
            if change=='too_few':spec['figures'].pop()
            if change=='equal_mix':spec['figures'][1].update(analysis_role='baseline_result',palette='monochrome')
            with self.subTest(change=change),self.assertRaises(ValueError):chart_records(spec,self.run)

    def test_known_collision_and_stale_visual_hash_cannot_pass(self):
        for change in ('collision','stale','unseen','size'):
            spec=copy.deepcopy(self.spec);check=spec['figures'][1]['build_selfcheck']
            if change=='collision':check['collisions']=[{'kind':'step','label':'450'}]
            if change=='stale':check['visual_review']['png_sha256']='0'*64
            if change=='unseen':check['visual_review']['inspected']=False
            if change=='size':check['visual_review']['final_width_mm']=100
            with self.subTest(change=change),self.assertRaises(ValueError):chart_records(spec,self.run)

    def test_verified_existing_statistical_result_can_supply_baseline(self):
        baseline=self.spec['figures'].pop(0)
        self.spec['retained_results']=[{'figure_id':1,'sha256':baseline['sha256'],
            'analysis_role':'baseline_result','palette':'monochrome','source_member':'word/media/image1.png',
            'result_reason':'原件含相同工况的统计结果，无需重绘',
            'visual_review':{'inspected':True,'png_sha256':baseline['sha256'],'evidence':'原图是结果曲线，非流程框图'}}]
        self.assertEqual(len(chart_records(self.spec,self.run)),3)
        self.spec['retained_results'][0]['analysis_role']='workflow'
        with self.assertRaises(ValueError):chart_records(self.spec,self.run)

    def test_frozen_v1_and_absent_policy_keep_original_rules(self):
        one={'figures':[{'figure_id':1,'question':'原合同','data_source':'原输入',
                        'chart_type':'line','labels':['数值'],'caption':'图1 原结果'}]}
        self.assertEqual(len(chart_records(one,{'chart_policy':'analytical-v1'})),1)
        with self.assertRaises(ValueError):chart_records(one,{})
        with self.assertRaises(ValueError):chart_policy({'chart_policy':'unknown'})

    def test_word_resize_invalidates_construction_visual_size(self):
        block=ET.fromstring('<w:p xmlns:w="'+NS['w']+'" xmlns:a="'+NS['a']+'" xmlns:r="'+NS['r']+'" xmlns:wp="'+NS['wp']+'"><w:r><w:drawing><wp:inline><wp:extent cx="5580000" cy="3600000"/><a:blip r:embed="rId1"/></wp:inline></w:drawing></w:r></w:p>')
        relations={'rId1':'media/a.png'};media={'word/media/a.png':'sha'}
        check_word_chart_width(block,relations,media,'sha',155)
        with self.assertRaises(ValueError):check_word_chart_width(block,relations,media,'sha',120)
        block.find('.//wp:extent',NS).set('cx','invalid')
        with self.assertRaises(ValueError):check_word_chart_width(block,relations,media,'sha',155)


if __name__=='__main__':unittest.main()
