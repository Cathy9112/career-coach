import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.interview_service import InterviewSession


def completion(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def stream_chunk(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


class InterviewServiceTest(unittest.TestCase):
    def session(self):
        return InterviewSession(
            resume_text="Python后端项目经验",
            target_position="后端开发工程师",
            difficulty="中级",
            user_id=7,
            job_description="熟悉FastAPI和Redis",
        )

    def test_answered_question_is_recorded_separately(self):
        session = self.session()
        session.chat_list.append({"role": "assistant", "content": "请说明Redis缓存穿透的解决方案。"})

        with (
            patch.object(session, "_get_knowledge", return_value=""),
            patch(
                "services.interview_service.chat_completion",
                return_value=[stream_chunk("下一题")],
            ),
        ):
            reply = "".join(session.stream_next_question("可以使用布隆过滤器和空值缓存。"))

        self.assertEqual(reply, "下一题")
        self.assertEqual(
            session.qa_history,
            [{
                "question": "请说明Redis缓存穿透的解决方案。",
                "answer": "可以使用布隆过滤器和空值缓存。",
            }],
        )

    def test_report_scores_are_normalized_and_cached(self):
        session = self.session()
        session.qa_history = [{"question": "什么是事务？", "answer": "事务具有ACID特性。"}]
        payload = {
            "overall_score": 105,
            "dimension_scores": {
                "专业知识": 88,
                "项目实战": 70,
                "问题分析": 82,
                "表达沟通": 76,
                "岗位匹配": -4,
            },
            "summary": "基础知识较扎实。",
            "strengths": ["能够说明ACID"],
            "improvements": ["补充实际案例"],
            "question_feedback": [{
                "question": "模型返回的问题不应覆盖真实问题",
                "score": 86,
                "feedback": "概念正确，但缺少例子。",
                "better_answer": "按定义、特性、案例组织回答。",
            }],
            "next_steps": ["复习事务隔离级别"],
        }

        with patch(
            "services.interview_service.chat_completion",
            return_value=completion(json.dumps(payload, ensure_ascii=False)),
        ) as chat_completion:
            first_report = session.generate_report()
            second_report = session.generate_report()

        self.assertIs(first_report, second_report)
        self.assertEqual(chat_completion.call_count, 1)
        self.assertEqual(first_report["overall_score"], 100)
        self.assertEqual(first_report["dimension_scores"]["岗位匹配"], 0)
        self.assertEqual(first_report["question_feedback"][0]["question"], "什么是事务？")
        self.assertEqual(first_report["question_feedback"][0]["answer"], "事务具有ACID特性。")
        self.assertEqual(first_report["answered_questions"], 1)

    def test_report_requires_at_least_one_answer(self):
        with self.assertRaisesRegex(ValueError, "至少回答一道面试题"):
            self.session().generate_report()


if __name__ == "__main__":
    unittest.main()
