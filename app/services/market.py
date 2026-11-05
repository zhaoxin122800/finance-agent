"""市场级数据 service —— 北向资金等全市场指标。

北向资金(沪深股通)是 A 股重要外资动向信号:
- 正值大幅流入 → 外资看多
- 负值大幅流出 → 外资撤离,谨慎
数据源:同花顺 data.hexin.cn(稳定,不依赖 pandas)。
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.parse
import urllib.request

log = logging.getLogger("finance-agent.market")

_NORTHBOUND_URL = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"


def _fetch_northbound_raw() -> dict | None:
    """请求同花顺北向资金原始数据。失败返回 None。"""
    try:
        req = urllib.request.Request(
            _NORTHBOUND_URL,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.10jqka.com.cn/"},
        )
        text = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
        return json.loads(text)
    except Exception as e:
        log.warning("北向资金请求失败: %s", e)
        return None


def _last_valid(values: list) -> float:
    """取列表最后一个非 None 值,全 None 返回 0。"""
    for v in reversed(values or []):
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
    return 0.0


def northbound_flow() -> dict:
    """当日北向资金净流入(亿元)。

    返回 {hgt: 沪股通, sgt: 深股通, total: 合计, time: 最后更新时间}
    """
    raw = _fetch_northbound_raw()
    if not raw:
        return {"hgt": 0.0, "sgt": 0.0, "total": 0.0, "time": "", "error": "数据源未返回"}

    hgt = _last_valid(raw.get("hgt", []))
    sgt = _last_valid(raw.get("sgt", []))
    times = raw.get("time", [])
    last_time = times[-1] if times else ""

    return {
        "hgt": round(hgt, 2),
        "sgt": round(sgt, 2),
        "total": round(hgt + sgt, 2),
        "time": last_time,
    }


# ============================================================
# 个股公告(东财 np-anotice-stock,比新闻更权威)
# ============================================================

_ANNOUNCE_URL = (
    "https://np-anotice-stock.eastmoney.com/api/security/ann"
    "?cb=jQuery&sr=-1&page_size={page_size}&page_index=1"
    "&ann_type=A&client_source=web&stock_list={code}"
)


def _fetch_announcements_raw(code: str, page_size: int = 20) -> str | None:
    """请求东财个股公告 JSONP 原始文本。失败返回 None。"""
    try:
        url = _ANNOUNCE_URL.format(page_size=page_size, code=code)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://so.eastmoney.com/"})
        return urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
    except Exception as e:
        log.warning("个股公告请求失败(%s): %s", code, e)
        return None


def stock_announcements(code: str, limit: int = 10) -> list[dict]:
    """获取个股公告列表。

    返回 [{title, notice_date, art_code, url}]
    公告类型含:分红/减持/业绩预告/重组/股东大会 等(比新闻更权威,是官方披露)。
    """
    import re
    text = _fetch_announcements_raw(code, page_size=max(limit, 20))
    if not text:
        return []
    try:
        m = re.search(r"jQuery\((.*)\)", text, re.DOTALL)
        if not m:
            return []
        d = json.loads(m.group(1))
        items = d.get("data", {}).get("list", []) or []
        return [
            {
                "title": it.get("title", ""),
                "notice_date": (it.get("notice_date", "") or "")[:10],
                "art_code": it.get("art_code", ""),
                "url": f"https://np-anotice-stock.eastmoney.com/api/security/ann?art_code={it.get('art_code','')}",
            }
            for it in items[:limit]
        ]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log.warning("公告解析失败(%s): %s", code, e)
        return []


# ============================================================
# 财联社电报(7×24 实时快讯)
#   端点: https://www.cls.cn/v1/roll/get_roll_list
#   签名: sign = MD5(SHA1(sortedQuery))
#     - 参数按 key 字典序排序,拼成 key=value 用 & 连接
#     - 过滤空值(对应 JS filter(e=>e))
#     - 先 SHA1 取 hex,再 MD5 取 hex
#   sv 必须为 8.7.9(网页版当前版本,7.7.5 等旧值会 errno=10012)
#   逆向自 https://www.cls.cn/telegraph 的 _app chunk(module 36498)
# ============================================================

_CLS_TELEGRAPH_URL = "https://www.cls.cn/v1/roll/get_roll_list"
_CLS_SV = "8.7.9"


def _cls_sign(params: dict) -> str:
    """财联社网页版签名:MD5(SHA1(sortedQuery))。"""
    parts = []
    for k in sorted(params):
        v = params[k]
        if v is None or v == "":
            continue
        parts.append(f"{k}={v}")
    qs = "&".join(parts)
    sha1_hex = hashlib.sha1(qs.encode("utf-8")).hexdigest()
    return hashlib.md5(sha1_hex.encode("utf-8")).hexdigest()


def _fetch_cls_telegraph_raw(rn: int, last_time: int) -> str | None:
    """请求财联社电报列表原始 JSON 文本。失败返回 None。

    rn: 每页条数; last_time: 翻页时间戳(0 表示取最新)。
    """
    params = {
        "app": "CailianpressWeb",
        "last_time": last_time,
        "os": "web",
        "refresh_type": "1",
        "rn": rn,
        "sv": _CLS_SV,
    }
    # 关键:空值参数既不进签名也不进 URL。
    # 服务器按实际收到的参数校验签名,空字符串参数会导致签名不一致(errno=10012)。
    params = {k: v for k, v in params.items() if v not in (None, "")}
    params["sign"] = _cls_sign(params)
    url = _CLS_TELEGRAPH_URL + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
                "Referer": "https://www.cls.cn/telegraph",
                "Accept": "application/json",
            },
        )
        return urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
    except Exception as e:
        log.warning("财联社电报请求失败: %s", e)
        return None


def cls_telegraph(limit: int = 20) -> list[dict]:
    """获取财联社 7×24 实时电报。

    返回 [{time, content, level, shareurl, stocks}]
      - time: 本地时间字符串 HH:MM:SS
      - content: 电报正文
      - level: 重要性 A/B/C(A=重磅)
      - shareurl: 财联社原文链接
      - stocks: 关联个股 [{name, code}]
    """
    text = _fetch_cls_telegraph_raw(rn=max(limit, 20), last_time=0)
    if not text:
        return []
    try:
        d = json.loads(text)
        if d.get("errno") != 0:
            log.warning("财联社电报返回错误: errno=%s msg=%s", d.get("errno"), d.get("msg"))
            return []
        items = (d.get("data") or {}).get("roll_data") or []
        result = []
        for it in items[:limit]:
            ts = it.get("ctime") or 0
            stocks = [
                {"name": s.get("name", ""), "code": s.get("stock_id", "") or s.get("code", "")}
                for s in (it.get("stock_list") or [])
                if isinstance(s, dict)
            ]
            result.append({
                "time": time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "",
                "content": (it.get("content") or it.get("brief") or "").strip(),
                "level": it.get("level") or "C",
                "shareurl": it.get("shareurl") or "",
                "stocks": stocks,
            })
        return result
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log.warning("财联社电报解析失败: %s", e)
        return []


# ============================================================
# 公司画像/产业链定位(东财 F10 公司基本信息)
#   端点: datacenter.eastmoney.com securities/api/data/get
#         type=RPT_F10_ORG_BASICINFO
#   一条接口拿到主营业务/行业分类/概念板块/收入结构/控股股东,
#   用于 AI 推断"这家公司做什么的、产业链上下游、竞争对手"。
# ============================================================

_COMPANY_URL = (
    "https://datacenter.eastmoney.com/securities/api/data/get"
    "?type=RPT_F10_ORG_BASICINFO&sty=ALL"
    "&filter=(SECURITY_CODE%3D%22{code}%22)&p=1&ps=1"
)


def _fetch_company_raw(code: str) -> str | None:
    """请求东财 F10 公司基本信息原始 JSON 文本。失败返回 None。"""
    try:
        url = _COMPANY_URL.format(code=code)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://emweb.eastmoney.com/"},
        )
        return urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
    except Exception as e:
        log.warning("公司画像请求失败(%s): %s", code, e)
        return None


def _split_concepts(raw: str) -> list[str]:
    """概念板块字符串(逗号分隔,混有半角/全角逗号)拆成列表,去掉 HS300_ 等指数标记。"""
    if not raw:
        return []
    parts = raw.replace("，", ",").split(",")
    return [p.strip() for p in parts if p.strip() and not p.strip().endswith("_")]


def company_profile(code: str) -> dict:
    """获取公司画像/产业链定位数据。

    返回精简字段(全部容错,缺失则空字符串/空列表):
      - name: 公司简称; full_name: 公司全称; org_type: 企业类型(国企/民企/外资)
      - main_business: 主营业务; business_scope: 经营范围
      - industry: 东财三级行业; csrc_industry: 证监会行业; area: 地域板块
      - concepts: 概念板块列表(半导体概念/苹果概念 等,产业链信号)
      - profile: 公司简介
      - income_structure: 收入结构(产品+占比); top_product: 最赚钱产品
      - gross_margin: 毛利率(%); listing_date: 上市日期
      - controller: 控股股东; real_controller: 实际控制人
    """
    text = _fetch_company_raw(code)
    if not text:
        return {}
    try:
        d = json.loads(text)
        items = (d.get("result") or {}).get("data") or []
        if not items:
            return {}
        it = items[0]
        income_name = it.get("INCOME_STRU_NAMENEW") or it.get("INCOME_STRU_NAME") or ""
        income_ratio = it.get("INCOME_STRU_RATIONEW") or it.get("INCOME_STRU_RATIO") or ""
        # 把"产品A、产品B | 80%、20%"拼成可读结构
        income_structure = ""
        if income_name and income_ratio:
            names = [s.strip() for s in income_name.replace("，", ",").replace("；", ",").split(",") if s.strip()]
            ratios = [s.strip() for s in income_ratio.replace("，", ",").replace("；", ",").split(",") if s.strip()]
            income_structure = "; ".join(
                f"{n} {r}" for n, r in zip(names, ratios)
            )
        return {
            "name": it.get("SECURITY_NAME_ABBR", ""),
            "full_name": it.get("ORG_NAME", ""),
            "org_type": it.get("ORG_FORM", ""),
            "main_business": it.get("MAIN_BUSINESS", ""),
            "business_scope": it.get("BUSINESS_SCOPE", ""),
            "industry": it.get("EM2016", ""),
            "csrc_industry": it.get("CSRC_INDUSTRY_NAME", ""),
            "area": it.get("AREA_BOARD_NAME", ""),
            "concepts": _split_concepts(it.get("BLGAINIAN", "")),
            "profile": (it.get("ORG_PROFILE") or it.get("ORG_PROFIE") or "").strip(),
            "income_structure": income_structure,
            "top_product": it.get("MAXPROFIT_PRODUCT", ""),
            "gross_margin": it.get("GROSS_PROFIT_RATIO", ""),
            "listing_date": (it.get("LISTING_DATE") or "")[:10],
            "controller": it.get("CONTROL_HOLDER", ""),
            "real_controller": it.get("REAL_CONTROLER", ""),
        }
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
        log.warning("公司画像解析失败(%s): %s", code, e)
        return {}


# ============================================================
# 公告正文详情(东财 np-cnotice-stock)
#   端点: np-cnotice-stock.eastmoney.com/api/content/ann
#   用 art_code(列表接口已返回)换取正文 notice_content + PDF 附件 attach_url
# ============================================================

_ANNOUNCEMENT_DETAIL_URL = "https://np-cnotice-stock.eastmoney.com/api/content/ann"


def _fetch_announcement_detail_raw(art_code: str) -> str | None:
    """请求公告正文详情原始 JSON。失败返回 None。"""
    url = f"{_ANNOUNCEMENT_DETAIL_URL}?art_code={art_code}&client_source=web&page_index=1"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"},
        )
        return urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
    except Exception as e:
        log.warning("公告正文请求失败(%s): %s", art_code, e)
        return None


def _clean_notice_html(raw: str) -> str:
    """公告正文是含 HTML 标签的字符串,转成纯文本供页面展示。

    保留段落换行,去掉 script/style/标签,合并多余空白。
    """
    if not raw:
        return ""
    import re as _re
    # 去掉 script/style
    raw = _re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw, flags=_re.S | _re.I)
    # <br> / <p> / </p> 转\n
    raw = _re.sub(r"<br\s*/?>", "\n", raw, flags=_re.I)
    raw = _re.sub(r"</p\s*>", "\n", raw, flags=_re.I)
    raw = _re.sub(r"<p[^>]*>", "", raw, flags=_re.I)
    # 去其余标签
    raw = _re.sub(r"<[^>]+>", "", raw)
    # HTML 实体反转义
    import html as _html
    raw = _html.unescape(raw)
    # 合并多余空白但保留换行
    lines = [ln.strip() for ln in raw.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def announcement_detail(art_code: str) -> dict:
    """获取单条公告的正文详情。

    返回 {title, date, content(纯文本), attach_url(PDF), art_code}
    数据缺失/失败返回空 dict(不抛)。
    """
    text = _fetch_announcement_detail_raw(art_code)
    if not text:
        return {}
    try:
        d = json.loads(text)
        data = d.get("data") or {}
        if not isinstance(data, dict) or not data:
            return {}
        return {
            "art_code": art_code,
            "title": data.get("notice_title", ""),
            "date": (data.get("notice_date") or "")[:10],
            "content": _clean_notice_html(data.get("notice_content", "")),
            "attach_url": data.get("attach_url", ""),
        }
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log.warning("公告正文解析失败(%s): %s", art_code, e)
        return {}
