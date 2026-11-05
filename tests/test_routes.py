"""routes 层冒烟测试 —— FastAPI TestClient。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


PAGES = [
    ("/", "首页"),
    ("/watchlist", "自选股"),
    ("/analyst", "个股分析"),
    ("/account", "虚拟账户"),
    ("/review", "每日复盘"),
    ("/policy", "政策监控"),
    ("/report", "研报提炼"),
    ("/backtest", "策略回测"),
    ("/risk", "风险预警"),
]


@pytest.mark.parametrize("path,name", PAGES)
def test_all_pages_return_200(client, path, name):
    """8 个功能页 + 首页都应返回 200。"""
    resp = client.get(path)
    assert resp.status_code == 200, f"{name}({path}) 返回 {resp.status_code}"


def test_index_shows_all_nav_tabs(client):
    """首页 HTML 应包含 8 个导航 tab。"""
    resp = client.get("/")
    tabs = ["自选股", "个股分析", "虚拟账户", "每日复盘", "政策监控", "研报提炼", "策略回测", "风险预警"]
    for tab in tabs:
        assert tab in resp.text, f"首页缺少导航 tab: {tab}"
