#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
A股统一数据源 - data.py

提供实时行情、历史K线、分时数据、板块行情、龙虎榜、资金流向等接口。
数据源：新浪财经、搜狐财经
零外部依赖，仅使用 Python 标准库。

Usage:
    python data.py realtime 600789 002446
    python data.py kline 600789 --days 30
    python data.py kline 600789 --days 5 --scale 60
    python data.py minute 600789
    python data.py sectors
    python data.py top_list --date 2026-06-22
    python data.py money_flow 600789
    python data.py realtime 600789 --json
"""

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta

# Windows 控制台 UTF-8 兼容
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ============================================================
# 代码格式转换
# ============================================================

def _to_sina_symbol(code: str) -> str:
    """根据股票代码生成新浪格式代码 (sh600789 / sz002446 / bj830799)"""
    code = code.upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
    if code.startswith("6"):
        return "sh" + code
    elif code.startswith(("0", "3")):
        return "sz" + code
    elif code.startswith(("8", "4")):
        return "bj" + code
    else:
        return "sh" + code


def _strip_code(sina_symbol: str) -> str:
    """从新浪代码提取纯数字代码 (sh600789 -> 600789)"""
    return re.sub(r"^(sh|sz|bj)", "", sina_symbol)


# ============================================================
# HTTP 请求工具
# ============================================================

_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def _http_get(url: str, encoding: str = "utf-8", timeout: int = 10) -> str:
    """HTTP GET 请求"""
    req = urllib.request.Request(url, headers=_HEADERS)
    resp = urllib.request.urlopen(req, timeout=timeout)
    return resp.read().decode(encoding)


# ============================================================
# 实时行情
# ============================================================

def get_realtime(codes: list[str]) -> dict[str, dict]:
    """获取实时行情（支持批量）
    
    Args:
        codes: 股票代码列表，如 ["600789", "002446"]
    
    Returns:
        {code: {name, price, open, high, low, pre_close, volume, amount, bid, ask, change_pct}}
    """
    result = {}
    if not codes:
        return result
    
    try:
        symbols = [_to_sina_symbol(c) for c in codes]
        codes_str = ",".join(symbols)
        url = f"https://hq.sinajs.cn/list={codes_str}"
        text = _http_get(url, encoding="gbk")
        
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            
            match = re.match(r'var hq_str_(\w+)="([^"]*)"', line)
            if not match:
                continue
            
            symbol = match.group(1)
            data_str = match.group(2)
            if not data_str:
                continue
            
            fields = data_str.split(",")
            if len(fields) < 10:
                continue
            
            name = fields[0]
            open_price = float(fields[1]) if fields[1] else 0
            pre_close = float(fields[2]) if fields[2] else 0
            price = float(fields[3]) if fields[3] else 0
            high = float(fields[4]) if fields[4] else 0
            low = float(fields[5]) if fields[5] else 0
            bid = float(fields[6]) if fields[6] else 0
            ask = float(fields[7]) if fields[7] else 0
            volume = int(float(fields[8])) if fields[8] else 0
            amount = float(fields[9]) if fields[9] else 0
            
            if not price or price <= 0:
                continue
            
            change_amt = price - pre_close if pre_close else 0
            change_pct = (change_amt / pre_close * 100) if pre_close and pre_close > 0 else 0
            
            code = _strip_code(symbol)
            result[code] = {
                "code": code,
                "name": name,
                "price": price,
                "open": open_price,
                "high": high,
                "low": low,
                "pre_close": pre_close,
                "volume": volume // 100,  # 股 -> 手
                "amount": amount,
                "bid": bid,
                "ask": ask,
                "change_pct": round(change_pct, 2),
            }
    except Exception as e:
        print(f"get_realtime 错误: {e}", file=sys.stderr)
    
    return result


# ============================================================
# 历史K线
# ============================================================

def get_kline(code: str, days: int = 30, scale: str = "240") -> list[dict]:
    """获取历史K线数据
    
    Args:
        code: 股票代码，如 "600789"
        days: 返回天数
        scale: K线周期，5/15/30/60/240 分钟（240=日K）
    
    Returns:
        [{date, open, high, low, close, volume}]
    """
    result = []
    try:
        symbol = _to_sina_symbol(code)
        url = (
            f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_{symbol}="
            f"/CN_MarketDataService.getKLineData?symbol={symbol}&scale={scale}&ma=no&datalen={days}"
        )
        text = _http_get(url, encoding="utf-8")
        
        match = re.search(r"\(\[(.*)\]\)", text, re.DOTALL)
        if not match:
            return result
        
        data = json.loads("[" + match.group(1) + "]")
        for item in data:
            result.append({
                "date": item.get("day", ""),
                "open": float(item.get("open", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "close": float(item.get("close", 0)),
                "volume": int(item.get("volume", 0)),  # 股
            })
    except Exception as e:
        print(f"get_kline 错误: {e}", file=sys.stderr)
    
    return result


# ============================================================
# 分时数据
# ============================================================

def get_minute(code: str) -> list[dict]:
    """获取分时数据（1分钟K线）
    
    Args:
        code: 股票代码，如 "600789"
    
    Returns:
        [{time, price, volume, avg_price}]
    """
    result = []
    try:
        symbol = _to_sina_symbol(code)
        url = (
            f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_{symbol}="
            f"/CN_MarketDataService.getKLineData?symbol={symbol}&scale=1&ma=no&datalen=242"
        )
        text = _http_get(url, encoding="utf-8")
        
        match = re.search(r"\(\[(.*)\]\)", text, re.DOTALL)
        if not match:
            return result
        
        data = json.loads("[" + match.group(1) + "]")
        
        # 计算累计均价
        total_amount = 0.0
        total_volume = 0
        
        for item in data:
            vol = int(item.get("volume", 0))
            close = float(item.get("close", 0))
            amt = float(item.get("amount", 0))
            
            total_volume += vol
            total_amount += amt
            avg_price = (total_amount / total_volume) if total_volume > 0 else close
            
            result.append({
                "time": item.get("day", ""),
                "price": close,
                "volume": vol // 100,  # 股 -> 手
                "avg_price": round(avg_price, 3),
            })
    except Exception as e:
        print(f"get_minute 错误: {e}", file=sys.stderr)
    
    return result


# ============================================================
# 板块行情
# ============================================================

# 新浪行业板块代码表（部分常用板块）
_SECTOR_CODES = {
    "new_energy": "新能源",
    "semiconductor": "半导体",
    "pharmaceutical": "医药",
    "real_estate": "房地产",
    "banking": "银行",
    "brokerage": "券商",
    "automobile": "汽车",
    "military": "军工",
    "food_beverage": "食品饮料",
    "electronics": "电子",
    "computer": "计算机",
    "communication": "通信",
    "media": "传媒",
    "machinery": "机械",
    "chemical": "化工",
    "steel": "钢铁",
    "nonferrous": "有色",
    "construction": "建筑",
    "power": "电力",
    "agriculture": "农业",
}

# 新浪板块指数代码 (s_开头表示板块指数)
_SECTOR_INDEX_SYMBOLS = {
    "新能源": "sr_new_energy",
    "半导体": "sr_semiconductor",
    "医药": "sr_pharmaceutical",
    "房地产": "sr_real_estate",
    "银行": "sr_banking",
    "券商": "sr_brokerage",
    "汽车": "sr_automobile",
    "军工": "sr_military",
    "食品饮料": "sr_food_beverage",
    "电子": "sr_electronics",
    "计算机": "sr_computer",
    "通信": "sr_communication",
    "传媒": "sr_media",
    "机械": "sr_machinery",
    "化工": "sr_chemical",
    "钢铁": "sr_steel",
    "有色": "sr_nonferrous",
    "建筑": "sr_construction",
    "电力": "sr_power",
    "农业": "sr_agriculture",
}


def get_sectors() -> list[dict]:
    """获取板块行情
    
    Returns:
        [{name, change_pct, leader_stock}]
    """
    result = []
    try:
        url = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
        text = _http_get(url, encoding="gbk")
        
        # 新浪板块接口返回格式:
        # var S_Finance_bankuai_sinaindustry = {"key":"code,名称,个股数,均价,涨跌幅,换手率,...,领涨股代码,领涨股涨幅,...,领涨股名", ...}
        match = re.search(r'var\s+S_Finance_bankuai_\w+\s*=\s*(\{.*\})\s*;', text, re.DOTALL)
        if not match:
            return result
        
        data = json.loads(match.group(1))
        
        for key, val in data.items():
            if not isinstance(val, str):
                continue
            fields = val.split(",")
            # 字段: [0=code, 1=名称, 2=个股数, 3=均价, 4=涨跌幅, 5=换手率,
            #        6=成交量, 7=成交额, 8=领涨股代码, 9=领涨股涨幅, ...,
            #        12=领涨股名称]
            if len(fields) >= 13:
                name = fields[1]
                try:
                    change_pct = float(fields[4])
                except (ValueError, IndexError):
                    change_pct = 0.0
                leader_stock = fields[12] if len(fields) > 12 else ""
                result.append({
                    "name": name,
                    "change_pct": round(change_pct, 2),
                    "leader_stock": leader_stock,
                })
    except Exception as e:
        print(f"get_sectors 错误: {e}", file=sys.stderr)
    
    return result

# ============================================================
# 龙虎榜
# ============================================================

def get_top_list(date: str = None) -> list[dict]:
    """获取龙虎榜数据
    
    Args:
        date: 日期，格式 YYYY-MM-DD，默认为当天
    
    Returns:
        [{code, name, close, change_pct, net_buy, buy_amount, sell_amount, reason}]
    """
    result = []
    try:
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        date_fmt = date.replace("-", "")
        # 新浪龙虎榜接口
        # 返回 JSONP, 内含股票代码、名称、上榜原因、净买额等
        url = (
            f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"StockService.getTopList?page=1&num=50&sort=netamount&asc=0&date={date_fmt}&"
            f"bankuai=&sh=&sz=&jj=&qihuo=&etf=&lof=&fjj=&fjjo=&fund="
        )
        text = _http_get(url, encoding="utf-8")
        text = text.strip()
        
        items = []
        if text.startswith("["):
            items = json.loads(text)
        elif text.startswith("{"):
            data = json.loads(text)
            if "data" in data:
                items = data["data"]
            else:
                items = [data]
        else:
            # 尝试提取 JSON
            match = re.search(r'(\[.*\])', text, re.DOTALL)
            if match:
                items = json.loads(match.group(1))
        
        for item in items:
            if not isinstance(item, dict):
                continue
            code = item.get("code", item.get("symbol", ""))
            name = item.get("name", item.get("cname", ""))
            close = float(item.get("close", item.get("price", 0)))
            change_pct = float(item.get("changepercent", item.get("change_pct", 0)))
            net_buy = float(item.get("netamount", item.get("net_buy", 0)))
            buy_amount = float(item.get("buyamount", item.get("buy_amount", 0)))
            sell_amount = float(item.get("sellamount", item.get("sell_amount", 0)))
            reason = item.get("reason", item.get("memo", ""))
            
            result.append({
                "code": code,
                "name": name,
                "close": close,
                "change_pct": change_pct,
                "net_buy": net_buy,
                "buy_amount": buy_amount,
                "sell_amount": sell_amount,
                "reason": reason,
            })
    except Exception as e:
        print(f"get_top_list 错误: {e}", file=sys.stderr)
    
    return result


# ============================================================
# 资金流向
# ============================================================

def _to_eastmoney_secid(code: str) -> str:
    """生成东财 secid: 1.600789(沪) / 0.002446(深)"""
    code = code.upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
    if code.startswith("6"):
        return "1." + code
    elif code.startswith(("0", "3")):
        return "0." + code
    elif code.startswith(("8", "4")):
        return "0." + code  # 北交所
    return "1." + code


def get_money_flow(code: str) -> dict:
    """获取个股资金流向（东财接口）
    
    Args:
        code: 股票代码，如 "600789"
    
    Returns:
        {main_net, super_large, large, medium, small}
    """
    result = {
        "main_net": 0,
        "super_large": 0,
        "large": 0,
        "medium": 0,
        "small": 0,
    }
    try:
        secid = _to_eastmoney_secid(code)
        # 东财日级资金流向 kline 接口
        # klines 格式: "date,main_net,super_large_net,large_net,medium_net,small_net,..."
        url = (
            f"https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get?"
            f"secid={secid}&lmt=1&klt=101&"
            f"fields1=f1,f2,f3,f7&"
            f"fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63&"
            f"ut=b2884a393a59ad64002292a3e90d46a5"
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        text = resp.read().decode("utf-8")
        data = json.loads(text)
        
        klines = data.get("data", {}).get("klines", [])
        if klines:
            fields = klines[-1].split(",")
            # f52=main_net, f53=super_large, f54=large, f55=medium, f56=small
            if len(fields) >= 6:
                result["main_net"] = float(fields[1])
                result["super_large"] = float(fields[2])
                result["large"] = float(fields[3])
                result["medium"] = float(fields[4])
                result["small"] = float(fields[5])
    except Exception as e:
        print(f"get_money_flow 错误: {e}", file=sys.stderr)
    
    return result


# ============================================================
# 命令行界面
# ============================================================

def _format_realtime(data: dict) -> str:
    change_symbol = "+" if data["change_pct"] >= 0 else ""
    lines = [
        f"{'='*50}",
        f"  {data['name']} ({data['code']})",
        f"{'='*50}",
        f"  现价: {data['price']:.2f}  涨跌: {change_symbol}{data['change_pct']:.2f}%",
        f"  今开: {data['open']:.2f}  最高: {data['high']:.2f}  最低: {data['low']:.2f}",
        f"  昨收: {data['pre_close']:.2f}",
        f"  买一: {data['bid']:.2f}  卖一: {data['ask']:.2f}",
        f"  成交量: {data['volume']}手  成交额: {data['amount']/10000:.1f}万",
    ]
    return "\n".join(lines)


def _format_kline(data: list[dict]) -> str:
    if not data:
        return "无K线数据"
    lines = [f"  {'日期':<20} {'开':>8} {'高':>8} {'低':>8} {'收':>8} {'量':>10}"]
    lines.append("  " + "-" * 70)
    for item in data[-20:]:  # 最多显示20条
        lines.append(
            f"  {item['date']:<20} {item['open']:>8.2f} {item['high']:>8.2f} "
            f"{item['low']:>8.2f} {item['close']:>8.2f} {item['volume']:>10}"
        )
    if len(data) > 20:
        lines.insert(0, f"  (共{len(data)}条，显示最后20条)")
    return "\n".join(lines)


def _format_minute(data: list[dict]) -> str:
    if not data:
        return "无分时数据"
    lines = [f"  {'时间':<20} {'价格':>8} {'量(手)':>8} {'均价':>8}"]
    lines.append("  " + "-" * 50)
    for item in data[-20:]:
        lines.append(
            f"  {item['time']:<20} {item['price']:>8.2f} {item['volume']:>8} {item['avg_price']:>8.3f}"
        )
    if len(data) > 20:
        lines.insert(0, f"  (共{len(data)}条，显示最后20条)")
    return "\n".join(lines)


def _format_sectors(data: list[dict]) -> str:
    if not data:
        return "无板块数据"
    lines = [f"  {'板块':<12} {'涨跌幅':>8} {'领涨股':<10}"]
    lines.append("  " + "-" * 40)
    for item in data:
        pct = item["change_pct"]
        symbol = "+" if pct >= 0 else ""
        lines.append(f"  {item['name']:<12} {symbol}{pct:>7.2f}% {item.get('leader_stock', '')}")
    return "\n".join(lines)


def _format_top_list(data: list[dict]) -> str:
    if not data:
        return "无龙虎榜数据"
    lines = [f"  {'代码':<8} {'名称':<8} {'涨跌':>6} {'净买(万)':>10} {'原因'}"]
    lines.append("  " + "-" * 60)
    for item in data:
        lines.append(
            f"  {item['code']:<8} {item['name']:<8} {item['change_pct']:>5.1f}% "
            f"{item['net_buy']/10000:>10.1f} {item.get('reason', '')}"
        )
    return "\n".join(lines)


def _format_money_flow(data: dict) -> str:
    lines = [
        f"{'='*40}",
        f"  资金流向",
        f"{'='*40}",
        f"  主力净流入: {data['main_net']/10000:.1f}万",
        f"  超大单:     {data['super_large']/10000:.1f}万",
        f"  大单:       {data['large']/10000:.1f}万",
        f"  中单:       {data['medium']/10000:.1f}万",
        f"  小单:       {data['small']/10000:.1f}万",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="A股统一数据源")
    sub = parser.add_subparsers(dest="command", help="子命令")
    
    # realtime
    p_rt = sub.add_parser("realtime", help="实时行情")
    p_rt.add_argument("codes", nargs="+", help="股票代码")
    p_rt.add_argument("--json", "-j", action="store_true", help="JSON输出")
    
    # kline
    p_kl = sub.add_parser("kline", help="历史K线")
    p_kl.add_argument("code", help="股票代码")
    p_kl.add_argument("--days", type=int, default=30, help="天数")
    p_kl.add_argument("--scale", default="240", choices=["5", "15", "30", "60", "240"], help="K线周期(分钟)")
    p_kl.add_argument("--json", "-j", action="store_true", help="JSON输出")
    
    # minute
    p_min = sub.add_parser("minute", help="分时数据")
    p_min.add_argument("code", help="股票代码")
    p_min.add_argument("--json", "-j", action="store_true", help="JSON输出")
    
    # sectors
    p_sec = sub.add_parser("sectors", help="板块行情")
    p_sec.add_argument("--json", "-j", action="store_true", help="JSON输出")
    
    # top_list
    p_tl = sub.add_parser("top_list", help="龙虎榜")
    p_tl.add_argument("--date", default=None, help="日期 YYYY-MM-DD")
    p_tl.add_argument("--json", "-j", action="store_true", help="JSON输出")
    
    # money_flow
    p_mf = sub.add_parser("money_flow", help="资金流向")
    p_mf.add_argument("code", help="股票代码")
    p_mf.add_argument("--json", "-j", action="store_true", help="JSON输出")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    if args.command == "realtime":
        data = get_realtime(args.codes)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            for code, d in data.items():
                print(_format_realtime(d))
                print()
    
    elif args.command == "kline":
        data = get_kline(args.code, days=args.days, scale=args.scale)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(_format_kline(data))
    
    elif args.command == "minute":
        data = get_minute(args.code)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(_format_minute(data))
    
    elif args.command == "sectors":
        data = get_sectors()
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(_format_sectors(data))
    
    elif args.command == "top_list":
        data = get_top_list(args.date)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(_format_top_list(data))
    
    elif args.command == "money_flow":
        data = get_money_flow(args.code)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(_format_money_flow(data))


if __name__ == "__main__":
    main()
