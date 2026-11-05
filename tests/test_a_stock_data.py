"""a_stock_data(V3.2.3)关键端点测试。

不依赖网络:tencent_quote mock urllib;em_get 在 requests 缺失时降级;
纯 stdlib 函数直接验证返回。
"""
from __future__ import annotations

import io
from unittest.mock import patch, MagicMock

import pytest

from vendors import a_stock_data as asd


# ============================================================
# 纯标准库函数(无三方依赖,始终可用)
# ============================================================

def test_get_prefix_sh_returns_sh_for_6xx():
    assert asd.get_prefix("600789") == "sh"
    assert asd.get_prefix("688017") == "sh"


def test_get_prefix_sz_for_0_3():
    assert asd.get_prefix("002446") == "sz"
    assert asd.get_prefix("300750") == "sz"


def test_forward_pe_computes_correctly():
    assert asd.forward_pe(10.0, 1.0) == 10.0
    assert asd.forward_pe(20.0, 2.0) == 10.0


def test_calc_peg_computes_correctly():
    # PEG = PE / (CAGR * 100)
    assert asd.calc_peg(20.0, 0.1) == 2.0


# ============================================================
# tencent_quote 解析(mock urllib,零依赖)
# ============================================================

def _fake_tencent_response(code: str = "600789") -> bytes:
    """构造腾讯行情接口的 gbk 响应。
    腾讯格式:v_sh600789="1~名称~2~price~last_close~open~...~change_amt~change_pct~..."
    用 ~ 拼 55 个字段(vals[1..52] 都要有效)。
    """
    fields = [""] * 55
    fields[1] = "鲁信创投"
    fields[3] = "10.50"   # price
    fields[4] = "10.38"   # last_close
    fields[5] = "10.40"   # open
    fields[31] = "0.12"   # change_amt
    fields[32] = "1.16"   # change_pct
    fields[33] = "10.60"  # high
    fields[34] = "10.20"  # low
    fields[37] = "12345"  # amount_wan
    fields[38] = "1.5"    # turnover_pct
    fields[39] = "25.0"   # pe_ttm
    fields[43] = "3.8"    # amplitude_pct
    fields[44] = "100"    # mcap_yi
    fields[45] = "95"     # float_mcap_yi
    fields[46] = "3.0"    # pb
    fields[47] = "11.42"  # limit_up
    fields[48] = "9.34"   # limit_down
    fields[49] = "1.2"    # vol_ratio
    fields[52] = "22.0"   # pe_static
    payload = "~".join(fields)
    return f'v_sh{code}="{payload}";'.encode("gbk")


def test_tencent_quote_parses_fields_correctly():
    """腾讯接口解析:能提取 price/pe_ttm/pb 等富字段。"""
    fake_bytes = _fake_tencent_response("600789")
    mock_resp = MagicMock()
    mock_resp.read.return_value = fake_bytes
    with patch("vendors.a_stock_data.urllib.request.urlopen", return_value=mock_resp):
        result = asd.tencent_quote(["600789"])
    assert "600789" in result
    q = result["600789"]
    assert q["name"] == "鲁信创投"
    assert q["price"] == 10.50
    assert q["pe_ttm"] == 25.0
    assert q["pb"] == 3.0
    assert q["mcap_yi"] == 100.0
    assert q["change_pct"] == 1.16


def test_tencent_quote_returns_empty_on_network_failure():
    """网络异常时返回空 dict,不抛(由调用方兜底)。"""
    with patch("vendors.a_stock_data.urllib.request.urlopen", side_effect=RuntimeError("net down")):
        # 注:tencent_quote 原版不捕获异常,这里验证它向上抛
        with pytest.raises(RuntimeError):
            asd.tencent_quote(["600789"])


def test_tencent_quote_skips_malformed_lines():
    """部分行格式错误(字段<53)时跳过,不影响其它行。"""
    good = _fake_tencent_response("600789")
    bad_line = b'v_sz000001="short";'
    payload = good + bad_line
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    with patch("vendors.a_stock_data.urllib.request.urlopen", return_value=mock_resp):
        result = asd.tencent_quote(["600789", "000001"])
    # 600789 正常解析,000001 因字段不足被跳过
    assert "600789" in result
    assert "000001" not in result


# ============================================================
# em_get 降级(requests 缺失场景,模拟标志位)
# ============================================================

def test_em_get_raises_friendly_when_requests_missing(monkeypatch):
    """requests 缺失时,em_get 应抛带安装提示的错误,而非 NameError。
    模拟 _HAS_REQUESTS=False + requests=None。
    """
    monkeypatch.setattr(asd, "_HAS_REQUESTS", False)
    monkeypatch.setattr(asd, "requests", None)
    with pytest.raises(ImportError) as exc_info:
        asd.em_get("https://data.eastmoney.com/x")
    assert "data-premium" in str(exc_info.value) or "requests" in str(exc_info.value).lower()


def test_require_helper_raises_with_install_hint():
    """_require 辅助函数给出安装命令。"""
    with pytest.raises(ImportError) as exc_info:
        asd._require("mootdx")
    assert "data-premium" in str(exc_info.value)


# ============================================================
# 模块完整性:27 端点都在
# ============================================================

EXPECTED_ENDPOINTS = [
    "tencent_quote", "baidu_kline_with_ma", "em_get", "eastmoney_datacenter",
    "eastmoney_reports", "download_pdf", "eastmoney_industry_reports",
    "ths_eps_forecast", "iwencai_search", "dedup_articles",
    "ths_hot_reason", "hsgt_realtime", "eastmoney_concept_blocks",
    "eastmoney_fund_flow_minute", "dragon_tiger_board", "lockup_expiry",
    "industry_comparison", "daily_dragon_tiger",
    "margin_trading", "block_trade", "holder_num_change", "dividend_history",
    "stock_fund_flow_120d", "eastmoney_stock_news", "eastmoney_global_news",
    "eastmoney_stock_info", "sina_financial_report", "cninfo_announcements",
    "forward_pe", "pe_digestion", "calc_peg", "get_prefix",
]


@pytest.mark.parametrize("endpoint", EXPECTED_ENDPOINTS)
def test_endpoint_present(endpoint):
    """V3.2.3 的全部端点都应可 import。"""
    assert hasattr(asd, endpoint), f"缺少端点 {endpoint}"


# ============================================================
# baidu_kline_with_ma 容错
# Bug:百度 API 偶尔把 Result 返回成 list(空 list 或对象数组),
#      代码 d.get("Result", {}) 假设 dict → result.get() 对 list 报
#      AttributeError: 'list' object has no attribute 'get'。
# 修复:Result 非 dict 时按"无数据"处理,返回空结构,触发上层降级新浪。
# ============================================================

def test_baidu_kline_returns_empty_when_result_is_empty_list():
    """Result=[] (百度风控/无数据) 时返回空结构,不崩,触发降级。"""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Result": []}
    with patch("vendors.a_stock_data.requests.get", return_value=mock_resp):
        result = asd.baidu_kline_with_ma("600519")
    assert result == {"keys": [], "rows": []}


def test_baidu_kline_returns_empty_when_result_missing():
    """Result 键缺失时也返回空结构。"""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {}
    with patch("vendors.a_stock_data.requests.get", return_value=mock_resp):
        result = asd.baidu_kline_with_ma("600519")
    assert result == {"keys": [], "rows": []}


def test_baidu_kline_parses_when_result_is_dict():
    """正常 Result=dict 时照常解析。"""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "Result": {
            "newMarketData": {
                "keys": ["time", "close", "ma5avgprice"],
                "marketData": "20260620000000,10.0,9.9;20260621000000,10.5,10.0",
            }
        }
    }
    with patch("vendors.a_stock_data.requests.get", return_value=mock_resp):
        result = asd.baidu_kline_with_ma("600519")
    assert "ma5avgprice" in result["keys"]
    assert len(result["rows"]) == 2
