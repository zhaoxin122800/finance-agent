"""screener(选股器)service 测试。"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

from app.services import screener


def test_hot_stocks_returns_dragon_tiger_list():
    """hot_stocks 包装 daily_dragon_tiger,返回股票列表。"""
    fake = {
        "date": "2026-06-23",
        "total_records": 2,
        "stocks": [
            {"code": "600353", "name": "旭光电子", "reason": "涨幅偏离值", "close": 48.8, "change_pct": 5.6, "net_buy_wan": 193759.9, "turnover_pct": 12.3},
            {"code": "002475", "name": "立讯精密", "reason": "日振幅值", "close": 38.5, "change_pct": -2.1, "net_buy_wan": -5000, "turnover_pct": 8.1},
        ],
    }
    with patch("app.services.screener.a_stock_data") as mock_asd:
        mock_asd.daily_dragon_tiger.return_value = fake
        result = screener.hot_stocks()
    assert result["date"] == "2026-06-23"
    assert len(result["stocks"]) == 2
    assert result["stocks"][0]["code"] == "600353"


def test_hot_stocks_failure_returns_empty():
    """数据源失败时返回空结构,不抛。"""
    with patch("app.services.screener.a_stock_data") as mock_asd:
        mock_asd.daily_dragon_tiger.side_effect = RuntimeError("net")
        result = screener.hot_stocks()
    assert result["stocks"] == []
    assert result["total_records"] == 0


def test_hot_stocks_respects_limit():
    """limit 限制返回条数(默认 30)。"""
    fake_stocks = [{"code": f"60000{i}", "name": f"股{i}", "close": 10, "change_pct": 5, "net_buy_wan": 1000, "reason": "x", "turnover_pct": 5} for i in range(50)]
    with patch("app.services.screener.a_stock_data") as mock_asd:
        mock_asd.daily_dragon_tiger.return_value = {"date": "2026-06-23", "total_records": 50, "stocks": fake_stocks}
        result = screener.hot_stocks(limit=10)
    assert len(result["stocks"]) == 10


def test_sector_ranking_sorts_by_change_pct(monkeypatch):
    """sector_ranking 按涨跌幅降序排序。"""
    fake = [
        {"name": "半导体", "change_pct": 3.5, "leader_stock": "中芯国际"},
        {"name": "银行", "change_pct": -0.5, "leader_stock": "工商银行"},
        {"name": "白酒", "change_pct": 2.1, "leader_stock": "贵州茅台"},
    ]
    monkeypatch.setattr(screener, "_fetch_sina_sectors", lambda: fake)
    result = screener.sector_ranking()
    assert result[0]["name"] == "半导体"
    assert result[1]["name"] == "白酒"
    assert result[2]["name"] == "银行"


def test_sector_ranking_failure_returns_empty(monkeypatch):
    """_fetch_sina_sectors 失败时返回空。"""
    monkeypatch.setattr(screener, "_fetch_sina_sectors", lambda: [])
    assert screener.sector_ranking() == []


# ============================================================
# 全市场选股器
# ============================================================

_FAKE_SINA_PAGE = [
    {"symbol": "sh600519", "code": "600519", "name": "贵州茅台", "trade": "1680.0", "changepercent": "2.5", "volume": "12345", "amount": "200000000", "per": "30.0", "pb": "10.0", "mktcap": "2100000000000", "nmc": "2100000000000", "turnoverratio": "0.5"},
    {"symbol": "sz000001", "code": "000001", "name": "平安银行", "trade": "11.5", "changepercent": "-1.2", "volume": "500000", "amount": "575000000", "per": "4.5", "pb": "0.5", "mktcap": "223000000000", "nmc": "223000000000", "turnoverratio": "1.8"},
]


def test_market_list_maps_sina_fields(monkeypatch):
    """market_list 把新浪字段映射成统一结构。"""
    def fake(page, num, sort, asc):
        return _FAKE_SINA_PAGE if page == 1 else []  # 只首页有数据
    monkeypatch.setattr(screener, "_fetch_sina_market_page", fake)
    result = screener.market_list(page=1, num=10)
    assert result["total_returned"] == 2
    stock = result["stocks"][0]
    assert stock["code"] == "600519"
    assert stock["name"] == "贵州茅台"
    assert stock["price"] == 1680.0
    assert stock["change_pct"] == 2.5
    assert stock["pe"] == 30.0
    assert stock["pb"] == 10.0
    assert stock["market_cap"] == 21000.0  # mktcap 2100000000000元 → 21000亿


def test_market_list_supports_sort(monkeypatch):
    """sort 参数透传给数据源。"""
    captured = {}
    def fake(page, num, sort, asc):
        captured["sort"] = sort
        captured["asc"] = asc
        return _FAKE_SINA_PAGE
    monkeypatch.setattr(screener, "_fetch_sina_market_page", fake)
    screener.market_list(sort="turnoverratio", asc=False)
    assert captured["sort"] == "turnoverratio"
    assert captured["asc"] is False


def test_market_list_search_filters_by_code_or_name(monkeypatch):
    """query 参数走 suggest 接口全市场搜索(不再只搜涨幅榜)。
    格式:var suggestdata="名称,类型,代码,符号,简称,...;..."
    只保留 A 股(类型 11=沪/12=深,过滤掉 31 港股/22 美股等)。
    """
    fake_suggest = 'var suggestdata="贵州茅台,11,600519,sh600519,贵州茅台,,贵州茅台,1,1,,,;茅台啤酒,12,600600,sh600600,茅台啤酒,,茅台啤酒,1,1,,,";'
    monkeypatch.setattr(screener, "_fetch_sina_suggest", lambda key: fake_suggest)
    result = screener.market_list(query="茅台")
    assert result["total_returned"] == 2
    assert result["stocks"][0]["code"] == "600519"
    assert result["stocks"][0]["name"] == "贵州茅台"


def test_market_list_search_only_a_shares(monkeypatch):
    """suggest 返回港股/美股时应过滤,只留 A 股(类型 11/12)。"""
    fake = 'var suggestdata="工商银行,31,01398,03998,工商银行,,;工商银行,11,601398,sh601398,工商银行,,;招商银行,12,600036,sh600036,招商银行,,";'
    monkeypatch.setattr(screener, "_fetch_sina_suggest", lambda key: fake)
    result = screener.market_list(query="工商")
    assert result["total_returned"] == 2  # 港股 01398 被过滤
    codes = [s["code"] for s in result["stocks"]]
    assert "601398" in codes
    assert "600036" in codes
    assert "01398" not in codes


def test_market_list_search_failure_returns_empty(monkeypatch):
    """suggest 接口失败时返回空。"""
    monkeypatch.setattr(screener, "_fetch_sina_suggest", lambda key: "")
    result = screener.market_list(query="不存在的词")
    assert result["stocks"] == []


def test_market_list_failure_returns_empty(monkeypatch):
    """数据源失败时返回空结构。"""
    monkeypatch.setattr(screener, "_fetch_sina_market_page", lambda *a, **k: [])
    result = screener.market_list()
    assert result["stocks"] == []
    assert result["total_returned"] == 0
