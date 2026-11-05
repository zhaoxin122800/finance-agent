"""quant-kb 检索测试 —— 用临时 kb 目录。"""
from __future__ import annotations

import pytest

from app.ai import kb


@pytest.fixture
def fake_kb(tmp_path, monkeypatch):
    """造 2 个假 md,含关键词。"""
    (tmp_path / "terms.md").write_text("# 术语\n\n## T+1\n当天买入次日才能卖出。\n## MACD\n异动移动平均指标。\n", encoding="utf-8")
    (tmp_path / "strategies.md").write_text("# 策略\n\n## 均线交叉\nMA5 上穿 MA20 买入。\n", encoding="utf-8")
    monkeypatch.setattr(kb, "QUANT_KB_DIR", tmp_path)
    return tmp_path


def test_search_returns_matching_snippets(fake_kb):
    result = kb.search(["T+1"])
    assert any("T+1" in s for s in result)


def test_search_no_match_returns_empty(fake_kb):
    result = kb.search(["完全不存在的词"])
    assert result == []


def test_search_aggregates_across_files(fake_kb):
    """关键词分散在多个文件时都要召回。"""
    result = kb.search(["T+1", "均线"])
    joined = "\n".join(result)
    assert "T+1" in joined
    assert "均线" in joined


def test_search_deduplicates(fake_kb):
    """同一关键词多次匹配不重复返回同一段。"""
    result = kb.search(["T+1", "T+1"])
    t1_count = sum(1 for s in result if "T+1" in s)
    assert t1_count == 1


def test_search_limits_snippet_length(fake_kb):
    """单条 snippet 不过长(避免撑爆 prompt)。"""
    (fake_kb / "big.md").write_text("# 大文件\n\n" + ("很长的内容 " * 500), encoding="utf-8")
    result = kb.search(["大文件"])
    assert all(len(s) <= 600 for s in result)


def test_format_for_prompt_joins_snippets(fake_kb):
    snippets = kb.search(["T+1"])
    formatted = kb.format_for_prompt(snippets)
    assert "T+1" in formatted


def test_search_empty_keywords_returns_empty(fake_kb):
    assert kb.search([]) == []
