"""Prompt/facts integration only, not a claim that a UI is visually accepted."""
import unittest
from pathlib import Path
import test_product_flow as flow
import test_review_navigation as navigation
from common import read_json, write_json
from evidence_index import review_input
from proflow import prepare


class CaseNativePromptTests(unittest.TestCase):
    setUp = flow.FlowTests.setUp
    tearDown = flow.FlowTests.tearDown

    def test_new_prompt_contains_design_decisions_and_live_reference_paths(self):
        text=(self.work/'.product-v2/深化命令词.txt').read_text(encoding='utf-8')
        self.assertIn('用户判断/操作',text)
        self.assertIn('不把本案功能做成同构页面',text)
        self.assertIn('本案若为桌面Web',text)
        self.assertIn('没有对照直接继续',text)
        self.assertIn('谁选择哪个对象→哪些信息必须同屏→用户判断/操作→哪个结果或状态改变',text)
        self.assertIn('不按标题关键词分配模板',text)
        self.assertIn('先实现该场景的真实纵向切片',text)
        self.assertIn('pages.screenshot和workflow/assertion',text)
        self.assertIn('不因普通侧栏/表格相似而返工',text)
        self.assertIn('每段常驻文字应帮助选择对象、输入、判断结果或恢复操作',text)
        self.assertIn('不全局删介绍段',text)
        self.assertIn('不缩减Word图表解释',text)
        self.assertIn('阻断原因、风险、数据性质和结果适用限制',text)
        self.assertIn('不新增表单、审批或审美审核轮次',text)
        for name in ('frontend-design-playbook.md','frontend-motion.md'):
            path=Path(__file__).resolve().parents[1]/'references'/name
            self.assertTrue(path.is_file());self.assertIn(str(path),text)

    def test_existing_run_and_prompt_not_rewritten_by_prepare(self):
        prompt=self.work/'.product-v2/深化命令词.txt'
        prompt.write_bytes(b'Frozen older instructions')
        run=self.work/'.product-v2/run.json';before=run.read_bytes()
        prepare(self.work,self.out,'设备运行管理',self.source)
        self.assertEqual(run.read_bytes(),before)
        self.assertEqual(prompt.read_bytes(),b'Frozen older instructions')

    def test_reference_is_task_choices_not_required_upstream_install(self):
        root=Path(__file__).resolve().parents[1]
        guide=(root/'references/frontend-design-playbook.md').read_text(encoding='utf-8')
        for action in ('检视图像','安排资源','定位设备','查询空间','比较试样','审核记录'):
            self.assertIn(action,guide)
        self.assertIn('表外更合适的方式优先',guide)
        self.assertIn('不新增字段、单独报告或截图数量指标',guide)
        self.assertIn('工作本来就是表格时允许表格为主体',guide)
        refs=(root/'references/frontend-reference-map.md').read_text(encoding='utf-8')
        self.assertIn('不把五个项目串成五道工序',refs)
        self.assertIn('没有安装或运行这些产品',refs)


class CaseNativeReviewTests(unittest.TestCase):
    setUp = navigation.NavigationTests.setUp
    prepare = navigation.NavigationTests.prepare

    def test_existing_review_facts_carry_visual_task_check_without_new_evidence(self):
        index=self.prepare();runpath=self.control/'run.json';run=read_json(runpath)
        run['web_experience_policy']='case-workflow-v1';write_json(runpath,run)
        spec=read_json(index)
        spec['review_scope']={'web':{'policy':'case-workflow-v1','page_ids':['core'],
            'workflow_ids':['inspect'],'evidence_hashes':{}}}
        write_json(index,spec);before=index.read_bytes()
        dest=self.control/'ui-facts.json';review_input(self.work,index,dest,compact=True)
        facts=read_json(dest);instruction=facts['web_review_requirements']['instruction']
        self.assertIn('page/region',instruction)
        self.assertIn('cosmetic preferences remain nonblocking',instruction)
        self.assertIn('object -> simultaneous information -> action -> observable result',instruction)
        self.assertIn('pages.screenshot and workflow/assertion',instruction)
        self.assertIn('a familiar layout serving the same work is valid',instruction)
        self.assertIn('no extra design review stage',instruction)
        self.assertIn('persistent text should help identify an object',instruction)
        self.assertIn('decision-critical conditions, units, data nature',instruction)
        self.assertIn('Extra prose alone is nonblocking',instruction)
        self.assertIn('do not reduce Word figure explanations',instruction)
        self.assertEqual(set(facts['web_review_requirements']),
                         {'policy','page_ids','workflow_ids','instruction'})
        self.assertEqual(facts['web_review_requirements']['page_ids'],['core'])
        self.assertEqual(facts['web_review_requirements']['workflow_ids'],['inspect'])
        self.assertEqual(index.read_bytes(),before)
        self.assertFalse(facts['visual_navigation']['coverage_claim'])
        self.assertNotIn('decision',facts)

    def test_no_web_policy_does_not_introduce_ui_review(self):
        index=self.prepare();runpath=self.control/'run.json';run=read_json(runpath)
        run.pop('web_experience_policy',None);write_json(runpath,run)
        before=index.read_bytes();dest=self.control/'no-ui-facts.json'
        review_input(self.work,index,dest,compact=True)
        self.assertNotIn('web_review_requirements',read_json(dest))
        self.assertEqual(index.read_bytes(),before)


if __name__=='__main__':unittest.main()
