from threading import Lock

from utils.llm_util import chat_completion

CHAT_SYSTEM_PROMPT = """
你是Career Coach职业小助手，专业、耐心、简洁地解答用户的求职、技术、面试相关问题，也可以回答通用知识类问题。
回答条理清晰，重点突出，不要使用Markdown格式，用纯文本自然分段表达。
"""

class ChatSession:
    def __init__(self):
        self._lock = Lock()
        self.chat_list = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT}
        ]

    def stream_reply(self, message: str):
        """
        流式生成回复，自动维护对话历史
        :param message: 用户当前输入的消息
        :return: 生成器，逐字返回文本
        """
        with self._lock:
            original_chat = self.chat_list.copy()
            try:
                # 添加用户消息
                self.chat_list.append({"role": "user", "content": message})

                # 调用大模型流式输出
                response = chat_completion(self.chat_list, stream=True)
                full_reply = ""

                for chunk in response:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if hasattr(delta, "content") and delta.content:
                            text = delta.content
                            full_reply += text
                            yield text

                # 正常结束，保存助手回复到对话历史
                self.chat_list.append({"role": "assistant", "content": full_reply})

            except BaseException:
                # Roll back both ordinary failures and client disconnects.
                self.chat_list = original_chat
                raise
