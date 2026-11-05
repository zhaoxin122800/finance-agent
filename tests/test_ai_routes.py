"""AI 路由冒烟测试。"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_analyst_interpret_post_returns_markdown(client):
    fake_data = {"code": "600789", "realtime": {"name": "鲁信创投", "price": 10.5}, "kline": [], "money_flow": {}, "minute_analysis": {}, "on_top_list": False, "top_list_reason": ""}
    with patch("app.routes.analyst.assemble", return_value=fake_data), \
         patch("app.routes.analyst.interpret_stock", return_value="## AI 解读内容") as mock_interp:
        resp = client.post("/analyst/600789/interpret")
    assert resp.status_code == 200
    assert "AI 解读内容" in resp.text
    mock_interp.assert_called_once()


def test_review_page_returns_200(client):
    with patch("app.routes.review.summarize_account", return_value={"total_assets": 1000, "cash": 1000, "market_value": 0, "total_pnl": 0, "total_pnl_pct": 0, "today_trades_count": 0}), \
         patch("app.routes.review.load_archived", return_value=None), \
         patch("app.routes.review.get_ai_client", return_value=None):
        resp = client.get("/review")
    assert resp.status_code == 200
    assert "复盘" in resp.text


def test_review_generate_post(client):
    with patch("app.routes.review.summarize_account", return_value={"total_assets": 1000, "cash": 1000, "market_value": 0, "total_pnl": 0, "total_pnl_pct": 0, "today_trades_count": 0}), \
         patch("app.routes.review.generate_review", return_value="## 复盘报告") as mock_gen:
        resp = client.post("/review/generate")
    assert resp.status_code == 200
    assert "复盘报告" in resp.text
    mock_gen.assert_called_once()
