import logging
from threading import Lock

from utils.llm_util import chat_completion


logger = logging.getLogger(__name__)

INTERVIEW_SYSTEM_PROMPT = """
你是一名资深专业面试官，负责{target_position}岗位的招聘面试，难度等级：{difficulty}。
你风格严厉务实，眼光毒辣，以岗位真实用人标准为核心判断依据，不会顺着简历泛泛提问，会直击候选人能力与岗位要求的差距。

【核心出题规则（优先级从高到低）】
1. 最高优先级：如果本次对话提供了【官方题库参考内容】，必须严格优先基于题库中的知识点、题目进行提问，不得脱离题库范围自行编造题目。可以对原题进行变形、追问，但核心考点必须来自题库。
2. 所有提问必须紧扣{target_position}岗位的核心职责、必备技能与能力要求，简历仅作为背景参考。
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
"""


class InterviewSession:
    def __init__(self, resume_text: str, target_position: str, difficulty: str, user_id: int):
        self._lock = Lock()
        self.chat_list = []
        self.target_position = target_position
        self.difficulty = difficulty
        self.resume_text = resume_text
        self.user_id = user_id

        self.system_prompt = INTERVIEW_SYSTEM_PROMPT.format(
            target_position=target_position,
            difficulty=difficulty,
            resume_text=resume_text
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
            try:
                # ===== 首次提问：生成第一道面试题 =====
                if len(self.chat_list) == 1:
                    knowledge = self._get_knowledge(f"{self.target_position} {self.difficulty} 基础面试题 常考考点")
                    user_prompt = "请开始第一个问题"
                    if knowledge:
                        user_prompt = knowledge + "\n" + user_prompt
                    self.chat_list.append({"role": "user", "content": user_prompt})

                # ===== 后续追问：结合回答与题库出题 =====
                else:
                    knowledge_query = f"{self.target_position} {user_answer} 进阶追问 下一个考点"
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
                raise
