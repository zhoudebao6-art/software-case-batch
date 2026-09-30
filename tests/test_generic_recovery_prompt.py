"""Recovery prompts must remain case-specific instead of carrying one old case."""
import unittest
from pathlib import Path


class GenericRecoveryPromptTests(unittest.TestCase):
    def test_common_recovery_path_has_no_historical_case_literals(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts' / 'caseflow.py').read_text(encoding='utf-8')
        for literal in ('18028', '18052', '18053', 'phm-source-v9', 'verify_phm_v9.py',
                        'freeze_phm_current.py', 'recapture_video_routes_v9.py'):
            self.assertNotIn(literal, source)

    def test_recovery_prompt_requires_current_service_identity(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts' / 'caseflow.py').read_text(encoding='utf-8')
        self.assertIn('capture-plan.json', source)
        self.assertIn('案件ID、工作区、端口、PID、创建时间、命令行和版本', source)
        self.assertIn('禁止重复被拒绝启动', source)


if __name__ == '__main__':
    unittest.main()
