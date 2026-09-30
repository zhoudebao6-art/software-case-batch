"""New chart preferences must reach future stages without reopening old batches."""
import json
import unittest
from pathlib import Path

from test_caseflow import flow


class ChartPolicyScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = {"_prompts": Path(__file__).resolve().parents[1] / "prompts"}
        cls.scope = flow.read_json(flow.PROFESSIONAL_CHART_SCOPE)
        cls.rule = flow.PROFESSIONAL_CHART_SCOPE.with_name("chart-professional.md").read_text(encoding="utf-8")
        cls.stages = ("build", "repair_visual", "repair_video", "repair_final",
                      "video", "review_visual", "review_video", "review_final")

    def test_future_batch_receives_rule_in_build_repair_and_review(self):
        context = {"batch_id": "future-batch-fixture"}
        for stage in self.stages:
            with self.subTest(stage=stage):
                text = flow.prompt(self.cfg, stage, context)
                self.assertEqual(text.count(self.rule), 1)
                injected = json.loads(text.split("RUNNER_CONTEXT_JSON:\n", 1)[1])
                self.assertEqual(injected["chart_policy_addendum"], self.scope["version"])
        self.assertNotIn("chart_policy_addendum", context)

    def test_existing_batches_do_not_receive_new_acceptance_requirement(self):
        for batch_id in self.scope["existing_batch_ids"]:
            for stage in self.stages:
                with self.subTest(batch_id=batch_id, stage=stage):
                    text = flow.prompt(self.cfg, stage, {"batch_id": batch_id})
                    self.assertNotIn(self.rule, text)
                    injected = json.loads(text.split("RUNNER_CONTEXT_JSON:\n", 1)[1])
                    self.assertNotIn("chart_policy_addendum", injected)

    def test_unknown_batch_identity_does_not_retroactively_apply_policy(self):
        text = flow.prompt(self.cfg, "repair_final", {})
        self.assertNotIn(self.rule, text)
        self.assertEqual(flow.CHART_RULES_VERSION, "2026-09-24")


class LegendPolicyScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg={'_prompts':Path(__file__).resolve().parents[1]/'prompts'}
        cls.scope=flow.read_json(flow.LEGEND_CHART_SCOPE)
        cls.rule=flow.LEGEND_CHART_SCOPE.with_name('chart-legend.md').read_text(encoding='utf-8')
        cls.stages=('build','repair_visual','repair_video','repair_final','video',
                    'review_visual','review_video','review_final','prepare_video')

    def test_future_batch_injects_legend_rule_into_construction_repair_and_review(self):
        context={'batch_id':'future-legend-fixture'}
        for stage in self.stages:
            with self.subTest(stage=stage):
                prompt=flow.prompt(self.cfg,stage,context)
                self.assertEqual(prompt.count(self.rule),1)
                injected=json.loads(prompt.split('RUNNER_CONTEXT_JSON:\n',1)[1])
                self.assertEqual(injected['legend_policy_addendum'],self.scope['version'])
        self.assertNotIn('legend_policy_addendum',context)

    def test_current_batches_do_not_receive_new_legend_requirement(self):
        for batch_id in self.scope['existing_batch_ids']:
            for stage in self.stages:
                with self.subTest(batch_id=batch_id,stage=stage):
                    prompt=flow.prompt(self.cfg,stage,{'batch_id':batch_id})
                    self.assertNotIn(self.rule,prompt)
                    injected=json.loads(prompt.split('RUNNER_CONTEXT_JSON:\n',1)[1])
                    self.assertNotIn('legend_policy_addendum',injected)
        # The newer in-progress batches keep their already applicable professional chart rule.
        for batch_id in set(self.scope['existing_batch_ids'])-set(flow.read_json(flow.PROFESSIONAL_CHART_SCOPE)['existing_batch_ids']):
            self.assertIn('chart_policy_addendum',flow.prompt(self.cfg,'review_final',{'batch_id':batch_id}))

    def test_unknown_identity_does_not_guess_new_policy_or_change_base_version(self):
        self.assertNotIn(self.rule,flow.prompt(self.cfg,'repair_final',{}))
        self.assertEqual(flow.CHART_RULES_VERSION,'2026-09-24')


if __name__ == "__main__":
    unittest.main()
