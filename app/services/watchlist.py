"""自选股监控 service —— 管理 data/watchlist.json + 装配实时行情。

设计 §4.1:自选股是"关注列表",与持仓(sim_account.json)区分。
"""
from __future__ import annotations

import logging
from typing import Any

from app.services import state

log = logging.getLogger("finance-agent.watchlist")

WATCHLIST_FILE = "watchlist.json"


def load_watchlist() -> dict[str, dict]:
    """返回 {code: {name, up_alert_pct, down_alert_pct}}。"""
    data = state.load_json(WATCHLIST_FILE, default={})
    return data if isinstance(data, dict) else {}


def _save(raw: dict[str, dict]) -> None:
    state.save_json(WATCHLIST_FILE, raw)


def add_stock(code: str, name: str = "", up_alert_pct: float | None = None, down_alert_pct: float | None = None) -> None:
    wl = load_watchlist()
    existing = wl.get(code, {})
    wl[code] = {
        "name": name or existing.get("name", code),
        "up_alert_pct": up_alert_pct if up_alert_pct is not None else existing.get("up_alert_pct"),
        "down_alert_pct": down_alert_pct if down_alert_pct is not None else existing.get("down_alert_pct"),
    }
    _save(wl)


def remove_stock(code: str) -> None:
    wl = load_watchlist()
    wl.pop(code, None)
    _save(wl)


def set_thresholds(code: str, up_alert_pct: float | None, down_alert_pct: float | None) -> None:
    wl = load_watchlist()
    if code not in wl:
        wl[code] = {"name": code, "up_alert_pct": None, "down_alert_pct": None}
    wl[code]["up_alert_pct"] = up_alert_pct
    wl[code]["down_alert_pct"] = down_alert_pct
    _save(wl)


def get_watchlist_with_quotes(datasource: Any) -> list[dict]:
    """装配自选股 + 实时行情。返回按 code 排序的列表。

    腾讯源(主)有 PE/PB/市值但无 volume;新浪(备)有 volume/bid/ask 但无 PE。
    字段尽力而为:有则带,无则 None,消费方用 .get()。
    """
    wl = load_watchlist()
    if not wl:
        return []
    codes = list(wl.keys())
    quotes = datasource.get_realtime(codes)
    rows = []
    for code in sorted(codes):
        meta = wl[code]
        q = quotes.get(code, {})
        change_pct = q.get("change_pct")
        alert = _check_alert(change_pct, meta.get("up_alert_pct"), meta.get("down_alert_pct"))
        rows.append({
            "code": code,
            "name": q.get("name") or meta.get("name") or code,
            "price": q.get("price"),
            "change_pct": change_pct,
            "volume": q.get("volume"),
            "amount_wan": q.get("amount_wan"),  # 腾讯字段
            "pe_ttm": q.get("pe_ttm"),          # 腾讯字段
            "pb": q.get("pb"),                  # 腾讯字段
            "mcap_yi": q.get("mcap_yi"),        # 腾讯字段
            "turnover_pct": q.get("turnover_pct"),  # 腾讯字段
            "up_alert_pct": meta.get("up_alert_pct"),
            "down_alert_pct": meta.get("down_alert_pct"),
            "alert": alert,
        })
    return rows


def _check_alert(change_pct: float | None, up: float | None, down: float | None) -> str | None:
    if change_pct is None:
        return None
    if up is not None and change_pct >= up:
        return "up"
    if down is not None and change_pct <= down:
        return "down"
    return None
