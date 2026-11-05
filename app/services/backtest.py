"""策略回测引擎(新写)。

遵循 vendors/backtest_methodology.md 「加摩擦、找最容易崩的」原则:
- 每笔交易扣 commission_rate(默认 0.00025,匹配 sim_trade)
- 卖出加印花税 stamp_tax(默认 0.001)
- 滑点用收盘价成交(保守近似)
指标:总收益、最大回撤、夏普(年化)、胜率。
"""
from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger("finance-agent.backtest")

DEFAULT_COMMISSION = 0.00025
DEFAULT_STAMP_TAX = 0.001  # 卖出单边


def list_strategies() -> list[str]:
    return ["ma_cross", "volume_breakout", "top_list_follow"]


def _sma(values: list[float], window: int) -> list[float | None]:
    out = [None] * len(values)
    for i in range(window - 1, len(values)):
        out[i] = sum(values[i - window + 1 : i + 1]) / window
    return out


def ma_cross_signals(klines: list[dict], fast: int = 5, slow: int = 20) -> list[dict]:
    """MA fast 上穿 slow 买入,下穿卖出。"""
    closes = [k["close"] for k in klines]
    ma_fast = _sma(closes, fast)
    ma_slow = _sma(closes, slow)
    signals = []
    for i in range(1, len(klines)):
        if ma_fast[i] is None or ma_slow[i] is None or ma_fast[i - 1] is None or ma_slow[i - 1] is None:
            continue
        crossed_up = ma_fast[i - 1] <= ma_slow[i - 1] and ma_fast[i] > ma_slow[i]
        crossed_down = ma_fast[i - 1] >= ma_slow[i - 1] and ma_fast[i] < ma_slow[i]
        if crossed_up:
            signals.append({"date": klines[i]["date"], "action": "buy", "price": klines[i]["close"]})
        elif crossed_down:
            signals.append({"date": klines[i]["date"], "action": "sell", "price": klines[i]["close"]})
    return signals


def volume_breakout_signals(klines: list[dict], vol_window: int = 5, multiplier: float = 1.5) -> list[dict]:
    """放量突破:当日量 > N日均量*multiplier 且收阳 → 买;反向收阴 → 卖。"""
    signals = []
    vols = [k["volume"] for k in klines]
    for i in range(vol_window, len(klines)):
        avg_vol = sum(vols[i - vol_window : i]) / vol_window
        is_up = klines[i]["close"] > klines[i]["open"]
        if vols[i] > avg_vol * multiplier:
            if is_up:
                signals.append({"date": klines[i]["date"], "action": "buy", "price": klines[i]["close"]})
            else:
                signals.append({"date": klines[i]["date"], "action": "sell", "price": klines[i]["close"]})
    return signals


def top_list_follow_signals(
    klines: list[dict],
    vol_window: int = 5,
    anomaly_pct: float = 7.0,
    vol_mult: float = 1.5,
    hold_days: int = 3,
    stop_loss_pct: float = -5.0,
    **_,
) -> list[dict]:
    """龙虎榜股的「异动跟随」策略(龙虎榜股的典型特征:涨幅异常+放量)。

    真实逻辑(不再是占位):
    - 买入信号:当日涨幅 >= anomaly_pct(默认7%,龙虎榜涨幅偏离阈值)
                  且当日成交量 > N日均量 * vol_mult(放量确认)
    - 卖出信号:持有 hold_days 天后卖出;或跌破成本 stop_loss_pct 止损
    - 同一时间只持有一笔,卖出后才能再买
    """
    if len(klines) < vol_window + 1:
        return []

    vols = [k["volume"] for k in klines]
    signals: list[dict] = []
    holding = False
    buy_day = -1
    buy_price = 0.0

    for i in range(vol_window, len(klines)):
        k = klines[i]
        avg_vol = sum(vols[i - vol_window : i]) / vol_window
        change_pct = ((k["close"] - klines[i - 1]["close"]) / klines[i - 1]["close"] * 100) if klines[i - 1]["close"] else 0
        is_anomaly = change_pct >= anomaly_pct and vols[i] > avg_vol * vol_mult

        if not holding and is_anomaly:
            signals.append({"date": k["date"], "action": "buy", "price": k["close"]})
            holding = True
            buy_day = i
            buy_price = k["close"]
        elif holding:
            days_held = i - buy_day
            pnl_pct = (k["close"] - buy_price) / buy_price * 100 if buy_price else 0
            if pnl_pct <= stop_loss_pct or days_held >= hold_days:
                signals.append({"date": k["date"], "action": "sell", "price": k["close"]})
                holding = False
    return signals


_STRATEGY_FNS = {
    "ma_cross": ma_cross_signals,
    "volume_breakout": volume_breakout_signals,
    "top_list_follow": top_list_follow_signals,
}


def _max_drawdown_pct(equity: list[float]) -> float:
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = (v - peak) / peak * 100 if peak else 0
        max_dd = min(max_dd, dd)
    return round(max_dd, 2)


def run(
    datasource: Any,
    code: str,
    strategy: str,
    start: str,
    end: str,
    fast: int = 5,
    slow: int = 20,
    commission_rate: float = DEFAULT_COMMISSION,
    stamp_tax: float = DEFAULT_STAMP_TAX,
    initial_capital: float = 10000.0,
) -> dict:
    if strategy not in _STRATEGY_FNS:
        raise ValueError(f"未知策略: {strategy},可选 {list(_STRATEGY_FNS)}")

    klines = datasource.get_kline(code, days=120, scale="240")
    klines = [k for k in klines if start <= k["date"] <= end]
    if len(klines) < max(fast, slow) + 1:
        return {"error": f"K线数据不足({len(klines)} 根),至少需 {max(fast, slow)+1} 根"}

    fn = _STRATEGY_FNS[strategy]
    kwargs = {"fast": fast, "slow": slow} if strategy == "ma_cross" else {}
    signals = fn(klines, **kwargs)

    cash = initial_capital
    position = 0
    trades = []
    commission_paid = 0.0
    equity_curve = []

    for sig in signals:
        price = sig["price"]
        if sig["action"] == "buy" and position == 0:
            qty = int(cash / (price * (1 + commission_rate)))
            qty = (qty // 100) * 100
            if qty <= 0:
                continue
            fee = price * qty * commission_rate
            cash -= price * qty + fee
            commission_paid += fee
            position = qty
            trades.append({"date": sig["date"], "action": "buy", "price": price, "qty": qty, "fee": round(fee, 2)})
        elif sig["action"] == "sell" and position > 0:
            revenue = price * position
            fee = revenue * (commission_rate + stamp_tax)
            cash += revenue - fee
            commission_paid += fee
            trades.append({"date": sig["date"], "action": "sell", "price": price, "qty": position, "fee": round(fee, 2)})
            position = 0

    last_price = klines[-1]["close"]
    final_equity = cash + position * last_price

    for k in klines:
        mark_to_market = cash + position * k["close"]
        equity_curve.append({"date": k["date"], "equity": round(mark_to_market, 2)})

    total_return_pct = (final_equity / initial_capital - 1) * 100
    eq_values = [e["equity"] for e in equity_curve] or [initial_capital]

    daily_returns = []
    for i in range(1, len(eq_values)):
        if eq_values[i - 1] > 0:
            daily_returns.append(eq_values[i] / eq_values[i - 1] - 1)
    if daily_returns:
        mean_r = sum(daily_returns) / len(daily_returns)
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)) or 1e-9
        sharpe = round(mean_r / std_r * math.sqrt(252), 2)
    else:
        sharpe = 0.0

    # 胜率:按交易序列顺序,用状态机配对(显式找每个卖出对应的最近买入),
    # 比 zip(buys, sells) 更健壮 —— 即使序列不严格交替也不会错配
    win_count = 0
    sell_count = 0
    pending_buy_price = None
    for t in trades:
        if t["action"] == "buy":
            pending_buy_price = t["price"]
        elif t["action"] == "sell" and pending_buy_price is not None:
            sell_count += 1
            if t["price"] > pending_buy_price:
                win_count += 1
            pending_buy_price = None
    win_rate = round(win_count / sell_count * 100, 2) if sell_count else 0.0

    return {
        "code": code,
        "strategy": strategy,
        "start": start,
        "end": end,
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": _max_drawdown_pct(eq_values),
        "sharpe": sharpe,
        "win_rate": win_rate,
        "trades": trades,
        "equity_curve": equity_curve,
        "commission_paid": round(commission_paid, 2),
        "final_equity": round(final_equity, 2),
    }
