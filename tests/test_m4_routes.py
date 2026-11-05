"""M4 路由冒烟(按 task 逐步补充)。"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


_EMPTY_VIEW = {"cash": 1000, "market_value": 0, "total_assets": 1000, "total_pnl": 0, "positions": []}


def test_account_page_200(client):
    with patch("app.routes.account.build_account_view", return_value=_EMPTY_VIEW), \
         patch("app.routes.account.history", return_value=[]):
        resp = client.get("/account")
    assert resp.status_code == 200
    assert "账户" in resp.text


def test_account_buy_post(client):
    with patch("app.routes.account.buy", return_value={"ok": True}) as mock_buy, \
         patch("app.routes.account.build_account_view", return_value=_EMPTY_VIEW), \
         patch("app.routes.account.history", return_value=[]):
        resp = client.post("/account/api/buy", data={"code": "600789", "qty": "100"})
    assert resp.status_code in (200, 303)
    mock_buy.assert_called_once()


def test_account_sell_post(client):
    with patch("app.routes.account.sell", return_value={"ok": True}) as mock_sell, \
         patch("app.routes.account.build_account_view", return_value=_EMPTY_VIEW), \
         patch("app.routes.account.history", return_value=[]):
        resp = client.post("/account/api/sell", data={"code": "600789", "qty": "100"})
    assert resp.status_code in (200, 303)
    mock_sell.assert_called_once()


def test_account_sell_all_empty_qty_no_422(client):
    """清仓场景:qty 空字段 + all=True 不应 422。"""
    with patch("app.routes.account.sell", return_value={"ok": True}) as mock_sell, \
         patch("app.routes.account.build_account_view", return_value=_EMPTY_VIEW), \
         patch("app.routes.account.history", return_value=[]):
        resp = client.post("/account/api/sell", data={"code": "600789", "qty": "", "all": "true"})
    assert resp.status_code in (200, 303), f"期望 200/303,实际 {resp.status_code}"
    mock_sell.assert_called_once_with("600789", qty=None, all_=True)


def test_account_buy_empty_amount_no_422(client):
    """买入:amount 空字段不应 422。"""
    with patch("app.routes.account.buy", return_value={"ok": True}) as mock_buy, \
         patch("app.routes.account.build_account_view", return_value=_EMPTY_VIEW), \
         patch("app.routes.account.history", return_value=[]):
        resp = client.post("/account/api/buy", data={"code": "600519", "qty": "100", "amount": ""})
    assert resp.status_code in (200, 303)
    mock_buy.assert_called_once_with("600519", qty=100, amount=None)


def test_account_buy_only_code_no_422(client):
    """买入:只填 code(无 qty 无 amount)不应 422。"""
    with patch("app.routes.account.buy", return_value={"ok": True}) as mock_buy, \
         patch("app.routes.account.build_account_view", return_value=_EMPTY_VIEW), \
         patch("app.routes.account.history", return_value=[]):
        resp = client.post("/account/api/buy", data={"code": "600519"})
    assert resp.status_code in (200, 303)
    mock_buy.assert_called_once_with("600519", qty=None, amount=None)


def test_policy_page_200(client):
    with patch("app.routes.policy.policy.search_news", return_value=[]), \
         patch("app.routes.policy.policy.daily_brief", return_value="日报"):
        resp = client.get("/policy")
    assert resp.status_code == 200


def test_report_page_200(client):
    with patch("app.routes.report.list_history", return_value=[]):
        resp = client.get("/report")
    assert resp.status_code == 200


def test_report_extract_text_post(client):
    with patch("app.routes.report.extract_and_save", return_value={"title": "x", "rating": "买入"}) as mock_ext, \
         patch("app.routes.report.list_history", return_value=[]):
        resp = client.post("/report/api/extract", data={"text": "某研报内容"})
    assert resp.status_code == 200
    assert "买入" in resp.text
    mock_ext.assert_called_once()


def test_backtest_page_200(client):
    resp = client.get("/backtest")
    assert resp.status_code == 200


def test_backtest_run_post(client):
    fake_result = {"error": None, "total_return_pct": 5.0, "max_drawdown_pct": -2.0, "sharpe": 1.2, "win_rate": 60.0, "trades": [], "equity_curve": [], "commission_paid": 10.0}
    with patch("app.routes.backtest.run", return_value=fake_result) as mock_run:
        resp = client.post("/backtest/run", data={"code": "600519", "strategy": "ma_cross", "start": "2026-01-01", "end": "2026-06-01"})
    assert resp.status_code == 200
    mock_run.assert_called_once()


def test_risk_page_200(client):
    with patch("app.routes.risk.scan", return_value=[]):
        resp = client.get("/risk")
    assert resp.status_code == 200
