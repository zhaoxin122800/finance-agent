#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
A股模拟交易系统 — 1000元虚拟账户

Usage:
    uv run sim_trade.py account                      # 查看账户
    uv run sim_trade.py buy 600789 --qty 100          # 买入100股
    uv run sim_trade.py buy 600789 --amount 500       # 用500元买
    uv run sim_trade.py sell 600789 --qty 100         # 卖出100股
    uv run sim_trade.py sell 600789 --all             # 全部卖出
    uv run sim_trade.py history                       # 交易记录
    uv run sim_trade.py reset                         # 重置账户(1000元)
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# Windows 控制台 UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SKILL_SCRIPTS = os.path.expanduser("~/.openclaw-autoclaw/skills/a-stock-analysis/scripts")
sys.path.insert(0, SKILL_SCRIPTS)
sys.path.insert(0, os.path.dirname(__file__))
from analyze import get_sina_symbol, fetch_realtime_sina

ACCOUNT_FILE = Path.home() / ".openclaw-autoclaw" / "workspace" / "sim_account.json"
INITIAL_CAPITAL = 100000.0  # 与 account_seed 一致;A股最低1手100股
COMMISSION_RATE = 0.00025
MIN_COMMISSION = 5.0
STAMP_TAX_RATE = 0.001
TRANSFER_FEE_RATE = 0.00001


def load_account():
    if ACCOUNT_FILE.exists():
        with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "initial_capital": INITIAL_CAPITAL,
        "cash": INITIAL_CAPITAL,
        "positions": {},
        "history": [],
        "created_at": datetime.now().isoformat(),
    }


def save_account(data):
    ACCOUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    with open(ACCOUNT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_price(code):
    symbol = get_sina_symbol(code)
    data = fetch_realtime_sina([symbol])
    if symbol not in data:
        raise ValueError(f"无法获取 {code} 行情")
    info = data[symbol]
    name = info.get("name", code)
    price = info.get("price", 0)
    if price <= 0:
        raise ValueError(f"{code} 当前价格异常: {price}")
    return name, price


def calc_buy_fee(price, qty):
    amount = price * qty
    commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
    transfer = amount * TRANSFER_FEE_RATE
    return round(commission + transfer, 2)


def calc_sell_fee(price, qty):
    amount = price * qty
    commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
    stamp_tax = amount * STAMP_TAX_RATE
    transfer = amount * TRANSFER_FEE_RATE
    return round(commission + stamp_tax + transfer, 2)


def buy(code, qty=None, amount=None):
    """买入。

    返回 {"ok": bool, "msg": str}。失败不抛异常(打印 ❌ + 返回 ok=False),
    以便上层 service 区分成功/失败(CLI 仍可忽略返回值)。
    """
    name, price = get_price(code)

    if qty is None and amount is not None:
        max_qty = int(amount / (price * (1 + COMMISSION_RATE + TRANSFER_FEE_RATE)))
        qty = (max_qty // 100) * 100
        if qty < 100:
            msg = f"{amount:.2f}元最多只能买{max_qty}股，不足1手(100股)"
            print(f"❌ {msg}")
            return {"ok": False, "msg": msg}

    if qty <= 0 or qty % 100 != 0:
        msg = f"买入数量必须是100的整数倍，当前: {qty}"
        print(f"❌ {msg}")
        return {"ok": False, "msg": msg}

    cost = price * qty
    fee = calc_buy_fee(price, qty)
    total = cost + fee

    account = load_account()
    if account["cash"] < total:
        msg = f"资金不足！需要 {total:.2f} 元（含手续费 {fee:.2f}），账户仅有 {account['cash']:.2f} 元"
        print(f"❌ {msg}")
        return {"ok": False, "msg": msg}

    account["cash"] = round(account["cash"] - total, 2)

    if code not in account["positions"]:
        account["positions"][code] = {
            "name": name,
            "qty": 0,
            "cost_price": 0,
            "lots": [],
        }

    pos = account["positions"][code]
    old_total_cost = pos["cost_price"] * pos["qty"]
    pos["qty"] += qty
    pos["cost_price"] = round((old_total_cost + cost) / pos["qty"], 4)
    pos["name"] = name
    pos["lots"].append({"qty": qty, "price": price, "time": datetime.now().isoformat(), "fee": fee})

    account["history"].append({
        "type": "buy",
        "code": code,
        "name": name,
        "price": price,
        "qty": qty,
        "amount": cost,
        "fee": fee,
        "total": total,
        "time": datetime.now().isoformat(),
    })

    save_account(account)
    print(f"✅ 买入成功: {name}({code}) {qty}股 @ {price:.2f}元")
    print(f"   成交金额: {cost:.2f}  手续费: {fee:.2f}  合计: {total:.2f}")
    print(f"   账户余额: {account['cash']:.2f} 元")
    return {"ok": True, "msg": f"买入成功 {name}({code}) {qty}股 @ {price:.2f}元"}


def sell(code, qty=None, all=False):
    """卖出。返回 {"ok": bool, "msg": str}(见 buy 注释)。"""
    account = load_account()
    if code not in account["positions"]:
        msg = f"未持有 {code}"
        print(f"❌ {msg}")
        return {"ok": False, "msg": msg}

    pos = account["positions"][code]
    if all:
        qty = pos["qty"]

    if qty <= 0:
        msg = "卖出数量必须大于0"
        print(f"❌ {msg}")
        return {"ok": False, "msg": msg}

    if qty > pos["qty"]:
        msg = f"持仓不足！持有 {pos['qty']} 股，试图卖出 {qty} 股"
        print(f"❌ {msg}")
        return {"ok": False, "msg": msg}

    name, price = get_price(code)
    revenue = price * qty
    fee = calc_sell_fee(price, qty)
    net = round(revenue - fee, 2)

    account["cash"] = round(account["cash"] + net, 2)
    pos["qty"] -= qty

    if pos["qty"] == 0:
        account["positions"].pop(code, None)

    account["history"].append({
        "type": "sell",
        "code": code,
        "name": name,
        "price": price,
        "qty": qty,
        "amount": revenue,
        "fee": fee,
        "net": net,
        "time": datetime.now().isoformat(),
    })

    save_account(account)
    print(f"✅ 卖出成功: {name}({code}) {qty}股 @ {price:.2f}元")
    print(f"   成交金额: {revenue:.2f}  手续费: {fee:.2f}  到账: {net:.2f}")
    return {"ok": True, "msg": f"卖出成功 {name}({code}) {qty}股 @ {price:.2f}元"}
    print(f"   账户余额: {account['cash']:.2f} 元")


def show_account():
    account = load_account()

    print("=" * 66)
    print(f"  📊 模拟交易账户  初始资金: {account['initial_capital']:.2f} 元")
    print("=" * 66)

    positions = account["positions"]
    total_market_value = 0
    total_cost = 0

    if positions:
        symbols = [get_sina_symbol(code) for code in positions]
        realtime = fetch_realtime_sina(symbols)

        print(f"\n  {'名称':<8} {'代码':<8} {'持仓':<8} {'成本':<8} {'现价':<8} {'市值':<10} {'盈亏':<12}")
        print("  " + "-" * 62)

        for code, pos in positions.items():
            symbol = get_sina_symbol(code)
            rt = realtime.get(symbol, {})
            price = rt.get("price", 0)
            name = pos.get("name", code)
            qty = pos["qty"]
            cost_price = pos["cost_price"]
            market_value = price * qty
            cost_value = cost_price * qty
            pnl = market_value - cost_value
            pnl_pct = (price / cost_price - 1) * 100 if cost_price > 0 else 0

            total_market_value += market_value
            total_cost += cost_value

            pnl_str = f"{pnl:+.2f} ({pnl_pct:+.2f}%)"
            print(f"  {name:<8} {code:<8} {qty:<8} {cost_price:<8.3f} {price:<8.2f} {market_value:<10.2f} {pnl_str:<12}")
    else:
        print("\n  （空仓）")

    total_assets = account["cash"] + total_market_value
    total_pnl = total_assets - account["initial_capital"]
    total_pnl_pct = (total_assets / account["initial_capital"] - 1) * 100

    print("\n  " + "-" * 62)
    print(f"  💰 现金: {account['cash']:.2f} 元")
    print(f"  📈 持仓市值: {total_market_value:.2f} 元")
    print(f"  🏦 总资产: {total_assets:.2f} 元")
    print(f"  {'📊' if total_pnl >= 0 else '📉'} 总盈亏: {total_pnl:+.2f} 元 ({total_pnl_pct:+.2f}%)")
    print(f"  📅 创建时间: {account.get('created_at', 'N/A')[:19]}")
    print(f"  🔄 更新时间: {account.get('updated_at', 'N/A')[:19]}")


def show_history():
    account = load_account()
    history = account["history"]

    if not history:
        print("暂无交易记录")
        return

    print("=" * 80)
    print(f"  📋 交易记录 ({len(history)} 笔)")
    print("=" * 80)
    print(f"  {'时间':<20} {'类型':<6} {'名称':<8} {'代码':<8} {'价格':<8} {'数量':<8} {'金额':<10} {'手续费':<8}")
    print("  " + "-" * 76)

    for t in history:
        time_str = t["time"][:19]
        ttype = "买入" if t["type"] == "buy" else "卖出"
        print(f"  {time_str:<20} {ttype:<6} {t['name']:<8} {t['code']:<8} {t['price']:<8.2f} {t['qty']:<8} {t['amount']:<10.2f} {t['fee']:<8.2f}")

    buys = [t for t in history if t["type"] == "buy"]
    sells = [t for t in history if t["type"] == "sell"]
    total_buy_amount = sum(t["amount"] + t["fee"] for t in buys)
    total_sell_amount = sum(t["net"] for t in sells)

    print("  " + "-" * 76)
    print(f"  买入: {len(buys)}笔, 总支出 {total_buy_amount:.2f} 元")
    print(f"  卖出: {len(sells)}笔, 总到账 {total_sell_amount:.2f} 元")


def reset_account():
    account = {
        "initial_capital": INITIAL_CAPITAL,
        "cash": INITIAL_CAPITAL,
        "positions": {},
        "history": [],
        "created_at": datetime.now().isoformat(),
    }
    save_account(account)
    print(f"✅ 账户已重置，初始资金 {INITIAL_CAPITAL:.2f} 元")


def main():
    parser = argparse.ArgumentParser(description="A股模拟交易系统 (1000元虚拟账户)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("account", help="查看账户")
    sub.add_parser("history", help="交易记录")
    sub.add_parser("reset", help="重置账户(1000元)")

    buy_p = sub.add_parser("buy", help="买入股票")
    buy_p.add_argument("code", help="股票代码")
    buy_p.add_argument("--qty", "-q", type=int, help="买入数量(100的整数倍)")
    buy_p.add_argument("--amount", "-a", type=float, help="按金额买入")

    sell_p = sub.add_parser("sell", help="卖出股票")
    sell_p.add_argument("code", help="股票代码")
    sell_p.add_argument("--qty", "-q", type=int, help="卖出数量")
    sell_p.add_argument("--all", action="store_true", help="全部卖出")

    args = parser.parse_args()

    if args.command == "account":
        show_account()
    elif args.command == "buy":
        if args.qty is None and args.amount is None:
            print("❌ 请指定 --qty 或 --amount")
            return
        buy(args.code, qty=args.qty, amount=args.amount)
    elif args.command == "sell":
        if not args.all and args.qty is None:
            print("❌ 请指定 --qty 或 --all")
            return
        sell(args.code, qty=args.qty, all=args.all)
    elif args.command == "history":
        show_history()
    elif args.command == "reset":
        reset_account()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
