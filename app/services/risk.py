"""风险预警 service。

设计 §4.8:对自选股扫描规则:跌幅超阈值、放量异常、破均线。
触发归档到 data/alerts/。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.config import DATA_DIR
from app.services.watchlist import load_watchlist

log = logging.getLogger("finance-agent.risk")


def load_watchlist_meta() -> dict[str, dict]:
    """复用 watchlist 的自选股(代码+阈值)。"""
    return load_watchlist()


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0


def scan(datasource: Any) -> list[dict]:
    wl = load_watchlist_meta()
    if not wl:
        return []
    codes = list(wl.keys())
    quotes = datasource.get_realtime(codes)
    alerts = []
    for code in codes:
        meta = wl[code]
        q = quotes.get(code, {})
        change_pct = q.get("change_pct")
        price = q.get("price")
        rules = []

        # 规则1:涨跌幅超阈值
        up_t = meta.get("up_alert_pct")
        down_t = meta.get("down_alert_pct")
        if change_pct is not None:
            if up_t is not None and change_pct >= up_t:
                rules.append("up_threshold")
            if down_t is not None and change_pct <= down_t:
                rules.append("down_threshold")

        # 规则2/3:需 K线
        klines = datasource.get_kline(code, days=30, scale="240") if price else []
        # 放量异常
        if klines and len(klines) >= 6:
            recent_vols = [k["volume"] for k in klines[-6:-1]]
            avg_vol = _avg(recent_vols)
            today_vol = klines[-1]["volume"]
            if avg_vol > 0 and today_vol > avg_vol * 2:
                rules.append("volume_spike")
        # 破 20 日均线
        if klines and len(klines) >= 20 and price:
            ma20 = _avg([k["close"] for k in klines[-20:]])
            if price < ma20:
                rules.append("ma_break")

        if rules:
            alert = {
                "code": code,
                "name": q.get("name") or meta.get("name") or code,
                "price": price,
                "change_pct": change_pct,
                "rules": rules,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            alerts.append(alert)

    if alerts:
        _archive(alerts)
    return alerts


def _archive(alerts: list[dict]) -> None:
    path = DATA_DIR / "alerts" / f"{time.strftime('%Y-%m-%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(alerts, ensure_ascii=False, indent=2), encoding="utf-8")
