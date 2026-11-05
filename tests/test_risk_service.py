from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import risk


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(risk, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def stub_watchlist(monkeypatch):
    """自选股含一只设了阈值的股票。"""
    monkeypatch.setattr(risk, "load_watchlist_meta", lambda: {
        "600789": {"name": "鲁信创投", "up_alert_pct": 5.0, "down_alert_pct": -3.0}
    })


def test_scan_detects_down_threshold():
    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 9.5, "change_pct": -5.0, "name": "鲁信创投"}}
    ds.get_kline.return_value = []
    alerts = risk.scan(ds)
    assert len(alerts) == 1
    assert alerts[0]["code"] == "600789"
    assert "down_threshold" in alerts[0]["rules"]


def test_scan_detects_up_threshold():
    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 11.0, "change_pct": 6.0, "volume": 100, "name": "鲁信创投"}}
    ds.get_kline.return_value = []
    alerts = risk.scan(ds)
    assert "up_threshold" in alerts[0]["rules"]


def test_scan_detects_volume_spike():
    """放量异常:K线最后一天量 > 前5日均量*2。"""
    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 10.0, "change_pct": 0.5, "volume": 100, "name": "鲁信创投"}}
    # 前 5 天量 1000,最后一天放量到 3000(>1000*2)
    klines = [{"date": f"2026-06-{i:02d}", "close": 10, "volume": 1000} for i in range(1, 10)]
    klines.append({"date": "2026-06-10", "close": 10.5, "open": 10, "high": 10.5, "low": 10, "volume": 3000})
    ds.get_kline.return_value = klines
    alerts = risk.scan(ds)
    vol_alerts = [a for a in alerts if "volume_spike" in a["rules"]]
    assert len(vol_alerts) == 1


def test_scan_detects_ma_break():
    """破均线:现价跌破 20日均线。"""
    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 8.0, "change_pct": -2.0, "volume": 100, "name": "鲁信创投"}}
    ds.get_kline.return_value = [{"date": f"2026-06-{i:02d}", "close": 10, "volume": 100} for i in range(1, 21)]
    alerts = risk.scan(ds)
    ma_alerts = [a for a in alerts if "ma_break" in a["rules"]]
    assert len(ma_alerts) == 1


def test_scan_no_alert_when_quiet():
    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 10.0, "change_pct": 0.5, "volume": 100, "name": "鲁信创投"}}
    ds.get_kline.return_value = [{"date": f"2026-06-{i:02d}", "close": 10, "volume": 100} for i in range(1, 21)]
    alerts = risk.scan(ds)
    assert alerts == []


def test_scan_archives_alerts(isolated_data_dir):
    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 9.0, "change_pct": -5.0, "volume": 100, "name": "鲁信创投"}}
    ds.get_kline.return_value = []
    risk.scan(ds)
    files = list((isolated_data_dir / "alerts").glob("*.json")) if (isolated_data_dir / "alerts").exists() else []
    assert len(files) >= 1


def test_scan_handles_empty_watchlist(monkeypatch):
    monkeypatch.setattr(risk, "load_watchlist_meta", lambda: {})
    ds = MagicMock()
    alerts = risk.scan(ds)
    assert alerts == []
