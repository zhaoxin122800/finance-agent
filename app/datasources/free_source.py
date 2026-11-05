"""FreeSource —— 默认数据源实现,降级链 + 内存缓存 + 错误兜底。

实时行情降级链:腾讯(富字段 PE/PB/市值) → 新浪(基础字段) → 空。
K线降级链:百度(带MA) → 新浪 → 空。
其余接口(分时/板块/资金流/龙虎榜)走新浪 data.py。
缓存只对 realtime 生效(TTL 防封 IP);其它接口每次实时调。
"""
from __future__ import annotations

import logging
import re
import time
import urllib.request
from typing import Any

from app.services.screener import parse_sina_sectors
from vendors import a_stock_data, data  # 原样资产,作为依赖注入点

log = logging.getLogger("finance-agent.datasource")

_SINA_SECTOR_URL = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"


# 百度列名 → 统一字段名的映射
_BAIDU_KEY_MAP = {
    "time": "date",
    "open": "open",
    "close": "close",
    "high": "high",
    "low": "low",
    "volume": "volume",
    "amount": "amount",
    "ma5avgprice": "ma5",
    "ma10avgprice": "ma10",
    "ma20avgprice": "ma20",
}


def _parse_baidu_kline(raw: dict) -> list[dict]:
    """解析百度股市通K线返回。

    raw = {"keys": "time,open,...,ma5avgprice,...", "rows": ["20260620000000,10.0,...", ...]}
    兼容 keys 为 list 或逗号字符串;rows 每条按 keys 列对齐取值。
    单行格式错误(列数不符)跳过,不影响整批。
    """
    if not raw or not isinstance(raw, dict):
        return []
    keys_raw = raw.get("keys", [])
    if isinstance(keys_raw, str):
        keys = [k.strip() for k in keys_raw.split(",") if k.strip()]
    else:
        keys = list(keys_raw)
    if not keys:
        return []
    rows = raw.get("rows", [])
    if not rows:
        return []

    # 建立 列索引 → 统一字段名 的映射(只保留关心的字段)
    idx_to_field: dict[int, str] = {}
    for i, k in enumerate(keys):
        field = _BAIDU_KEY_MAP.get(k)
        if field:
            idx_to_field[i] = field

    result: list[dict] = []
    for row in rows:
        vals = row.split(",")
        if len(vals) != len(keys):
            continue  # 列数不符,跳过
        item: dict = {}
        for i, field in idx_to_field.items():
            raw_val = vals[i].strip()
            if not raw_val:
                continue
            try:
                if field == "date":
                    # 百度 time 字段已是 YYYY-MM-DD 格式(如 2018-03-29),直接用;
                    # 兼容纯数字格式 20260620000000 -> 2026-06-20
                    if re.match(r"^\d{4}-\d{2}-\d{2}", raw_val):
                        item["date"] = raw_val[:10]
                    elif re.match(r"^\d{8}", raw_val):
                        item["date"] = f"{raw_val[:4]}-{raw_val[4:6]}-{raw_val[6:8]}"
                    else:
                        continue
                else:
                    item[field] = float(raw_val)
            except (ValueError, IndexError):
                continue
        if "date" in item:
            result.append(item)
    return result


class FreeSource:
    """默认免费数据源。"""

    def __init__(self, cache_ttl_realtime: int = 30):
        self._ttl = cache_ttl_realtime
        # 缓存结构: {frozenset(codes): (timestamp, payload)}
        self._realtime_cache: dict[frozenset[str], tuple[float, dict[str, dict]]] = {}

    def get_realtime(self, codes: list[str]) -> dict[str, dict]:
        if not codes:
            return {}
        key = frozenset(codes)
        now = time.time()
        cached = self._realtime_cache.get(key)
        if cached and (now - cached[0]) < self._ttl:
            return cached[1]

        payload = self._fetch_realtime_with_fallback(list(codes))
        if payload:
            self._realtime_cache[key] = (now, payload)
        return payload

    def _fetch_realtime_with_fallback(self, codes: list[str]) -> dict[str, dict]:
        """降级链:腾讯(主) → 新浪(备)。"""
        # 1. 腾讯(富字段:PE/PB/市值/涨跌停)
        try:
            payload = a_stock_data.tencent_quote(codes)
            if payload:
                return payload
        except Exception as e:
            log.warning("tencent_quote 失败,降级新浪(%s): %s", codes, e)
        # 2. 新浪(基础字段:volume/bid/ask)
        try:
            return data.get_realtime(codes)
        except Exception as e:
            log.warning("get_realtime 新浪也失败(%s): %s", codes, e)
            return {}

    def get_kline(self, code: str, days: int = 30, scale: str = "240") -> list[dict]:
        """降级链:日K用百度(带MA) → 新浪;非日K(分时/周)直接用新浪(百度不认 scale)。"""
        # 日K(240):优先百度(独有 ma5/ma10/ma20)
        if scale == "240":
            try:
                raw = a_stock_data.baidu_kline_with_ma(code)
                parsed = _parse_baidu_kline(raw)
                if parsed:
                    return parsed[-days:] if days else parsed
            except Exception as e:
                log.warning("baidu_kline_with_ma 失败,降级新浪(%s): %s", code, e)
        # 新浪(支持全周期 5/15/30/60/240/1680)
        try:
            return data.get_kline(code, days, scale)
        except Exception as e:
            log.warning("get_kline 新浪失败(%s, scale=%s): %s", code, scale, e)
            return []

    def get_minute(self, code: str) -> list[dict]:
        try:
            return data.get_minute(code)
        except Exception as e:
            log.warning("get_minute 失败(%s): %s", code, e)
            return []

    def get_sectors(self) -> list[dict]:
        """新浪板块。走宽松解析(parse_sina_sectors),不依赖 data.py 的严格正则。

        data.py 的正则要求结尾分号,新浪实际返回无分号 → 始终空。
        这里自己抓网络 + 用 parse_sina_sectors 解析(与 screener 共用)。
        """
        try:
            req = urllib.request.Request(_SINA_SECTOR_URL, headers={"User-Agent": "Mozilla/5.0"})
            text = urllib.request.urlopen(req, timeout=10).read().decode("gbk", errors="ignore")
            return parse_sina_sectors(text)
        except Exception as e:
            log.warning("get_sectors 失败: %s", e)
            return []

    def get_money_flow(self, code: str) -> dict:
        """资金流降级链:东财防封分钟级(主)→ 新浪(备)→ 全0。

        新浪 get_money_flow 走东财 push2 裸请求,常被风控断连;
        a_stock_data 的 eastmoney_fund_flow_minute 带 em_get 限流,更稳。
        东财返回分钟级 list,取最新一条并映射字段到统一结构。
        """
        # 1. 东财防封版(取最新一条分钟数据)
        try:
            minutes = a_stock_data.eastmoney_fund_flow_minute(code)
            if minutes:
                latest = minutes[-1]
                return {
                    "main_net": latest.get("main_net", 0),
                    "super_large": latest.get("super_net", 0),
                    "large": latest.get("large_net", 0),
                    "medium": latest.get("mid_net", 0),
                    "small": latest.get("small_net", 0),
                }
        except Exception as e:
            log.warning("eastmoney_fund_flow_minute 失败,降级新浪(%s): %s", code, e)
        # 2. 新浪(备)
        try:
            return data.get_money_flow(code)
        except Exception as e:
            log.warning("get_money_flow 新浪也失败(%s): %s", code, e)
            return {"main_net": 0, "super_large": 0, "large": 0, "medium": 0, "small": 0}

    def get_top_list(self, date: str | None = None) -> list[dict]:
        try:
            return data.get_top_list(date)
        except Exception as e:
            log.warning("get_top_list 失败: %s", e)
            return []
