"""AI client 测试 —— mock openai.OpenAI,绝不打真实 LLM(设计 §9)。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.ai.client import AIClient, AIClientError


def _make_client():
    return AIClient(base_url="http://fake/v1", api_key="sk-fake", model="glm-4-flash")


def test_complete_returns_content_on_success():
    client = _make_client()
    with patch.object(client, "_client") as mock_client:
        mock_msg = MagicMock()
        mock_msg.message.content = "这是 AI 解读"
        mock_choice = MagicMock()
        mock_choice.message = mock_msg.message
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp
        result = client.complete(system="你是分析师", user="分析 600789")
    assert result == "这是 AI 解读"


def test_complete_includes_context_when_provided():
    """context 拼进 system 末尾作为 RAG 背景。"""
    client = _make_client()
    with patch.object(client, "_client") as mock_client:
        mock_msg = MagicMock()
        mock_msg.message.content = "ok"
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message = mock_msg.message
        mock_client.chat.completions.create.return_value = mock_resp
        client.complete(system="s", user="u", context="背景知识: MACD 金叉")
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        all_text = " ".join(m.get("content", "") for m in messages)
        assert "MACD 金叉" in all_text


def test_complete_raises_on_api_error():
    client = _make_client()
    with patch.object(client, "_client") as mock_client:
        mock_client.chat.completions.create.side_effect = RuntimeError("rate limit")
        with pytest.raises(AIClientError) as exc_info:
            client.complete(system="s", user="u")
    assert "rate limit" in str(exc_info.value)


def test_complete_raises_on_empty_choices():
    client = _make_client()
    with patch.object(client, "_client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.choices = []
        mock_client.chat.completions.create.return_value = mock_resp
        with pytest.raises(AIClientError):
            client.complete(system="s", user="u")


def test_complete_strips_whitespace():
    client = _make_client()
    with patch.object(client, "_client") as mock_client:
        mock_msg = MagicMock()
        mock_msg.message.content = "  带空白的解读  \n"
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message = mock_msg.message
        mock_client.chat.completions.create.return_value = mock_resp
        result = client.complete(system="s", user="u")
    assert result == "带空白的解读"


def test_client_constructs_openai_with_base_url_and_key():
    with patch("app.ai.client.OpenAI") as mock_openai_cls:
        AIClient(base_url="http://x/v1", api_key="sk-y", model="m")
    mock_openai_cls.assert_called_once()
    kwargs = mock_openai_cls.call_args.kwargs
    assert kwargs["base_url"] == "http://x/v1"
    assert kwargs["api_key"] == "sk-y"
