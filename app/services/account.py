"""虚拟账户 service —— 包装 vendors.sim_trade。

sim_trade 的 buy/sell 直接操作 data/sim_account.json(经 M1 路径补丁)。
- 交易动作:转调 sim_trade.buy/sell,失败时 catch 异常返回结构化错误。
- 账户视图:直接读 sim_account.json + 调 DataSource 取现价装配。
设计 §4.9:sim_account.json 是唯一真实来源。
"""
from __future__ import annotations

import logging
from typing import Any

from app.services import state
from app.services.account_seed import INITIAL_CAPITAL
from vendors import sim_trade  # M1 已打路径补丁,ACCOUNT_FILE 指向 data/

log = logging.getLogger("finance-agent.account")

ACCOUNT_FILE = "sim_account.json"


def load_account() -> dict:
    data = state.load_json(ACCOUNT_FILE, default=None)
    if data is None:
        return {
            "initial_capital": INITIAL_CAPITAL, "cash": INITIAL_CAPITAL,
            "positions": {}, "history": [],
        }
    return data


def build_account_view(datasource: Any) -> dict:
    """装配账户视图:总资产/盈亏/持仓(含现价与盈亏%)。"""
    acct = load_account()
    positions = acct.get("positions", {})
    rows = []
    market_value = 0.0
    quotes = datasource.get_realtime(list(positions.keys())) if positions else {}

    for code, pos in positions.items():
        q = quotes.get(code, {})
        price = q.get("price") or 0
        qty = pos.get("qty", 0)
        cost_price = pos.get("cost_price", 0)
        mv = price * qty
        cv = cost_price * qty
        pnl = mv - cv
        pnl_pct = (price / cost_price - 1) * 100 if cost_price else 0
        rows.append({
            "code": code, "name": pos.get("name") or q.get("name") or code,
            "qty": qty, "cost_price": cost_price, "price": price,
            "market_value": round(mv, 2), "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
        })
        market_value += mv

    cash = acct.get("cash", 0)
    total_assets = cash + market_value
    return {
        "cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "total_assets": round(total_assets, 2),
        "total_pnl": round(total_assets - acct.get("initial_capital", total_assets), 2),
        "positions": rows,
    }


def buy(code: str, qty: int | None = None, amount: float | None = None) -> dict:
    """转调 sim_trade.buy,据其返回值上报结果(不吞错误)。

    sim_trade.buy 返回 {"ok": bool, "msg": str};返回 None(旧契约)视为失败。
    """
    try:
        result = sim_trade.buy(code, qty=qty, amount=amount)
    except Exception as e:
        log.warning("买入失败 %s: %s", code, e)
        return {"ok": False, "error": str(e)}
    if isinstance(result, dict) and result.get("ok"):
        return {"ok": True}
    msg = result.get("msg") if isinstance(result, dict) else "未知失败"
    log.info("买入未成交 %s: %s", code, msg)
    return {"ok": False, "error": msg}


def sell(code: str, qty: int | None = None, all_: bool = False) -> dict:
    """转调 sim_trade.sell,据其返回值上报结果(见 buy)。"""
    try:
        result = sim_trade.sell(code, qty=qty, all=all_)
    except Exception as e:
        log.warning("卖出失败 %s: %s", code, e)
        return {"ok": False, "error": str(e)}
    if isinstance(result, dict) and result.get("ok"):
        return {"ok": True}
    msg = result.get("msg") if isinstance(result, dict) else "未知失败"
    log.info("卖出未成交 %s: %s", code, msg)
    return {"ok": False, "error": msg}


def history() -> list[dict]:
    return load_account().get("history", [])
