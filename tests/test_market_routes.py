"""watchlist + analyst 路由冒烟测试。"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_watchlist_page_returns_200(client):
    with patch("app.routes.watchlist.get_watchlist_with_quotes", return_value=[]):
        resp = client.get("/watchlist")
    assert resp.status_code == 200
    assert "自选股" in resp.text


def test_watchlist_api_quotes_returns_json(client):
    with patch("app.routes.watchlist.get_watchlist_with_quotes", return_value=[{"code": "600789", "price": 10.5}]):
        resp = client.get("/watchlist/api/quotes")
    assert resp.status_code == 200
    assert resp.json() == [{"code": "600789", "price": 10.5}]


def test_watchlist_add_post(client):
    with patch("app.routes.watchlist.add_stock") as mock_add:
        resp = client.post("/watchlist/api/add", data={"code": "600789", "name": "鲁信创投"})
    assert resp.status_code in (200, 303)
    mock_add.assert_called_once()


def test_watchlist_add_with_empty_thresholds_no_422(client):
    """表单带空的阈值字段(全市场选股器场景)不应 422。"""
    with patch("app.routes.watchlist.add_stock") as mock_add:
        resp = client.post("/watchlist/api/add", data={"code": "600519", "name": "贵州茅台", "up_alert_pct": "", "down_alert_pct": ""})
    assert resp.status_code in (200, 303), f"期望 200/303,实际 {resp.status_code}"
    mock_add.assert_called_once_with("600519", "贵州茅台", None, None)


def test_watchlist_add_without_threshold_fields(client):
    """表单完全不带阈值字段(只 code+name)也应成功。"""
    with patch("app.routes.watchlist.add_stock") as mock_add:
        resp = client.post("/watchlist/api/add", data={"code": "000001", "name": "平安银行"})
    assert resp.status_code in (200, 303)
    mock_add.assert_called_once_with("000001", "平安银行", None, None)


def test_watchlist_add_invalid_threshold_treated_as_none(client):
    """非法阈值字符串(如 'abc')应转为 None,不报错。"""
    with patch("app.routes.watchlist.add_stock") as mock_add:
        resp = client.post("/watchlist/api/add", data={"code": "600519", "name": "茅台", "up_alert_pct": "abc", "down_alert_pct": "5.0"})
    assert resp.status_code in (200, 303)
    mock_add.assert_called_once_with("600519", "茅台", None, 5.0)


def test_watchlist_remove_post(client):
    with patch("app.routes.watchlist.remove_stock") as mock_remove:
        resp = client.post("/watchlist/api/remove", data={"code": "600789"})
    assert resp.status_code in (200, 303)
    mock_remove.assert_called_once()


def test_analyst_page_returns_200(client):
    fake_data = {"code": "600789", "realtime": {"name": "鲁信创投", "price": 10.5}, "kline": [], "money_flow": {}, "minute_analysis": {}, "on_top_list": False, "top_list_reason": ""}
    with patch("app.routes.analyst.assemble", return_value=fake_data):
        resp = client.get("/analyst/600789")
    assert resp.status_code == 200
    assert "600789" in resp.text


def test_analyst_index_without_code_shows_form(client):
    resp = client.get("/analyst")
    assert resp.status_code == 200
