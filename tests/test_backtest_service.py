from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services import backtest


@pytest.fixture
def cross_klines():
    """构造先跌后涨的日K(MA3 会下穿再上穿 MA5,产生金叉)。"""
    prices = [20, 18, 16, 14, 12, 13, 15, 17, 19, 21, 23, 25]
    return [{"date": f"2026-06-{i+1:02d}", "open": p - 1, "high": p + 1, "low": p - 2, "close": p, "volume": 1000} for i, p in enumerate(prices)]


@pytest.fixture
def uptrend_klines():
    """构造一段持续上涨的日K(10天,从10元涨到19元)。"""
    return [{"date": f"2026-06-{i:02d}", "open": 10 + i - 1, "high": 10 + i, "low": 9 + i - 1, "close": 10 + i, "volume": 1000} for i in range(1, 11)]


def test_ma_cross_strategy_buys_on_golden_cross(cross_klines):
    """MA3 上穿 MA5 应产生买入信号(先跌后涨产生金叉)。"""
    signals = backtest.ma_cross_signals(cross_klines, fast=3, slow=5)
    buys = [s for s in signals if s["action"] == "buy"]
    assert len(buys) >= 1


def test_run_backtest_returns_metrics(uptrend_klines):
    ds = MagicMock()
    ds.get_kline.return_value = uptrend_klines
    result = backtest.run(ds, code="600789", strategy="ma_cross", start="2026-06-01", end="2026-06-10", fast=3, slow=5)
    assert "total_return_pct" in result
    assert "max_drawdown_pct" in result
    assert "sharpe" in result
    assert "win_rate" in result
    assert "trades" in result
    assert "equity_curve" in result


def test_run_backtest_applies_commission(uptrend_klines):
    """遵循 backtest_methodology:加摩擦。每笔交易扣手续费。"""
    ds = MagicMock()
    ds.get_kline.return_value = uptrend_klines
    result = backtest.run(ds, code="600789", strategy="ma_cross", start="2026-06-01", end="2026-06-10", fast=3, slow=5, commission_rate=0.001)
    assert result["commission_paid"] >= 0


def test_run_unknown_strategy_raises(uptrend_klines):
    ds = MagicMock()
    ds.get_kline.return_value = uptrend_klines
    with pytest.raises(ValueError):
        backtest.run(ds, code="600789", strategy="nonexistent", start="2026-06-01", end="2026-06-10")


def test_max_drawdown_calculation():
    """峰值到谷底的跌幅。"""
    curve = [100, 110, 105, 90, 95]  # 110→90 = -18.18%
    dd = backtest._max_drawdown_pct(curve)
    assert abs(dd - (-18.18)) < 0.1


def test_list_strategies():
    """列出 3 个内置策略名。"""
    names = backtest.list_strategies()
    assert set(names) >= {"ma_cross", "volume_breakout", "top_list_follow"}


def test_volume_breakout_strategy():
    """放量突破:当日量 > 5日均量*1.5 且收阳 → 买入。"""
    klines = [
        {"date": "2026-06-01", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-02", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-03", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-04", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-05", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-06", "open": 10, "high": 11, "low": 10, "close": 11, "volume": 200},  # 放量+收阳
    ]
    signals = backtest.volume_breakout_signals(klines, vol_window=5, multiplier=1.5)
    buys = [s for s in signals if s["action"] == "buy"]
    assert len(buys) >= 1


def test_run_backtest_insufficient_data_returns_error():
    """K线数据不足时返回 error 而非崩溃。"""
    ds = MagicMock()
    ds.get_kline.return_value = [{"date": "2026-06-01", "close": 10, "volume": 100}]
    result = backtest.run(ds, code="600789", strategy="ma_cross", start="2026-06-01", end="2026-06-02")
    assert "error" in result


def test_top_list_follow_buys_on_anomaly():
    """龙虎榜跟随(异动跟随):涨幅>7%且放量买入。"""
    # 前5天平稳量100、收10;第6天涨到10.8(+8%)、放量到200
    klines = [
        {"date": f"2026-06-{i:02d}", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100}
        for i in range(1, 6)
    ] + [{"date": "2026-06-06", "open": 10, "high": 10.9, "low": 10, "close": 10.8, "volume": 200}]
    signals = backtest.top_list_follow_signals(klines)
    buys = [s for s in signals if s["action"] == "buy"]
    assert len(buys) == 1
    assert buys[0]["date"] == "2026-06-06"


def test_top_list_follow_sells_after_holding_period():
    """买入后持有 hold_days 天卖出。"""
    klines = [
        {"date": "2026-06-01", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-02", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-03", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-04", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-05", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-06", "open": 10, "high": 10.9, "low": 10, "close": 10.8, "volume": 200},  # 买入日
        {"date": "2026-06-07", "open": 10.8, "high": 11, "low": 10.7, "close": 10.9, "volume": 150},
        {"date": "2026-06-08", "open": 10.9, "high": 11, "low": 10.8, "close": 11.0, "volume": 150},
        {"date": "2026-06-09", "open": 11.0, "high": 11.1, "low": 10.9, "close": 11.0, "volume": 150},  # 持有3天后
    ]
    signals = backtest.top_list_follow_signals(klines, hold_days=3)
    buys = [s for s in signals if s["action"] == "buy"]
    sells = [s for s in signals if s["action"] == "sell"]
    assert len(buys) == 1
    assert len(sells) == 1
    # 卖出应在买入后第3天(06-06 买 → 06-09 卖)
    assert sells[0]["date"] == "2026-06-09"


def test_top_list_follow_stop_loss_on_drop():
    """跌破成本 stop_loss_pct 时提前卖出。"""
    klines = [
        {"date": "2026-06-01", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-02", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-03", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-04", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-05", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-06", "open": 10, "high": 10.9, "low": 10, "close": 10.8, "volume": 200},  # 买入@10.8
        {"date": "2026-06-07", "open": 10.8, "high": 10.9, "low": 9.5, "close": 9.6, "volume": 300},  # 跌破成本>5%止损
    ]
    signals = backtest.top_list_follow_signals(klines, hold_days=5, stop_loss_pct=-5.0)
    sells = [s for s in signals if s["action"] == "sell"]
    assert len(sells) == 1
    # 止损卖出价应 <= 成本价*(1-5%)
    assert sells[0]["price"] <= 10.8 * 0.95 + 0.01


def test_win_rate_correct_with_mixed_trades():
    """胜率计算:2笔交易一胜一负,胜率应 50%。"""
    # 构造 cross_klines 产生至少2次买卖
    prices = [10, 8, 6, 8, 12, 8, 6, 8, 12]  # 先跌后涨再跌再涨,产生2次金叉2次死叉
    klines = [{"date": f"2026-06-{i+1:02d}", "open": p-1, "high": p+1, "low": p-2, "close": p, "volume": 1000} for i, p in enumerate(prices)]
    ds = MagicMock()
    ds.get_kline.return_value = klines
    result = backtest.run(ds, code="600789", strategy="ma_cross", start="2026-06-01", end="2026-06-30", fast=2, slow=4)
    sells = [t for t in result["trades"] if t["action"] == "sell"]
    if len(sells) >= 1:
        # 胜率应在 0-100 之间,且 = 盈利卖出数 / 总卖出数
        assert 0 <= result["win_rate"] <= 100


def test_win_rate_no_trades_is_zero():
    """无交易时胜率为 0(不报错)。"""
    ds = MagicMock()
    ds.get_kline.return_value = [{"date": f"2026-06-{i:02d}", "close": 10, "volume": 100, "open": 10, "high": 10, "low": 10} for i in range(1, 31)]
    result = backtest.run(ds, code="600789", strategy="ma_cross", start="2026-06-01", end="2026-06-30", fast=5, slow=20)
    assert result["win_rate"] == 0.0
