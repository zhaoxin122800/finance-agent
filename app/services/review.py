"""每日复盘 service。

设计 §4.4:账户变动 + 持仓异动 + 板块数据 → LLM → 归档。
单次 LLM 调用(复盘不像个股解读需要分维度)。

数据格式优化:
- summarize_account 补今日已实现盈亏、手续费汇总、持仓明细(含浮亏)
- today_trades 精简为关键字段,剔除冗余(amount/total/extra)
- 板块数据:data.get_sectors 正则 bug 会返回空,降级用 screener._fetch_sina_sectors
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from app.ai.client import AIClient, AIClientError
from app.ai.prompts import REVIEW_PROMPT
from app.services import state

log = logging.getLogger("finance-agent.review")

# 今日交易保留的关键字段(剔除 amount/total 等冗余)
_TRADE_KEYS = ("type", "code", "name", "price", "qty", "fee", "time")


def summarize_account(account: dict, datasource: Any) -> dict:
    """计算总资产/盈亏/今日已实现盈亏/手续费/持仓明细。"""
    positions = account.get("positions", {})
    market_value = 0.0
    positions_detail = []
    quotes = datasource.get_realtime(list(positions.keys())) if positions else {}
    for code, pos in positions.items():
        q = quotes.get(code, {})
        price = q.get("price") or 0
        qty = pos.get("qty", 0)
        cost_price = pos.get("cost_price", 0)
        mv = price * qty
        market_value += mv
        unrealized_pnl = (price - cost_price) * qty
        positions_detail.append({
            "code": code,
            "name": pos.get("name") or q.get("name") or code,
            "qty": qty,
            "cost_price": round(cost_price, 3),
            "current_price": price,
            "market_value": round(mv, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "unrealized_pnl_pct": round((price / cost_price - 1) * 100, 2) if cost_price else 0,
        })

    cash = account.get("cash", 0)
    initial = account.get("initial_capital", 0)
    total_assets = cash + market_value

    today = date.today().isoformat()
    today_trades = [t for t in account.get("history", []) if str(t.get("time", "")).startswith(today)]

    # 今日已实现盈亏:配对买卖计算(简化:同代码的 买入成本 vs 卖出收入)
    today_realized_pnl, today_total_fee = _compute_realized_and_fee(today_trades)

    # 精简交易明细
    summarized_trades = [{k: t.get(k) for k in _TRADE_KEYS if k in t} for t in today_trades]

    return {
        "initial_capital": round(initial, 2),
        "cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "total_assets": round(total_assets, 2),
        "total_pnl": round(total_assets - initial, 2),
        "total_pnl_pct": round((total_assets / initial - 1) * 100, 2) if initial else 0,
        "today_realized_pnl": round(today_realized_pnl, 2),
        "today_total_fee": round(today_total_fee, 2),
        "today_trades_count": len(today_trades),
        "today_trades": summarized_trades,
        "positions_detail": positions_detail,
    }


def _compute_realized_and_fee(trades: list[dict]) -> tuple[float, float]:
    """简化计算今日已实现盈亏(买入成本 vs 卖出收入)+ 手续费总和。

    配对逻辑:对每个 code,累计买入(数量/成本)与卖出(数量/收入),
    按 FIFO 计算卖出部分对应的买入成本。
    """
    buy_lots: dict[str, list[tuple[int, float]]] = {}  # code -> [(qty, price)]
    realized = 0.0
    fee = 0.0
    for t in trades:
        code = t.get("code", "")
        ttype = t.get("type")
        qty = t.get("qty", 0) or 0
        price = t.get("price", 0) or 0
        fee += t.get("fee", 0) or 0
        if ttype == "buy":
            buy_lots.setdefault(code, []).append((qty, price))
        elif ttype == "sell":
            remaining = qty
            lots = buy_lots.get(code, [])
            while remaining > 0 and lots:
                lot_qty, lot_price = lots[0]
                matched = min(remaining, lot_qty)
                realized += (price - lot_price) * matched
                remaining -= matched
                if matched >= lot_qty:
                    lots.pop(0)
                else:
                    lots[0] = (lot_qty - matched, lot_price)
    return realized, fee


def generate_review(account: dict, datasource: Any, ai: AIClient | None) -> str:
    today = date.today().isoformat()
    archived = load_archived(today)
    if archived:
        return archived

    summary = summarize_account(account, datasource)

    # 板块数据:优先 datasource.get_sectors(走降级链),空则用 screener 新浪解析
    sectors = datasource.get_sectors()
    if not sectors:
        try:
            from app.services.screener import _fetch_sina_sectors
            sectors = _fetch_sina_sectors()
        except Exception as e:
            log.warning("板块降级解析失败: %s", e)

    if ai is None:
        return "⚠️ AI 复盘未启用。请在 .env 配置 LLM_API_KEY。账户数据已展示在上方。"

    system = REVIEW_PROMPT.format(
        account=json.dumps(summary, ensure_ascii=False, default=str),
        sectors=json.dumps(sectors[:20] if isinstance(sectors, list) else [], ensure_ascii=False, default=str),  # 前20板块避免 prompt 过长
    )
    try:
        markdown = ai.complete(system=system, user=f"请生成 {today} 的复盘报告")
    except AIClientError as e:
        return f"⚠️ AI 服务暂不可用({e})。账户数据已展示。"

    archive(today, markdown)
    return markdown


def archive(day: str, markdown: str) -> None:
    path = state.DATA_DIR / "reviews" / f"{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")


def load_archived(day: str) -> str | None:
    path = state.DATA_DIR / "reviews" / f"{day}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None
