import json
import logging
from threading import Lock

from utils.llm_util import chat_completion, completion_content


logger = logging.getLogger(__name__)

INTERVIEW_SYSTEM_PROMPT = """
你是一名资深专业面试官，负责{target_position}岗位的招聘面试。
你风格严厉务实，眼光毒辣，以岗位真实用人标准为核心判断依据，不会顺着简历泛泛提问，会直击候选人能力与岗位要求的差距。

【核心出题规则（优先级从高到低）】
1. 最高优先级：如果本次对话提供了【官方题库参考内容】，必须严格优先基于题库中的知识点、题目进行提问，不得脱离题库范围自行编造题目。可以对原题进行变形、追问，但核心考点必须来自题库。
2. 所有提问必须紧扣{target_position}岗位的核心职责、必备技能与能力要求，简历仅作为背景参考。
   如果提供了岗位职责，必须优先围绕岗位职责明确列出的职责、技能、经验要求和加分项提问。
3. 正式提问前，先快速评估候选人简历与目标岗位的匹配度：
   - 若简历与岗位匹配度较低，必须先直接点明二者的核心差距，再围绕岗位要求的基础能力、必备知识进行提问
   - 若简历与岗位匹配度较高，则结合简历中的项目经历，深挖与岗位相关的技术细节、落地难点与实战经验
4. 每次只提出1个核心问题，可以附带1个追问方向，禁止一次性抛出多个问题。
5. 问题要有针对性，考察真实落地能力，不要问空泛的概念题。
6. 语气专业严肃，一针见血，不要客套寒暄，不要说场面话。

格式要求：
- 绝对禁止使用 **、-、数字序号等任何Markdown格式符号
- 正常分段表达，用自然的口语化书面语
- 不要分点罗列，用连贯的段落表达

【候选人简历】
{resume_text}
【岗位职责】
{job_description}
"""

REPORT_DIMENSIONS = (
    "专业知识",
    "项目实战",
    "问题分析",
    "表达沟通",
    "岗位匹配",
)

INTERVIEW_REPORT_PROMPT = """
你是一名严格、公正的招聘面试评估专家。请根据候选人的真实问答记录生成面试评分报告。

评分规则：
1. 只能评价实际提供的问答，不得编造候选人没有说过的知识、项目、经历、优点或缺点。
2. 岗位职责和简历只用于判断岗位匹配度，不能作为候选人在面试中已经证明能力的证据。
3. 只评分已经回答的问题，未回答的问题不得计入分数。
4. 每个分数范围为0到100的整数。总分应综合五个维度和逐题表现，不能随意给高分。
5. 逐题反馈必须指出回答中具体做得好的地方、缺失点和可执行的改进方法；参考答案只能给答题方向，不能虚构候选人的经历。
6. 只输出一个合法JSON对象，禁止Markdown代码块、开场白和收尾说明。

必须严格使用以下JSON结构：
{
  "overall_score": 0,
  "dimension_scores": {
    "专业知识": 0,
    "项目实战": 0,
    "问题分析": 0,
    "表达沟通": 0,
    "岗位匹配": 0
  },
  "summary": "总体评价",
  "strengths": ["优势1"],
  "improvements": ["改进项1"],
  "question_feedback": [
    {
      "question": "面试问题",
      "score": 0,
      "feedback": "针对实际回答的评价",
      "better_answer": "更好的作答结构和应覆盖的知识点"
    }
  ],
  "next_steps": ["下一步行动1"]
}
"""


def _score(value) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _text_list(value, limit: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value[:limit] if str(item).strip()]


def _parse_report(content: str, qa_history: list[dict[str, str]]) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("面试报告格式无效")
    try:
        payload = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("面试报告不是合法JSON") from exc

    raw_dimensions = payload.get("dimension_scores", {})
    dimensions = {
        name: _score(raw_dimensions.get(name, 0))
        for name in REPORT_DIMENSIONS
    }
    question_feedback = []
    raw_feedback = payload.get("question_feedback", [])
    if not isinstance(raw_feedback, list):
        raw_feedback = []
    for index, qa in enumerate(qa_history):
        item = raw_feedback[index] if index < len(raw_feedback) and isinstance(raw_feedback[index], dict) else {}
        question_feedback.append({
            "question": qa["question"],
            "answer": qa["answer"],
            "score": _score(item.get("score", 0)),
            "feedback": str(item.get("feedback", "暂未生成有效评价")).strip(),
            "better_answer": str(item.get("better_answer", "请结合问题补充完整答题思路")).strip(),
        })

    return {
        "overall_score": _score(payload.get("overall_score", 0)),
        "dimension_scores": dimensions,
        "summary": str(payload.get("summary", "暂未生成总体评价")).strip(),
        "strengths": _text_list(payload.get("strengths")),
        "improvements": _text_list(payload.get("improvements")),
        "question_feedback": question_feedback,
        "next_steps": _text_list(payload.get("next_steps")),
        "answered_questions": len(qa_history),
    }


class InterviewSession:
    def __init__(self, resume_text: str, target_position: str, user_id: int, job_description: str = ""):
        self._lock = Lock()
        self.chat_list = []
        self.target_position = target_position
        self.resume_text = resume_text
        self.job_description = job_description
        self.user_id = user_id
        self.qa_history = []
        self.report = None
        self.question_focus = {}

        self.system_prompt = INTERVIEW_SYSTEM_PROMPT.format(
            target_position=target_position,
            resume_text=resume_text,
            job_description=job_description or "未提供岗位职责，请按目标岗位通用要求进行面试。",
        )
        self.chat_list.append({"role": "system", "content": self.system_prompt})

    def _get_knowledge(self, query_text: str) -> str:
        """rag检索知识库，返回格式化的官方题库内容；检索不到则返回空字符串"""
        try:
            from utils.vector_util import KNOWLEDGE_COLLECTION_NAME, query_documents
            results = query_documents(
                KNOWLEDGE_COLLECTION_NAME,
                query_text,
                n_results=5,
                where={"user_id": str(self.user_id)},
            )
            if not results:
                return ""
            formatted = "【官方题库参考内容（必须优先使用）】\n"
            for i, item in enumerate(results, 1):
                formatted += f"{i}. {item}\n"
            formatted += "\n请务必优先从上述题库中选择考点出题，不得脱离题库自行编造。"
            return formatted
        except Exception:
            logger.exception("Knowledge base lookup failed")
            return ""

    def stream_next_question(self, user_answer: str = ""):
        """
        流式生成面试官回复，统一处理首个问题与后续追问
        首次调用（对话只有系统提示）自动生成第一个问题
        后续调用根据用户回答生成追问
        """
        with self._lock:
            original_chat = self.chat_list.copy()
            original_qa_history = self.qa_history.copy()
            try:
                # ===== 首次提问：生成第一道面试题 =====
                if len(self.chat_list) == 1:
                    knowledge = self._get_knowledge(f"{self.target_position} {self.job_description[:1000]} 基础面试题 常考考点")
                    user_prompt = "请开始第一个问题"
                    if knowledge:
                        user_prompt = knowledge + "\n" + user_prompt
                    self.chat_list.append({"role": "user", "content": user_prompt})

                # ===== 后续追问：结合回答与题库出题 =====
                else:
                    previous_question = next(
                        (
                            item["content"]
                            for item in reversed(self.chat_list)
                            if item.get("role") == "assistant"
                        ),
                        "",
                    )
                    if previous_question and user_answer.strip():
                        self.qa_history.append({
                            "question": previous_question,
                            "answer": user_answer.strip(),
                        })
                    knowledge_query = f"{self.target_position} {self.job_description[:1000]} {user_answer} 进阶追问 下一个考点"
                    knowledge = self._get_knowledge(knowledge_query)
                    final_input = user_answer
                    if knowledge:
                        final_input = knowledge + "\n【候选人回答】\n" + user_answer + "\n请结合官方题库，继续提出下一个问题或针对回答进行追问。"
                    self.chat_list.append({"role": "user", "content": final_input})

                # 调用大模型流式输出
                response = chat_completion(self.chat_list, stream=True)
                full_reply = ""

                for chunk in response:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if hasattr(delta, "content") and delta.content:
                            text = delta.content
                            # 兜底清洗 Markdown 符号
                            text = text.replace("**", "").replace("###", "").replace("- ", "")
                            full_reply += text
                            yield text

                # 正常结束，保存对话历史
                self.chat_list.append({"role": "assistant", "content": full_reply})

            except BaseException:
                # Roll back both ordinary failures and client disconnects.
                self.chat_list = original_chat
                self.qa_history = original_qa_history
                raise

    def get_current_question(self) -> str | None:
        return next(
            (
                item["content"]
                for item in reversed(self.chat_list)
                if item.get("role") == "assistant" and item.get("content", "").strip()
            ),
            None,
        )

    def get_question_focus(self) -> dict:
        question = self.get_current_question()
        if not question:
            raise ValueError("No current interview question")
        cached = self.question_focus.get(question)
        if cached is not None:
            return cached

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an interview coaching assistant. Based only on the interview question, "
                    "extract the key points being assessed. Do not invent candidate experience or evaluate "
                    "the candidate. Return valid JSON only, without Markdown. Format: "
                    "{\"focus\":[\"point 1\",\"point 2\"],\"answer_tip\":\"answer tip\"}"
                ),
            },
            {"role": "user", "content": question},
        ]
        response = chat_completion(messages, stream=False)
        content = completion_content(response).strip()
        start = content.find("{")
        end = content.rfind("}")
        payload = {}
        if start >= 0 and end > start:
            try:
                payload = json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                payload = {}
        focus = payload.get("focus", [])
        if not isinstance(focus, list):
            focus = []
        focus = [str(item).strip() for item in focus[:3] if str(item).strip()]
        result = {
            "question": question,
            "focus": focus or ["????????", "???????"],
            "answer_tip": str(payload.get("answer_tip", "??????????????????")),
        }
        self.question_focus[question] = result
        return result

    def stream_question_action(self, action: str):
        if action not in {"replace", "regenerate", "skip"}:
            raise ValueError("Unsupported question action")
        with self._lock:
            original_chat = self.chat_list.copy()
            original_qa_history = self.qa_history.copy()
            try:
                current_question = self.get_current_question()
                if not current_question:
                    raise ValueError("No current interview question")
                while self.chat_list and self.chat_list[-1].get("role") == "assistant":
                    self.chat_list.pop()
                instructions = {
                    "replace": (
                        "The candidate requests a different question. Ignore the current question and ask one "
                        "new interview question about a different job-related skill or knowledge point. Do not "
                        "explain this operation and do not treat this instruction as a candidate answer."
                    ),
                    "regenerate": (
                        "The candidate requests a regenerated question. Keep the same core assessment point but "
                        "ask it in a clearer, specific, and different way. Output one question only. Do not "
                        "explain this operation and do not treat this instruction as a candidate answer."
                    ),
                    "skip": (
                        "The candidate requests to skip the current question. Do not record or evaluate it. Ask "
                        "the next question about a different assessment point. Output one question only."
                    ),
                }
                knowledge = self._get_knowledge(
                    f"{self.target_position} {self.job_description[:1000]} {instructions[action]}"
                )
                prompt = instructions[action]
                if knowledge:
                    prompt = knowledge + "\n" + prompt
                self.chat_list.append({"role": "user", "content": prompt})
                response = chat_completion(self.chat_list, stream=True)
                full_reply = ""
                for chunk in response:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if hasattr(delta, "content") and delta.content:
                            text = delta.content.replace("**", "").replace("###", "").replace("- ", "")
                            full_reply += text
                            yield text
                self.chat_list.append({"role": "assistant", "content": full_reply})
            except BaseException:
                self.chat_list = original_chat
                self.qa_history = original_qa_history
                raise

    def generate_report(self) -> dict:
        if self.report is not None:
            return self.report
        if not self.qa_history:
            raise ValueError("请至少回答一道面试题后再生成报告")

        qa_history = self.qa_history[-10:]
        report_context = {
            "target_position": self.target_position,
            "job_description": self.job_description or "未提供岗位职责",
            "resume_text": self.resume_text,
            "qa_history": qa_history,
        }
        messages = [
            {"role": "system", "content": INTERVIEW_REPORT_PROMPT},
            {
                "role": "user",
                "content": json.dumps(report_context, ensure_ascii=False),
            },
        ]
        response = chat_completion(messages, stream=False)
        self.report = _parse_report(completion_content(response), qa_history)
        return self.report
