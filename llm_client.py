"""
llm_client.py
统一的大模型调用封装。默认走智谱 GLM 的 OpenAI 兼容接口；
只需切换 base_url 和 model 即可对接 DeepSeek / Qwen 等其他国产模型。
"""

from openai import OpenAI


DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"


class LLMClient:
    """轻量包装：统一 generate(prompt) 接口，屏蔽底层 SDK 差异"""

    def __init__(self,
                 api_key: str,
                 model: str = "glm-4-plus",
                 base_url: str = DEFAULT_BASE_URL):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model  = model

    def generate(self,
                 prompt: str,
                 max_tokens: int = 4096,
                 temperature: float = 0.3) -> str:
        """
        发送单轮 user 消息，返回模型生成的纯文本。

        兼容思考型模型（GLM-4.6 等）：当 content 为空时回退到 reasoning_content。
        思考型模型的 thinking 会占用 max_tokens 预算，建议给非思考型场景用 glm-4-plus。
        """
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        msg = resp.choices[0].message
        text = (getattr(msg, "content", None) or "").strip()
        if not text:
            # 思考型模型可能把答案放在 reasoning_content
            text = (getattr(msg, "reasoning_content", None) or "").strip()
        return text
