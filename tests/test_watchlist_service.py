"""watchlist service 测试 —— 全 mock DataSource,不打网络。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services import watchlist


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    # watchlist 通过 state.load_json/save_json 读写,实际 DATA_DIR 在 state 模块
    from app.services import state
    monkeypatch.setattr(state, "DATA_DIR", tmp_path)
    yield tmp_path


@pytest.fixture
def fake_ds():
    return MagicMock()


def test_empty_watchlist_returns_empty_list(fake_ds):
    """无自选股时返回 []。"""
    ds = fake_ds
    result = watchlist.get_watchlist_with_quotes(ds)
    assert result == []


def test_add_stock_persists_to_watchlist(fake_ds):
    ds = fake_ds
    watchlist.add_stock("600789", "鲁信创投")
    saved = watchlist.load_watchlist()
    assert "600789" in saved
    assert saved["600789"]["name"] == "鲁信创投"


def test_add_stock_with_thresholds(fake_ds):
    ds = fake_ds
    watchlist.add_stock("600789", "鲁信创投", up_alert_pct=5.0, down_alert_pct=-3.0)
    saved = watchlist.load_watchlist()
    assert saved["600789"]["up_alert_pct"] == 5.0
    assert saved["600789"]["down_alert_pct"] == -3.0


def test_add_duplicate_stock_updates_name_and_thresholds(fake_ds):
    ds = fake_ds
    watchlist.add_stock("600789", "旧名")
    watchlist.add_stock("600789", "新名", up_alert_pct=8.0)
    saved = watchlist.load_watchlist()
    assert saved["600789"]["name"] == "新名"
    assert saved["600789"]["up_alert_pct"] == 8.0


def test_remove_stock(fake_ds):
    ds = fake_ds
    watchlist.add_stock("600789", "鲁信创投")
    watchlist.add_stock("002446", "纳思达")
    watchlist.remove_stock("600789")
    saved = watchlist.load_watchlist()
    assert "600789" not in saved
    assert "002446" in saved


def test_set_thresholds(fake_ds):
    ds = fake_ds
    watchlist.add_stock("600789", "鲁信创投")
    watchlist.set_thresholds("600789", up_alert_pct=7.0, down_alert_pct=None)
    saved = watchlist.load_watchlist()
    assert saved["600789"]["up_alert_pct"] == 7.0
    assert saved["600789"]["down_alert_pct"] is None


def test_get_watchlist_with_quotes_merges_realtime(fake_ds):
    """装配:把 watchlist 的 name/threshold 与实时行情合并。"""
    ds = fake_ds
    ds.get_realtime.return_value = {
        "600789": {"code": "600789", "name": "鲁信创投", "price": 10.5, "change_pct": 1.2, "volume": 1000},
    }
    watchlist.add_stock("600789", "鲁信创投", up_alert_pct=5.0)
    result = watchlist.get_watchlist_with_quotes(ds)
    assert len(result) == 1
    item = result[0]
    assert item["code"] == "600789"
    assert item["price"] == 10.5
    assert item["change_pct"] == 1.2
    assert item["up_alert_pct"] == 5.0


def test_get_watchlist_handles_missing_realtime(fake_ds):
    """行情取不到(code 错误或停牌)时该行 price=None,不崩。"""
    ds = fake_ds
    ds.get_realtime.return_value = {}  # 全空
    watchlist.add_stock("600789", "鲁信创投")
    result = watchlist.get_watchlist_with_quotes(ds)
    assert len(result) == 1
    assert result[0]["price"] is None
    assert result[0]["code"] == "600789"


def test_get_watchlist_alerts_when_threshold_breached(fake_ds):
    """涨跌幅超过阈值时 alert 字段非空。"""
    ds = fake_ds
    ds.get_realtime.return_value = {
        "600789": {"code": "600789", "price": 11.0, "change_pct": 6.5, "volume": 100, "name": "鲁信创投"},
    }
    watchlist.add_stock("600789", "鲁信创投", up_alert_pct=5.0)
    result = watchlist.get_watchlist_with_quotes(ds)
    assert result[0]["alert"] == "up"  # 6.5 > 5.0


def test_get_watchlist_no_alert_within_threshold(fake_ds):
    ds = fake_ds
    ds.get_realtime.return_value = {
        "600789": {"code": "600789", "price": 10.1, "change_pct": 1.0, "volume": 100, "name": "鲁信创投"},
    }
    watchlist.add_stock("600789", "鲁信创投", up_alert_pct=5.0, down_alert_pct=-3.0)
    result = watchlist.get_watchlist_with_quotes(ds)
    assert result[0]["alert"] is None
