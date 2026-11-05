from __future__ import annotations

from unittest.mock import patch

from app.services import policy


def test_search_news_calls_monitor_and_returns_list():
    fake = [{"title": "央行降准", "source": "cls", "time": "2026-06-22", "url": "http://x", "summary": "..."}]
    with patch("app.services.policy.monitor") as mock_m:
        mock_m.search_policy_news.return_value = fake
        result = policy.search_news(keywords=["央行"])
    mock_m.search_policy_news.assert_called_once()
    assert result == fake


def test_search_news_failure_returns_empty():
    with patch("app.services.policy.monitor") as mock_m:
        mock_m.search_policy_news.side_effect = RuntimeError("net")
        result = policy.search_news()
    assert result == []


def test_enrich_adds_relation_fields():
    fake = [{"title": "支持半导体产业", "source": "x", "time": "t", "url": "", "summary": ""}]
    with patch("app.services.policy.monitor") as mock_m:
        mock_m.search_policy_news.return_value = fake
        mock_m.relate_stocks.return_value = {"sectors": ["半导体/芯片"], "stocks": [], "sentiment": "利好"}
        result = policy.search_news(enrich=True)
    assert result[0]["relation"]["sentiment"] == "利好"


def test_enrich_failure_doesnt_break_news():
    """relate_stocks 失败时该条新闻仍保留,relation 为中性默认。"""
    fake = [{"title": "某政策", "source": "x", "time": "t", "url": "", "summary": ""}]
    with patch("app.services.policy.monitor") as mock_m:
        mock_m.search_policy_news.return_value = fake
        mock_m.relate_stocks.side_effect = RuntimeError("ai error")
        result = policy.search_news(enrich=True)
    assert len(result) == 1
    assert result[0]["relation"]["sentiment"] == "中性"


def test_daily_brief_returns_string():
    with patch("app.services.policy.monitor") as mock_m:
        mock_m.daily_brief.return_value = "📋 政策日报..."
        result = policy.daily_brief()
    assert "政策日报" in result


def test_daily_brief_failure_returns_friendly():
    with patch("app.services.policy.monitor") as mock_m:
        mock_m.daily_brief.side_effect = RuntimeError("net")
        result = policy.daily_brief()
    assert "失败" in result or "不可用" in result
