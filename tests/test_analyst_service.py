"""analyst service 测试 —— mock DataSource + vendors.analyze。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import analyst


@pytest.fixture
def fake_ds():
    return MagicMock()


def test_assemble_returns_combined_data(fake_ds):
    """装配:realtime + kline + minute_analysis + money_flow + top_list。"""
    ds = fake_ds
    ds.get_realtime.return_value = {"600789": {"code": "600789", "name": "鲁信创投", "price": 10.5, "change_pct": 1.2}}
    ds.get_kline.return_value = [{"date": "2026-06-20", "open": 10.0, "high": 10.8, "low": 9.9, "close": 10.5, "volume": 1000}]
    ds.get_money_flow.return_value = {"main_net": 5000000, "super_large": 3000000, "large": 2000000, "medium": -500000, "small": -1000000}
    ds.get_top_list.return_value = [{"code": "600789", "name": "鲁信创投", "net_buy": 5000000, "reason": "日涨幅偏离值"}]

    with patch("app.services.analyst.analyze") as mock_analyze:
        mock_analyze.analyze_stock.return_value = {
            "code": "600789", "name": "鲁信创投", "realtime": {"price": 10.5},
            "minute_analysis": {"volume_profile": "放量上涨"},
        }
        result = analyst.assemble("600789", ds)

    assert result["code"] == "600789"
    assert result["realtime"]["price"] == 10.5
    assert len(result["kline"]) == 1
    assert result["money_flow"]["main_net"] == 5000000
    assert result["minute_analysis"]["volume_profile"] == "放量上涨"
    assert result["on_top_list"] is True


def test_assemble_handles_all_sources_failing(fake_ds):
    """所有数据源失败时返回带 error 的结构,不抛异常(设计 §8)。"""
    ds = fake_ds
    ds.get_realtime.return_value = {}
    ds.get_kline.return_value = []
    ds.get_money_flow.return_value = {}
    ds.get_top_list.return_value = []
    with patch("app.services.analyst.analyze") as mock_analyze:
        mock_analyze.analyze_stock.return_value = {"error": "无法获取行情"}
        result = analyst.assemble("000000", ds)
    assert result["code"] == "000000"
    assert result["realtime"] == {}
    assert result["kline"] == []
    assert result["error"] == "无法获取行情"


def test_assemble_includes_60_day_kline_by_default(fake_ds):
    """默认拉 60 日日 K(给 K线图用)。"""
    ds = fake_ds
    ds.get_realtime.return_value = {}
    ds.get_kline.return_value = []
    ds.get_money_flow.return_value = {}
    ds.get_top_list.return_value = []
    with patch("app.services.analyst.analyze") as mock_analyze:
        mock_analyze.analyze_stock.return_value = {"code": "600789", "realtime": {}}
        analyst.assemble("600789", ds)
    ds.get_kline.assert_called_once_with("600789", days=60, scale="240")


def test_assemble_detects_top_list_membership(fake_ds):
    """当 code 在龙虎榜里时 on_top_list=True 并附 reason。"""
    ds = fake_ds
    ds.get_realtime.return_value = {"600789": {"price": 10.5}}
    ds.get_kline.return_value = []
    ds.get_money_flow.return_value = {}
    ds.get_top_list.return_value = [{"code": "600789", "reason": "日涨幅偏离值7%"}]
    with patch("app.services.analyst.analyze") as mock_analyze:
        mock_analyze.analyze_stock.return_value = {"code": "600789", "realtime": {"price": 10.5}}
        result = analyst.assemble("600789", ds)
    assert result["on_top_list"] is True
    assert result["top_list_reason"] == "日涨幅偏离值7%"


def test_assemble_analyze_exception_is_caught(fake_ds):
    """vendors.analyze 抛异常时 assemble 不崩,error 字段记录原因。"""
    ds = fake_ds
    ds.get_realtime.return_value = {"600789": {"price": 10.5}}
    ds.get_kline.return_value = []
    ds.get_money_flow.return_value = {}
    ds.get_top_list.return_value = []
    with patch("app.services.analyst.analyze") as mock_analyze:
        mock_analyze.analyze_stock.side_effect = RuntimeError("analyze 内部错误")
        result = analyst.assemble("600789", ds)
    assert result["code"] == "600789"
    assert result["realtime"]["price"] == 10.5  # 其它字段不受影响
    assert "analyze 内部错误" in (result["error"] or "")
    assert result["minute_analysis"] == {}
