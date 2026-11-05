"""市场级数据 service 测试(北向资金等)。"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import market


def test_northbound_returns_latest_values(monkeypatch):
    """北向资金:返回当日沪股通/深股通净流入(列表最后有效值)。"""
    fake = {
        "time": ["09:10", "09:11", "09:12"],
        "hgt": [None, 1.5, 2.3],   # 沪股通(亿)
        "sgt": [None, None, 0.8],  # 深股通(亿)
    }
    monkeypatch.setattr(market, "_fetch_northbound_raw", lambda: fake)
    result = market.northbound_flow()
    assert result["hgt"] == 2.3   # 最后有效值
    assert result["sgt"] == 0.8
    assert result["total"] == 3.1  # hgt + sgt
    assert "time" in result


def test_northbound_handles_all_none(monkeypatch):
    """全部 None(非交易时段)时返回 0,不崩。"""
    monkeypatch.setattr(market, "_fetch_northbound_raw", lambda: {"time": [], "hgt": [], "sgt": []})
    result = market.northbound_flow()
    assert result["hgt"] == 0
    assert result["sgt"] == 0
    assert result["total"] == 0


def test_northbound_failure_returns_zero(monkeypatch):
    """接口失败时返回全0(不抛)。"""
    monkeypatch.setattr(market, "_fetch_northbound_raw", lambda: None)
    result = market.northbound_flow()
    assert result["total"] == 0
    assert "error" in result or result["hgt"] == 0


def test_northbound_filters_none_in_middle(monkeypatch):
    """列表中间有 None 时取最后一个非 None 值。"""
    fake = {"time": ["09:10","09:11","09:12","09:13"], "hgt": [1.0, None, 3.0, None], "sgt": [0.5, 0.6, None, None]}
    monkeypatch.setattr(market, "_fetch_northbound_raw", lambda: fake)
    result = market.northbound_flow()
    assert result["hgt"] == 3.0   # 最后非None
    assert result["sgt"] == 0.6


# ============================================================
# 个股公告(东财 np-anotice-stock,比新闻更权威)
# ============================================================

def test_stock_announcements_returns_list(monkeypatch):
    fake_jsonp = 'jQuery({"data":{"list":[{"title":"分红公告","notice_date":"2026-06-22","art_code":"A1"},{"title":"减持公告","notice_date":"2026-06-20","art_code":"A2"}]}})'
    monkeypatch.setattr(market, "_fetch_announcements_raw", lambda code, page_size: fake_jsonp)
    result = market.stock_announcements("600519", limit=5)
    assert len(result) == 2
    assert result[0]["title"] == "分红公告"
    assert result[0]["notice_date"] == "2026-06-22"


def test_stock_announcements_failure_returns_empty(monkeypatch):
    monkeypatch.setattr(market, "_fetch_announcements_raw", lambda code, page_size: None)
    result = market.stock_announcements("600519")
    assert result == []


def test_stock_announcements_bad_json_returns_empty(monkeypatch):
    monkeypatch.setattr(market, "_fetch_announcements_raw", lambda code, page_size: "not json")
    result = market.stock_announcements("600519")
    assert result == []


# ============================================================
# 财联社电报(cls_telegraph)
# ============================================================

def test_cls_sign_is_md5_of_sha1():
    """签名算法 = MD5(SHA1(sortedQuery)),与已知向量比对。"""
    # params 排序后过滤空值: app=CailianpressWeb&os=web&refresh_type=1&rn=5&sv=8.7.9
    import hashlib
    qs = "app=CailianpressWeb&os=web&refresh_type=1&rn=5&sv=8.7.9"
    expected = hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()
    params = {"app": "CailianpressWeb", "os": "web", "refresh_type": "1", "rn": "5", "sv": "8.7.9"}
    assert market._cls_sign(params) == expected


def test_cls_sign_filters_empty_values():
    """空值参数不进签名串。"""
    with_empty = {"app": "X", "category": "", "os": "web"}
    without = {"app": "X", "os": "web"}
    assert market._cls_sign(with_empty) == market._cls_sign(without)


def test_cls_telegraph_parses_roll_data(monkeypatch):
    """正常返回时解析出 time/content/level。"""
    import json
    fake = json.dumps({
        "errno": 0,
        "data": {
            "roll_data": [
                {"ctime": 1782841983, "content": "财联社电报测试", "level": "A", "shareurl": "http://x", "stock_list": []},
                {"ctime": 1782841127, "content": "  带空格  ", "level": "C", "shareurl": "", "stock_list": []},
            ]
        },
    })
    monkeypatch.setattr(market, "_fetch_cls_telegraph_raw", lambda rn, last_time: fake)
    result = market.cls_telegraph(limit=5)
    assert len(result) == 2
    assert result[0]["content"] == "财联社电报测试"
    assert result[0]["level"] == "A"
    assert result[0]["shareurl"] == "http://x"
    assert result[1]["content"] == "带空格"  # strip 后


def test_cls_telegraph_errno_returns_empty(monkeypatch):
    """errno != 0(签名错误等)返回空列表,不抛。"""
    fake = '{"errno": 10012, "msg": "签名错误"}'
    monkeypatch.setattr(market, "_fetch_cls_telegraph_raw", lambda rn, last_time: fake)
    assert market.cls_telegraph() == []


def test_cls_telegraph_failure_returns_empty(monkeypatch):
    """网络失败返回空列表。"""
    monkeypatch.setattr(market, "_fetch_cls_telegraph_raw", lambda rn, last_time: None)
    assert market.cls_telegraph() == []


def test_cls_telegraph_stocks_parsed(monkeypatch):
    """stock_list 正确解析为 [{name, code}]。"""
    import json
    fake = json.dumps({
        "errno": 0,
        "data": {"roll_data": [
            {"ctime": 1782841983, "content": "某股消息", "level": "B",
             "stock_list": [{"name": "贵州茅台", "stock_id": "SH600519"}]},
        ]},
    })
    monkeypatch.setattr(market, "_fetch_cls_telegraph_raw", lambda rn, last_time: fake)
    result = market.cls_telegraph(limit=5)
    assert result[0]["stocks"] == [{"name": "贵州茅台", "code": "SH600519"}]


# ============================================================
# 公司画像/产业链定位(company_profile)
# ============================================================

def test_company_profile_parses_fields(monkeypatch):
    """正常返回时解析出主营业务/行业/概念/收入结构等关键字段。"""
    import json
    fake = json.dumps({"result": {"data": [{
        "SECURITY_NAME_ABBR": "中微公司",
        "ORG_NAME": "中微半导体设备(上海)股份有限公司",
        "ORG_FORM": "地方国有企业",
        "MAIN_BUSINESS": "半导体设备及泛半导体设备的研发、生产和销售",
        "BUSINESS_SCOPE": "半导体设备制造",
        "EM2016": "电子设备-半导体-集成电路",
        "CSRC_INDUSTRY_NAME": "制造业-专用设备制造业",
        "AREA_BOARD_NAME": "上海板块",
        "BLGAINIAN": "半导体概念,国产芯片,中芯概念,机构重仓,HS300_,沪股通",
        "ORG_PROFILE": "  全球微观加工高端设备领军者  ",
        "INCOME_STRU_NAMENEW": "半导体设备相关产品",
        "INCOME_STRU_RATIONEW": "100.00%",
        "MAXPROFIT_PRODUCT": "半导体设备相关产品",
        "GROSS_PROFIT_RATIO": "44.5",
        "LISTING_DATE": "2019-07-22 00:00:00",
        "CONTROL_HOLDER": "无",
        "REAL_CONTROLER": "无",
    }]}})
    monkeypatch.setattr(market, "_fetch_company_raw", lambda code: fake)
    r = market.company_profile("688012")
    assert r["name"] == "中微公司"
    assert r["main_business"] == "半导体设备及泛半导体设备的研发、生产和销售"
    assert r["industry"] == "电子设备-半导体-集成电路"
    # 概念列表过滤掉 HS300_ 这类指数标记(以 _ 结尾)
    assert "半导体概念" in r["concepts"]
    assert "国产芯片" in r["concepts"]
    assert not any(c.endswith("_") for c in r["concepts"])
    # 收入结构拼成 "产品 占比"
    assert r["income_structure"] == "半导体设备相关产品 100.00%"
    # profile 去首尾空白
    assert r["profile"] == "全球微观加工高端设备领军者"
    assert r["listing_date"] == "2019-07-22"


def test_company_profile_failure_returns_empty(monkeypatch):
    """网络失败返回空 dict(不抛)。"""
    monkeypatch.setattr(market, "_fetch_company_raw", lambda code: None)
    assert market.company_profile("688012") == {}


def test_company_profile_bad_json_returns_empty(monkeypatch):
    """坏 JSON / 空 data 返回空 dict。"""
    monkeypatch.setattr(market, "_fetch_company_raw", lambda code: "not json")
    assert market.company_profile("688012") == {}


def test_company_profile_empty_data_returns_empty(monkeypatch):
    """接口返回空 data(无该公司)返回空 dict。"""
    import json
    fake = json.dumps({"result": {"data": []}})
    monkeypatch.setattr(market, "_fetch_company_raw", lambda code: fake)
    assert market.company_profile("999999") == {}


# ============================================================
# 公告正文详情(announcement_detail)
# ============================================================

def test_announcement_detail_parses_content(monkeypatch):
    """正常返回时解析出 title/date/content/attach_url。"""
    import json
    fake = json.dumps({"data": {
        "notice_title": "测试公告标题",
        "notice_date": "2026-06-22 00:00:00",
        "notice_content": "<p>证券代码：600519</p><p>正文内容</p><br/>结尾",
        "attach_url": "https://pdf.dfcfw.com/test.pdf",
    }})
    monkeypatch.setattr(market, "_fetch_announcement_detail_raw", lambda code: fake)
    r = market.announcement_detail("AN123")
    assert r["art_code"] == "AN123"
    assert r["title"] == "测试公告标题"
    assert r["date"] == "2026-06-22"
    assert r["attach_url"] == "https://pdf.dfcfw.com/test.pdf"
    # HTML 标签被清除,换行保留
    assert "<p>" not in r["content"]
    assert "证券代码" in r["content"]
    assert "正文内容" in r["content"]


def test_announcement_detail_strips_html_tags(monkeypatch):
    """正文里的 script/style/标签都要清除。"""
    fake = '{"data": {"notice_content": "<script>alert(1)</script><b>可见</b><style>x{}</style>"}}'
    monkeypatch.setattr(market, "_fetch_announcement_detail_raw", lambda code: fake)
    r = market.announcement_detail("AN1")
    assert "script" not in r["content"]
    assert "style" not in r["content"]
    assert "alert" not in r["content"]
    assert "可见" in r["content"]


def test_announcement_detail_failure_returns_empty(monkeypatch):
    """网络失败返回空 dict(不抛)。"""
    monkeypatch.setattr(market, "_fetch_announcement_detail_raw", lambda code: None)
    assert market.announcement_detail("AN1") == {}


def test_announcement_detail_bad_json_returns_empty(monkeypatch):
    """坏 JSON / 空 data 返回空 dict。"""
    monkeypatch.setattr(market, "_fetch_announcement_detail_raw", lambda code: "not json")
    assert market.announcement_detail("AN1") == {}
