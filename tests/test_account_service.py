"""account service 测试 —— mock vendors.sim_trade + DataSource。

关键契约:sim_trade.buy/sell 返回 {"ok": bool, "msg": str},
service 层据此上报结果(不吞错误)。失败不再误报 ok=True。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services import account


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    # account 通过 state.load_json 读写,实际 DATA_DIR 在 state 模块
    from app.services import state
    monkeypatch.setattr(state, "DATA_DIR", tmp_path)
    yield tmp_path


@pytest.fixture
def seeded_account_file(isolated_data_dir):
    """种子一个有效 sim_account.json。"""
    acct = {"initial_capital": 1000.0, "cash": 1000.0, "positions": {}, "history": [], "created_at": "2026-06-22", "updated_at": "2026-06-22"}
    (isolated_data_dir / "sim_account.json").write_text(json.dumps(acct), encoding="utf-8")


def test_load_account_returns_dict(seeded_account_file):
    acct = account.load_account()
    assert acct["cash"] == 1000.0
    assert acct["positions"] == {}


def test_load_account_returns_fresh_when_missing(isolated_data_dir):
    """文件不存在时返回初始账户。"""
    acct = account.load_account()
    assert acct["initial_capital"] == 100000.0  # 初始资金 10万(见 account_seed)


def test_account_view_computes_market_value(seeded_account_file, tmp_path):
    """装配持仓 + 实时价 → 总资产/盈亏。"""
    acct = account.load_account()
    acct["positions"] = {"600789": {"qty": 100, "cost_price": 10.0, "name": "鲁信创投"}}
    acct["cash"] = 500.0
    (tmp_path / "sim_account.json").write_text(json.dumps(acct), encoding="utf-8")

    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 12.0, "name": "鲁信创投"}}
    view = account.build_account_view(ds)
    assert view["cash"] == 500.0
    assert view["market_value"] == 1200.0
    assert view["total_assets"] == 1700.0
    assert view["total_pnl"] == 700.0
    pos_row = view["positions"][0]
    assert pos_row["code"] == "600789"
    assert pos_row["pnl_pct"] == 20.0  # (12/10 - 1)*100


def test_account_view_handles_empty_positions(seeded_account_file):
    """空仓时 market_value=0。"""
    ds = MagicMock()
    view = account.build_account_view(ds)
    assert view["market_value"] == 0.0
    assert view["positions"] == []


def test_buy_reports_ok_when_sim_trade_succeeds(seeded_account_file):
    """sim_trade.buy 返回 {ok:True} → service 上报 ok=True。"""
    with patch("app.services.account.sim_trade") as mock_st:
        mock_st.buy.return_value = {"ok": True, "msg": "买入成功"}
        result = account.buy("600789", qty=100)
    mock_st.buy.assert_called_once_with("600789", qty=100, amount=None)
    assert result["ok"] is True


def test_buy_reports_failure_when_sim_trade_returns_failure(seeded_account_file):
    """sim_trade.buy 返回 {ok:False}(资金不足/不足1手)→ service 必须上报 ok=False,不能吞。"""
    with patch("app.services.account.sim_trade") as mock_st:
        mock_st.buy.return_value = {"ok": False, "msg": "资金不足！需要 5002.05 元，账户仅有 1000.00 元"}
        result = account.buy("600789", qty=100)
    assert result["ok"] is False
    assert "资金不足" in result["error"]


def test_buy_reports_failure_when_sim_trade_returns_none(seeded_account_file):
    """防御:sim_trade 返回 None(旧契约)→ 视为失败,不误报成功。"""
    with patch("app.services.account.sim_trade") as mock_st:
        mock_st.buy.return_value = None
        result = account.buy("600789", qty=100)
    assert result["ok"] is False


def test_buy_reports_error_when_sim_trade_raises(seeded_account_file):
    with patch("app.services.account.sim_trade") as mock_st:
        mock_st.buy.side_effect = RuntimeError("资金不足")
        result = account.buy("600789", qty=100)
    assert result["ok"] is False
    assert "资金不足" in result["error"]


def test_sell_reports_ok_when_sim_trade_succeeds(seeded_account_file):
    with patch("app.services.account.sim_trade") as mock_st:
        mock_st.sell.return_value = {"ok": True, "msg": "卖出成功"}
        result = account.sell("600789", qty=100)
    mock_st.sell.assert_called_once_with("600789", qty=100, all=False)
    assert result["ok"] is True


def test_sell_reports_failure_when_sim_trade_returns_failure(seeded_account_file):
    """卖超/未持仓 → service 必须上报 ok=False。"""
    with patch("app.services.account.sim_trade") as mock_st:
        mock_st.sell.return_value = {"ok": False, "msg": "持仓不足！持有 100 股，试图卖出 200 股"}
        result = account.sell("600789", qty=200)
    assert result["ok"] is False
    assert "持仓不足" in result["error"]


def test_sell_all_flag_passed(seeded_account_file):
    """all=True 清仓标记透传。"""
    with patch("app.services.account.sim_trade") as mock_st:
        mock_st.sell.return_value = {"ok": True, "msg": "ok"}
        account.sell("600789", all_=True)
    mock_st.sell.assert_called_once_with("600789", qty=None, all=True)


def test_history_returns_account_history(seeded_account_file, tmp_path):
    acct = account.load_account()
    acct["history"] = [{"type": "buy", "code": "600789", "time": "2026-06-22T10:00:00"}]
    (tmp_path / "sim_account.json").write_text(json.dumps(acct), encoding="utf-8")
    history = account.history()
    assert len(history) == 1
    assert history[0]["code"] == "600789"
