"""ai 包 —— 根据 config 决定返回 AIClient 还是 None(未配 key)。"""
from __future__ import annotations

from app.ai.client import AIClient, AIClientError
from app.config import get_settings

__all__ = ["AIClient", "AIClientError", "get_ai_client"]


def get_ai_client() -> AIClient | None:
    """未配 key 时返回 None(设计 §8:AI 按钮置灰)。"""
    s = get_settings()
    if not s.ai_enabled:
        return None
    return AIClient(base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.llm_model)
