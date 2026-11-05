"""个股分析 service —— 装配实时/K线/分时量能/资金流/龙虎榜。

设计 §4.2:数据来自 DataSource + vendors.analyze。AI 解读在 M3。
所有子调用独立兜底,任一失败不影响其它字段(设计 §8)。
"""
from __future__ import annotations

import logging
from typing import Any

from vendors import analyze  # 原样资产

log = logging.getLogger("finance-agent.analyst")


def assemble(code: str, datasource: Any, kline_scale: str = "240", kline_days: int = 60) -> dict:
    """装配个股分析数据。

    realtime/kline/money_flow 走 DataSource(降级链:腾讯/百度→新浪);
    分时量能走 vendors.analyze(它自己拉分时 + 分析)。
    kline_scale: K线周期 5/15/30/60(分钟)/240(日)/1680(周)。
    """
    quotes = datasource.get_realtime([code])
    realtime = quotes.get(code, {})

    kline = datasource.get_kline(code, days=kline_days, scale=kline_scale)
    money_flow = datasource.get_money_flow(code)

    # 分时量能(vendors.analyze 自己拉分时数据 + 分析)
    try:
        analysis = analyze.analyze_stock(code, with_minute=True, realtime_cache={})
    except Exception as e:
        log.warning("analyze_stock 失败(%s): %s", code, e)
        analysis = {"error": str(e)}

    top_list = datasource.get_top_list()
    on_top = next((t for t in top_list if t.get("code") == code), None)

    # 个股公告(东财,比新闻权威)
    announcements: list[dict] = []
    try:
        from app.services.market import stock_announcements
        announcements = stock_announcements(code, limit=5)
    except Exception as e:
        log.warning("公告获取失败(%s): %s", code, e)

    # 公司画像/产业链定位(东财 F10,供 AI 第 4 维度)
    company: dict = {}
    try:
        from app.services.market import company_profile
        company = company_profile(code)
    except Exception as e:
        log.warning("公司画像获取失败(%s): %s", code, e)

    return {
        "code": code,
        "realtime": realtime,
        "kline": kline,
        "money_flow": money_flow,
        "minute_analysis": analysis.get("minute_analysis", {}) if isinstance(analysis, dict) else {},
        "error": analysis.get("error") if isinstance(analysis, dict) else str(analysis),
        "on_top_list": on_top is not None,
        "top_list_reason": on_top.get("reason", "") if on_top else "",
        "announcements": announcements,
        "company": company,
    }
