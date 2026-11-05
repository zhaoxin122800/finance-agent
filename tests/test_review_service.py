"""review service 测试。"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.services import review


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    from app.services import state
    monkeypatch.setattr(state, "DATA_DIR", tmp_path)
    yield tmp_path


def test_summarize_account_computes_pnl():
    """从 sim_account + 实时价计算总资产/盈亏。"""
    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 11.0, "name": "鲁信创投"}}
    account = {
        "initial_capital": 1000.0, "cash": 800.0,
        "positions": {"600789": {"qty": 100, "cost_price": 10.0, "name": "鲁信创投"}},
        "history": [],
    }
    summary = review.summarize_account(account, ds)
    assert summary["cash"] == 800.0
    assert summary["market_value"] == 1100.0  # 11.0 * 100
    assert summary["total_assets"] == 1900.0
    assert summary["total_pnl"] == 900.0  # 1900 - 1000


def test_summarize_account_handles_empty_positions():
    ds = MagicMock()
    ds.get_realtime.return_value = {}
    account = {"initial_capital": 1000.0, "cash": 1000.0, "positions": {}, "history": []}
    summary = review.summarize_account(account, ds)
    assert summary["market_value"] == 0.0
    assert summary["total_assets"] == 1000.0


def test_summarize_account_today_history():
    """只统计今天的交易。"""
    ds = MagicMock()
    ds.get_realtime.return_value = {}
    today = date.today().isoformat()
    account = {
        "initial_capital": 1000.0, "cash": 1000.0, "positions": {},
        "history": [
            {"type": "buy", "code": "600789", "time": today + "T10:00:00", "amount": 1000, "fee": 5},
            {"type": "sell", "code": "600789", "time": "2020-01-01T10:00:00", "amount": 500, "fee": 5},
        ],
    }
    summary = review.summarize_account(account, ds)
    assert summary["today_trades_count"] == 1


def test_generate_review_calls_llm_and_archives():
    ai = MagicMock()
    ai.complete.return_value = "## 今日复盘\n账户表现良好"
    ds = MagicMock()
    ds.get_realtime.return_value = {}
    ds.get_sectors.return_value = [{"name": "银行", "change_pct": 1.5}]
    account = {"initial_capital": 1000.0, "cash": 1000.0, "positions": {}, "history": []}
    md = review.generate_review(account, ds, ai)
    assert "今日复盘" in md
    today = date.today().isoformat()
    assert review.load_archived(today) == md


def test_generate_review_returns_archived_on_repeat():
    ai = MagicMock()
    ai.complete.return_value = "首次"
    ds = MagicMock()
    ds.get_realtime.return_value = {}
    ds.get_sectors.return_value = []
    account = {"initial_capital": 1000.0, "cash": 1000.0, "positions": {}, "history": []}
    review.generate_review(account, ds, ai)
    ai.complete.reset_mock()
    again = review.generate_review(account, ds, ai)
    assert again == "首次"
    ai.complete.assert_not_called()


def test_generate_review_without_ai_returns_disabled():
    ds = MagicMock()
    account = {"initial_capital": 1000.0, "cash": 1000.0, "positions": {}, "history": []}
    result = review.generate_review(account, ds, ai=None)
    assert "未启用" in result


def test_summarize_account_computes_today_realized_pnl_and_fee():
    """今日已实现盈亏(卖出收入-对应买入成本)+ 手续费汇总。"""
    ds = MagicMock()
    ds.get_realtime.return_value = {}
    today = date.today().isoformat()
    account = {
        "initial_capital": 100000.0, "cash": 95000.0, "positions": {},
        "history": [
            # 买 600789 100股@10,卖 600789 100股@11 → 已实现盈亏 (11-10)*100=100,买入费5+卖出费6
            {"type": "buy", "code": "600789", "name": "测试", "price": 10.0, "qty": 100, "amount": 1000.0, "fee": 5.0, "total": 1005.0, "time": today + "T10:00:00"},
            {"type": "sell", "code": "600789", "name": "测试", "price": 11.0, "qty": 100, "amount": 1100.0, "fee": 6.0, "total": 1094.0, "time": today + "T10:30:00"},
        ],
    }
    summary = review.summarize_account(account, ds)
    assert summary["today_realized_pnl"] == 100.0  # (11-10)*100
    assert summary["today_total_fee"] == 11.0  # 5+6


def test_summarize_account_positions_detail_includes_pnl():
    """positions_detail 每只持仓含浮亏。"""
    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 12.0, "name": "鲁信"}}
    account = {
        "initial_capital": 1000.0, "cash": 500.0,
        "positions": {"600789": {"qty": 100, "cost_price": 10.0, "name": "鲁信"}},
        "history": [],
    }
    summary = review.summarize_account(account, ds)
    detail = summary["positions_detail"]
    assert len(detail) == 1
    assert detail[0]["code"] == "600789"
    assert detail[0]["unrealized_pnl"] == 200.0  # (12-10)*100


def test_summarize_account_today_trades_summarized_fields():
    """today_trades 精简为关键字段(type/code/name/price/qty/fee)。"""
    ds = MagicMock()
    ds.get_realtime.return_value = {}
    today = date.today().isoformat()
    account = {
        "initial_capital": 1000.0, "cash": 1000.0, "positions": {},
        "history": [
            {"type": "buy", "code": "600789", "name": "测试", "price": 10.0, "qty": 100, "amount": 1000.0, "fee": 5.0, "total": 1005.0, "time": today + "T10:00:00", "extra": "冗余"},
        ],
    }
    summary = review.summarize_account(account, ds)
    trade = summary["today_trades"][0]
    # 关键字段保留
    assert trade["type"] == "buy"
    assert trade["code"] == "600789"
    assert trade["price"] == 10.0
    assert trade["qty"] == 100
    assert trade["fee"] == 5.0
    # 冗余字段剔除
    assert "extra" not in trade
    assert "total" not in trade


def test_generate_review_uses_screener_sectors_when_data_sectors_empty(monkeypatch):
    """get_sectors 空(走 data.py 正则 bug)时,降级用 screener._fetch_sina_sectors。"""
    from app.services import screener
    ai = MagicMock()
    ai.complete.return_value = "复盘内容"
    ds = MagicMock()
    ds.get_realtime.return_value = {}
    ds.get_sectors.return_value = []  # 模拟 data.py bug
    fake_sectors = [{"name": "半导体", "change_pct": 3.5, "leader_stock": "中芯"}]
    monkeypatch.setattr(screener, "_fetch_sina_sectors", lambda: fake_sectors)
    account = {"initial_capital": 1000.0, "cash": 1000.0, "positions": {}, "history": []}
    # 删归档避免命中缓存
    import os
    archived = review.load_archived(date.today().isoformat())
    if archived:
        (review.state.DATA_DIR / "reviews" / f"{date.today().isoformat()}.md").unlink()
    review.generate_review(account, ds, ai)
    # 验证 sectors 出现在 prompt 里
    all_text = " ".join(str(c) for c in ai.complete.call_args.args) + " ".join(str(v) for v in ai.complete.call_args.kwargs.values())
    assert "半导体" in all_text
