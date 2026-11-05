"""datasources 层测试 —— 全部 mock vendors,不打网络。"""
from __future__ import annotations

import inspect

from app.datasources.base import DataSource


def test_datasource_protocol_has_required_methods():
    """DataSource 必须定义设计 6.1 的全部方法。"""
    methods = {
        "get_realtime",
        "get_kline",
        "get_minute",
        "get_sectors",
        "get_money_flow",
        "get_top_list",
    }
    for name in methods:
        assert hasattr(DataSource, name), f"DataSource 缺少方法 {name}"


def test_get_realtime_signature():
    """get_realtime(codes) -> dict[str, dict]。Protocol 方法签名含 self,codes 应在其后。"""
    sig = inspect.signature(DataSource.get_realtime)
    params = list(sig.parameters.keys())
    assert "codes" in params
    # self 之后的第一个参数就是 codes
    non_self = [p for p in params if p != "self"]
    assert non_self[0] == "codes"


import time
from unittest.mock import patch

from app.datasources.free_source import FreeSource


# ============================================================
# get_realtime 降级链:腾讯(主) → 新浪(备) → 空
# ============================================================

TENCENT_PAYLOAD = {"600789": {"code": "600789", "name": "鲁信创投", "price": 10.5, "pe_ttm": 25.0, "pb": 3.0}}
SINA_PAYLOAD = {"600789": {"code": "600789", "name": "鲁信创投", "price": 10.5, "change_pct": 1.2}}


def test_realtime_uses_tencent_first():
    """腾讯成功时不调新浪,返回腾讯的富字段(含 pe_ttm)。"""
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.data") as mock_data:
        mock_asd.tencent_quote.return_value = TENCENT_PAYLOAD
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_realtime(["600789"])
    mock_asd.tencent_quote.assert_called_once_with(["600789"])
    mock_data.get_realtime.assert_not_called()
    assert result["600789"]["pe_ttm"] == 25.0


def test_realtime_falls_back_to_sina_when_tencent_empty():
    """腾讯返回空(非异常)时降级到新浪。"""
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.data") as mock_data:
        mock_asd.tencent_quote.return_value = {}  # 空结果
        mock_data.get_realtime.return_value = SINA_PAYLOAD
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_realtime(["600789"])
    mock_data.get_realtime.assert_called_once_with(["600789"])
    assert result["600789"]["change_pct"] == 1.2


def test_realtime_falls_back_to_sina_on_tencent_exception():
    """腾讯抛异常时降级到新浪。"""
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.data") as mock_data:
        mock_asd.tencent_quote.side_effect = RuntimeError("tencent down")
        mock_data.get_realtime.return_value = SINA_PAYLOAD
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_realtime(["600789"])
    assert result == SINA_PAYLOAD


def test_realtime_returns_empty_when_both_fail():
    """腾讯+新浪都失败时返回 {}(设计 §8 兜底)。"""
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.data") as mock_data:
        mock_asd.tencent_quote.side_effect = RuntimeError("tencent down")
        mock_data.get_realtime.side_effect = RuntimeError("sina down")
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_realtime(["600789"])
    assert result == {}


def test_realtime_returns_empty_when_both_empty():
    """腾讯+新浪都返回空时返回 {}。"""
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.data") as mock_data:
        mock_asd.tencent_quote.return_value = {}
        mock_data.get_realtime.return_value = {}
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_realtime(["600789"])
    assert result == {}


def test_realtime_empty_codes_returns_empty_without_call():
    """空 codes 列表不调任何源。"""
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.data") as mock_data:
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_realtime([])
    assert result == {}
    mock_asd.tencent_quote.assert_not_called()
    mock_data.get_realtime.assert_not_called()


# ============================================================
# 缓存(降级链结果缓存,行为不变)
# ============================================================

def test_realtime_cache_hits_within_ttl():
    """TTL 内第二次调用不应再打腾讯。"""
    with patch("app.datasources.free_source.a_stock_data") as mock_asd:
        mock_asd.tencent_quote.return_value = TENCENT_PAYLOAD
        ds = FreeSource(cache_ttl_realtime=30)
        ds.get_realtime(["600789"])
        ds.get_realtime(["600789"])
    assert mock_asd.tencent_quote.call_count == 1


def test_realtime_cache_misses_after_ttl():
    """TTL 过期后应重新打腾讯。"""
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.time") as mock_time:
        mock_time.time.side_effect = [0, 0, 100]
        mock_asd.tencent_quote.return_value = TENCENT_PAYLOAD
        ds = FreeSource(cache_ttl_realtime=30)
        ds.get_realtime(["600789"])  # miss -> 记 0
        ds.get_realtime(["600789"])  # hit (now=0 < 30)
        ds.get_realtime(["600789"])  # miss (now=100 >= 30)
    assert mock_asd.tencent_quote.call_count == 2


def test_realtime_cache_keyed_by_sorted_codes():
    """不同代码顺序的同一批应命中缓存。"""
    payload = {"600789": {"price": 10.5}, "002446": {"price": 20.0}}
    with patch("app.datasources.free_source.a_stock_data") as mock_asd:
        mock_asd.tencent_quote.return_value = payload
        ds = FreeSource(cache_ttl_realtime=30)
        ds.get_realtime(["600789", "002446"])
        ds.get_realtime(["002446", "600789"])
    assert mock_asd.tencent_quote.call_count == 1


# ============================================================
# get_kline 降级链:百度(主,带MA) → 新浪(备)
# ============================================================

# 百度返回格式:keys 是逗号分隔列名,rows 每条是逗号分隔值字符串
BAIDU_RAW = {
    "keys": "time,open,close,high,low,volume,amount,ma5avgprice,ma10avgprice,ma20avgprice",
    "rows": [
        "20260618000000,10.0,10.2,10.3,9.9,1000,10200,10.1,10.0,9.8",
        "20260619000000,10.2,10.5,10.6,10.1,1500,15750,10.2,10.1,9.9",
        "20260620000000,10.5,10.4,10.7,10.3,1200,12480,10.3,10.2,10.0",
    ],
}
SINA_KLINE = [{"date": "2026-06-20", "open": 10.5, "close": 10.4, "high": 10.7, "low": 10.3, "volume": 1200}]


def test_parse_baidu_kline_basic():
    """百度格式解析:keys 定位列,rows 转 list[dict]。"""
    from app.datasources.free_source import _parse_baidu_kline
    parsed = _parse_baidu_kline(BAIDU_RAW)
    assert len(parsed) == 3
    first = parsed[0]
    assert first["date"] == "2026-06-18"  # 20260618 -> YYYY-MM-DD
    assert first["open"] == 10.0
    assert first["close"] == 10.2
    assert first["ma5"] == 10.1
    assert first["ma10"] == 10.0
    assert first["ma20"] == 9.8


def test_parse_baidu_kline_skips_malformed_rows():
    """单行格式错误(列数不符)时跳过,不影响其它行。"""
    from app.datasources.free_source import _parse_baidu_kline
    raw = {
        "keys": "time,open,close",
        "rows": ["20260620000000,10.0,10.5", "bad,row", "20260621000000,10.5,10.8"],
    }
    parsed = _parse_baidu_kline(raw)
    assert len(parsed) == 2  # bad,row 被跳过
    assert parsed[1]["close"] == 10.8


def test_parse_baidu_kline_returns_empty_on_bad_input():
    from app.datasources.free_source import _parse_baidu_kline
    assert _parse_baidu_kline({}) == []
    assert _parse_baidu_kline({"keys": "", "rows": []}) == []


def test_kline_uses_baidu_first_returns_ma():
    """百度成功时不调新浪,返回带 ma5 的 K线。"""
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.data") as mock_data:
        mock_asd.baidu_kline_with_ma.return_value = BAIDU_RAW
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_kline("600789", days=30, scale="240")
    mock_asd.baidu_kline_with_ma.assert_called_once_with("600789")
    mock_data.get_kline.assert_not_called()
    assert len(result) == 3
    assert "ma5" in result[0]


def test_kline_falls_back_to_sina_on_baidu_exception():
    """百度抛异常时降级新浪。"""
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.data") as mock_data:
        mock_asd.baidu_kline_with_ma.side_effect = RuntimeError("baidu down")
        mock_data.get_kline.return_value = SINA_KLINE
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_kline("600789", days=30, scale="240")
    assert result == SINA_KLINE


def test_kline_falls_back_to_sina_when_baidu_empty():
    """百度返回空 rows 时降级新浪。"""
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.data") as mock_data:
        mock_asd.baidu_kline_with_ma.return_value = {"keys": "time,open", "rows": []}
        mock_data.get_kline.return_value = SINA_KLINE
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_kline("600789", days=30, scale="240")
    assert result == SINA_KLINE


def test_kline_returns_empty_when_both_fail():
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.data") as mock_data:
        mock_asd.baidu_kline_with_ma.side_effect = RuntimeError("baidu")
        mock_data.get_kline.side_effect = RuntimeError("sina")
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_kline("600789", days=30, scale="240")
    assert result == []


# ============================================================
# get_money_flow 失败口径:返回全0结构(与 data.py 一致),非空 {}
# 这样消费方能区分"无数据"(全0)而非"结构缺失"({})
# ============================================================

def test_money_flow_failure_returns_zero_dict():
    """失败时返回全0结构,非 {}(与 data.get_money_flow 失败口径一致)。"""
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.data") as mock_data:
        mock_asd.eastmoney_fund_flow_minute.side_effect = RuntimeError("asd net")
        mock_data.get_money_flow.side_effect = RuntimeError("net")
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_money_flow("600789")
    assert result == {"main_net": 0, "super_large": 0, "large": 0, "medium": 0, "small": 0}


# ============================================================
# get_money_flow 降级链:东财防封(主,取最新分钟) → 新浪(备) → 全0
# 新浪接口经常被风控断连,a_stock_data 的 eastmoney_fund_flow_minute 带 em_get 限流更稳
# ============================================================

def test_money_flow_uses_eastmoney_first_takes_latest_minute():
    """东财分钟资金流(主):取最新一条,字段映射到统一结构。"""
    fake_minute_data = [
        {"time": "2026-06-23 09:31", "main_net": 1000, "small_net": -200, "mid_net": 300, "large_net": 500, "super_net": 400},
        {"time": "2026-06-23 15:00", "main_net": 5000000, "small_net": -1000000, "mid_net": -500000, "large_net": 2000000, "super_net": 3000000},
    ]
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.data") as mock_data:
        mock_asd.eastmoney_fund_flow_minute.return_value = fake_minute_data
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_money_flow("600519")
    # 应取最新一条(15:00 的)
    assert result["main_net"] == 5000000
    # 字段映射:super_net→super_large, large_net→large, mid_net→medium, small_net→small
    assert result["super_large"] == 3000000
    assert result["large"] == 2000000
    assert result["medium"] == -500000
    assert result["small"] == -1000000
    mock_data.get_money_flow.assert_not_called()


def test_money_flow_falls_back_to_sina_when_eastmoney_empty():
    """东财返回空 list 时降级新浪。"""
    sina_data = {"main_net": 999, "super_large": 1, "large": 2, "medium": 3, "small": 4}
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.data") as mock_data:
        mock_asd.eastmoney_fund_flow_minute.return_value = []
        mock_data.get_money_flow.return_value = sina_data
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_money_flow("600519")
    assert result == sina_data


def test_money_flow_falls_back_to_sina_on_eastmoney_exception():
    """东财抛异常时降级新浪。"""
    sina_data = {"main_net": 888, "super_large": 1, "large": 2, "medium": 3, "small": 4}
    with patch("app.datasources.free_source.a_stock_data") as mock_asd, \
         patch("app.datasources.free_source.data") as mock_data:
        mock_asd.eastmoney_fund_flow_minute.side_effect = RuntimeError("push2 断连")
        mock_data.get_money_flow.return_value = sina_data
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_money_flow("600519")
    assert result == sina_data


# ============================================================
# get_sectors:新浪板块解析
# Bug:data.py 正则要求结尾分号,但新浪实际返回无分号 → 解析失败返回空。
# 修复:提取宽松解析器 parse_sina_sectors,FreeSource.get_sectors 复用,
# 不再走 data.py(严格正则)。
# ============================================================

# 模拟新浪真实返回格式:var 声明 + JSON,**无结尾分号**
# 字段顺序:[0=code,1=名称,2=个股数,3=均价,4=涨跌幅,5=换手率,6=成交量,7=成交额,
#           8=领涨股代码,9=领涨股涨幅,10=其它,11=其它,12=领涨股名称]
_SINA_SECTOR_TEXT_NO_SEMICOLON = (
    'var S_Finance_bankuai_sinaindustry = '
    '{"bankuai_yinhang":"HY_yh,银行,30,5.0,1.25,0.8,100000,500000,sz_gsyh,2.0,xx,yy,工商银行"}'
)
# 同样内容但带分号(旧格式)
_SINA_SECTOR_TEXT_WITH_SEMICOLON = _SINA_SECTOR_TEXT_NO_SEMICOLON + ";"


def test_parse_sina_sectors_handles_text_without_trailing_semicolon():
    """新浪实际返回无结尾分号,解析器必须能解析(Bug:旧正则要求分号导致失败)。"""
    from app.services.screener import parse_sina_sectors
    result = parse_sina_sectors(_SINA_SECTOR_TEXT_NO_SEMICOLON)
    assert len(result) == 1
    assert result[0]["name"] == "银行"
    assert result[0]["change_pct"] == 1.25
    assert result[0]["leader_stock"] == "工商银行"


def test_parse_sina_sectors_still_handles_text_with_semicolon():
    """兼容旧格式(带分号)。"""
    from app.services.screener import parse_sina_sectors
    result = parse_sina_sectors(_SINA_SECTOR_TEXT_WITH_SEMICOLON)
    assert len(result) == 1
    assert result[0]["name"] == "银行"


def test_parse_sina_sectors_returns_empty_on_no_match():
    from app.services.screener import parse_sina_sectors
    assert parse_sina_sectors("garbage text no json here") == []


def test_parse_sina_sectors_skips_malformed_entries():
    """字段不足13个的条目跳过,不影响其它。"""
    from app.services.screener import parse_sina_sectors
    text = (
        'var S_Finance_bankuai_x = '
        '{"a":"short,only,few,fields","b":"HY_xx,bankuai,银行,30,5.0,1.25,0.8,100000,500000,sz_xx,2.0,yy,工商银行"}'
    )
    result = parse_sina_sectors(text)
    assert len(result) == 1
    assert result[0]["name"] == "bankuai"  # fields[1]


def test_free_source_get_sectors_uses_loose_parser_not_data_py():
    """FreeSource.get_sectors 应走宽松解析(parse_sina_sectors),
    不再走 data.py 的严格正则(会被无分号返回坑掉)。"""
    from app.services.screener import parse_sina_sectors as real_parser
    with patch("app.datasources.free_source.data") as mock_data, \
         patch("app.datasources.free_source.parse_sina_sectors", wraps=real_parser) as mock_parser:
        # data.py 若被调用应抛错(证明没走它)
        mock_data.get_sectors.side_effect = AssertionError("不该走 data.py")
        ds = FreeSource(cache_ttl_realtime=30)
        # 走真实网络;宽松解析能拿到数据则 mock_parser 会被调
        result = ds.get_sectors()
    # 宽松解析被调用了(而不是 data.py)
    mock_parser.assert_called()


def test_free_source_get_sectors_returns_empty_on_network_failure():
    """网络失败返回空 list,不抛异常。"""
    with patch("app.services.screener.urllib.request.urlopen",
               side_effect=RuntimeError("net down")):
        ds = FreeSource(cache_ttl_realtime=30)
        result = ds.get_sectors()
    assert result == []
