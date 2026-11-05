"""OpenAI 兼容 LLM 客户端。

设计 §6.2:AIClient.complete(system, user, context)。失败抛 AIClientError。
兼容 GLM/DeepSeek/通义/OpenAI —— 它们都遵循 OpenAI API 协议。
"""
from __future__ import annotations

import logging

from openai import OpenAI

log = logging.getLogger("finance-agent.ai")


class AIClientError(Exception):
    """LLM 调用失败。"""


class AIClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self._model = model
        self._client = OpenAI(base_url=base_url, api_key=api_key)

    def complete(self, system: str, user: str, context: str = "") -> str:
        """调 chat completion。context 拼到 system 末尾作为 RAG 背景。"""
        full_system = system
        if context:
            full_system = f"{system}\n\n【参考知识】\n{context}"
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": full_system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as e:
            log.warning("LLM 调用失败: %s", e)
            raise AIClientError(str(e)) from e
        if not resp.choices:
            raise AIClientError("LLM 返回空 choices")
        content = resp.choices[0].message.content or ""
        return content.strip()
