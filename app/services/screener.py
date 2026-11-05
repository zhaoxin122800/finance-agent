"""选股器 service —— 提供市场热门股榜单(龙虎榜)+ 板块排名。

发现股票的入口:用户看到榜单里感兴趣的,点一下加进自选。
数据源:daily_dragon_tiger(东财 reportapi,不走 push2,较稳)+ 新浪板块(自带解析,绕开 data.py 正则 bug)。
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any

from vendors import a_stock_data

log = logging.getLogger("finance-agent.screener")

_SINA_SECTOR_URL = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"


def hot_stocks(limit: int = 30) -> dict:
    """当日龙虎榜热门股(按净买入排序的天然热门榜单)。

    返回 {date, total_records, stocks: [{code,name,reason,close,change_pct,net_buy_wan,turnover_pct}]}
    """
    try:
        result = a_stock_data.daily_dragon_tiger()
        stocks = result.get("stocks", [])[:limit]
        return {
            "date": result.get("date", ""),
            "total_records": result.get("total_records", 0),
            "stocks": stocks,
        }
    except Exception as e:
        log.warning("daily_dragon_tiger 失败: %s", e)
        return {"date": "", "total_records": 0, "stocks": []}


def parse_sina_sectors(text: str) -> list[dict]:
    """解析新浪板块接口返回文本(宽松正则,不要求结尾分号)。

    data.py 的 get_sectors 正则要求结尾分号,但实际返回无分号 → 解析失败。
    此函数为共享解析器,screener 与 FreeSource.get_sectors 共用。
    """
    # 宽松匹配:不要求结尾分号(新浪实际返回无分号)
    match = re.search(r"var\s+S_Finance_bankuai_\w+\s*=\s*(\{.*\})", text or "", re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return []
    result = []
    for val in data.values():
        if not isinstance(val, str):
            continue
        fields = val.split(",")
        if len(fields) >= 13:
            try:
                change_pct = float(fields[4])
            except (ValueError, IndexError):
                change_pct = 0.0
            result.append({
                "name": fields[1],
                "change_pct": round(change_pct, 2),
                "leader_stock": fields[12] if len(fields) > 12 else "",
            })
    return result


def _fetch_sina_sectors() -> list[dict]:
    """请求+解析新浪板块接口(走 parse_sina_sectors)。"""
    try:
        req = urllib.request.Request(_SINA_SECTOR_URL, headers={"User-Agent": "Mozilla/5.0"})
        text = urllib.request.urlopen(req, timeout=10).read().decode("gbk", errors="ignore")
        return parse_sina_sectors(text)
    except Exception as e:
        log.warning("新浪板块请求失败: %s", e)
        return []


def sector_ranking(datasource: Any = None) -> list[dict]:
    """板块涨跌排名(按 change_pct 降序)。

    优先用自带的新浪解析(避开 data.py 正则 bug);datasource 参数保留兼容但不再使用。
    """
    sectors = _fetch_sina_sectors()
    return sorted(sectors, key=lambda s: s.get("change_pct", 0) or 0, reverse=True)


# ============================================================
# 全市场选股器(新浪 Market_Center 接口,实时行情 + 20 字段)
# ============================================================

_MARKET_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData?page={page}&num={num}&node=hs_a&sort={sort}&asc={asc}"
)
# 允许的排序字段(白名单,防注入)
_SORTABLE = {
    "changepercent": "changepercent",
    "turnoverratio": "turnoverratio",
    "trade": "trade",
    "mktcap": "mktcap",
    "per": "per",
    "pb": "pb",
    "volume": "volume",
    "amount": "amount",
}


def _fetch_sina_market_page(page: int, num: int, sort: str, asc: bool) -> list[dict]:
    """请求新浪全市场一页数据。"""
    try:
        sort_field = _SORTABLE.get(sort, "changepercent")
        url = _MARKET_URL.format(page=page, num=num, sort=sort_field, asc="1" if asc else "0")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        text = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
        return json.loads(text) if text else []
    except Exception as e:
        log.warning("新浪全市场请求失败: %s", e)
        return []


def _fetch_sina_suggest(key: str) -> str:
    """新浪搜索建议接口(全市场,含 A 股/港股/美股/基金等)。

    返回原始文本:var suggestdata="名称,类型,代码,符号,简称,,简称,市场,1,,,;..."
    类型:11=沪A,12=深A,31=港股,22=美股,99=指数,23=基金 等
    """
    try:
        encoded_key = urllib.parse.quote(key)
        url = f"https://suggest3.sinajs.cn/suggest/type=&key={encoded_key}&name=suggestdata"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
        return urllib.request.urlopen(req, timeout=8).read().decode("gbk", errors="ignore")
    except Exception as e:
        log.warning("新浪搜索建议失败: %s", e)
        return ""


def _parse_sina_suggest(raw: str, limit: int = 50) -> list[dict]:
    """解析 suggest 接口,只保留 A 股(类型 11/12),返回 [{code, name, symbol}]。"""
    if not raw:
        return []
    m = re.search(r'suggestdata="(.*)"', raw, re.DOTALL)
    if not m:
        return []
    stocks = []
    for item in m.group(1).split(";"):
        fields = item.split(",")
        if len(fields) < 4:
            continue
        stype, code, symbol, name = fields[1], fields[2], fields[3], fields[0] or fields[4]
        # 只留沪深 A 股(11=沪,12=深)
        if stype not in ("11", "12"):
            continue
        stocks.append({"code": code, "name": name, "symbol": symbol})
        if len(stocks) >= limit:
            break
    return stocks


def market_list(
    page: int = 1,
    num: int = 50,
    sort: str = "changepercent",
    asc: bool = False,
    query: str = "",
) -> dict:
    """全市场股票列表(沪深 A 股)。

    - 无 query: 按排序拉涨幅/换手率等榜单(分页)
    - 有 query: 走新浪 suggest 接口全市场搜索(按代码/名称/拼音),覆盖全部 5000 只,
                不再限于榜单前 N 页。搜索结果补充实时行情需另查(此处只返回基础信息)。

    返回 {page, num, total_returned, stocks: [...]}
    """
    num = min(num, 80)

    # 搜索分支:全市场 suggest
    if query and query.strip():
        matches = _parse_sina_suggest(_fetch_sina_suggest(query.strip()), limit=num)
        stocks = [{"code": m["code"], "name": m["name"], "price": 0, "change_pct": 0,
                   "volume": 0, "pe": 0, "pb": 0, "market_cap": 0, "turnover_ratio": 0} for m in matches]
        return {"page": 1, "num": num, "total_returned": len(stocks), "stocks": stocks}

    # 浏览分支:按排序拉榜单
    raw = _fetch_sina_market_page(page, num, sort, asc)
    stocks = []
    for r in raw:
        try:
            stocks.append({
                "code": r.get("code", ""),
                "name": r.get("name", ""),
                "price": _to_float(r.get("trade")),
                "change_pct": _to_float(r.get("changepercent")),
                "volume": _to_float(r.get("volume")),
                "pe": _to_float(r.get("per")),
                "pb": _to_float(r.get("pb")),
                "market_cap": round(_to_float(r.get("mktcap")) / 1e8, 2),
                "turnover_ratio": _to_float(r.get("turnoverratio")),
            })
        except Exception:
            continue
    return {"page": page, "num": num, "total_returned": len(stocks), "stocks": stocks}


def _to_float(v) -> float:
    """安全转 float,失败返回 0。"""
    try:
        return float(v) if v not in (None, "") else 0.0
    except (ValueError, TypeError):
        return 0.0

