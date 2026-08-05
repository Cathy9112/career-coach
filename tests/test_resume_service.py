import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import resume_service


def completion(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


class ResumeServicePromptTest(unittest.TestCase):
    def test_optimize_prompt_forbids_invented_metrics(self):
        with patch.object(
            resume_service,
            "chat_completion",
            return_value=completion("优化建议"),
        ) as chat_completion:
            result = resume_service.optimize_resume(
                "参与后端接口开发",
                "Python开发工程师",
                "要求三年经验，熟悉Redis",
            )

        prompt = chat_completion.call_args.args[0][0]["content"]
        self.assertEqual(result, "优化建议")
        self.assertIn("只有【用户简历】中明确出现的内容", prompt)
        self.assertIn("岗位职责", prompt)
        self.assertIn("绝不能转写成候选人已经具备", prompt)
        self.assertIn("[待补充：具体可验证数据]", prompt)
        self.assertIn("若不足3处，不得为凑数编造经历", prompt)
        self.assertIn("要求三年经验，熟悉Redis", prompt)
        self.assertIn("参与后端接口开发", prompt)

    def test_full_resume_prompt_uses_placeholders_for_missing_facts(self):
        with patch.object(
            resume_service,
            "chat_completion",
            return_value=completion("完整简历"),
        ) as chat_completion:
            result = resume_service.generate_optimized_resume(
                "姓名：张三\n技能：Python",
                "后端开发工程师",
            )

        prompt = chat_completion.call_args.args[0][0]["content"]
        self.assertEqual(result, "完整简历")
        self.assertIn("禁止新增、猜测、推断或合理化", prompt)
        self.assertIn("[待补充：该模块的真实信息]", prompt)
        self.assertIn("用户明确写了“无”时才能写“无”", prompt)
        self.assertIn("输出前必须逐句进行事实核对", prompt)
        self.assertIn("未提供岗位职责", prompt)
        self.assertIn("姓名：张三", prompt)


if __name__ == "__main__":
    unittest.main()
