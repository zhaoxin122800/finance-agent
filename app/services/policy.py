"""政策监控 service —— 包装 vendors.monitor。"""
from __future__ import annotations

import logging

from vendors import monitor

log = logging.getLogger("finance-agent.policy")


def search_news(keywords: list[str] | None = None, enrich: bool = False) -> list[dict]:
    try:
        news = monitor.search_policy_news(keywords=keywords, limit=30)
    except Exception as e:
        log.warning("search_policy_news 失败: %s", e)
        return []
    if enrich:
        for item in news:
            text = f"{item.get('title', '')} {item.get('summary', '')}"
            try:
                item["relation"] = monitor.relate_stocks(text)
            except Exception as e:
                log.warning("relate_stocks 失败: %s", e)
                item["relation"] = {"sectors": [], "stocks": [], "sentiment": "中性"}
    return news


def daily_brief() -> str:
    try:
        return monitor.daily_brief()
    except Exception as e:
        log.warning("daily_brief 失败: %s", e)
        return f"⚠️ 政策日报生成失败({e})。"
