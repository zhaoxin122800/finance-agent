#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
policy-monitor: A股政策监控脚本
搜索财经政策新闻，提炼关键信息，关联板块/个股。
独立可运行，仅使用 Python 标准库。
"""

import sys
import os
import json
import re
import html
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta
from html.parser import HTMLParser

# ─── Windows UTF-8 兼容 ───────────────────────────────────────────
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# ─── 默认配置 ─────────────────────────────────────────────────────
DEFAULT_KEYWORDS = ["证监会", "央行", "国务院", "发改委", "财政部", "银保监会", "金融监管总局", "工信部", "商务部", "税务总局"]
DEFAULT_LIMIT = 20
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ─── 板块/个股关键词映射 ──────────────────────────────────────────
SECTOR_KEYWORDS = {
    "半导体/芯片": ["半导体", "芯片", "集成电路", "光刻", "封装", "晶圆", "EDA", "国产替代", "中芯国际", "北方华创", "中微公司", "韦尔股份", "长电科技"],
    "新能源": ["新能源", "光伏", "风电", "储能", "锂电", "碳酸锂", "宁德时代", "比亚迪", "隆基绿能", "阳光电源", "逆变器", "硅料"],
    "医药/医疗": ["医药", "医疗", "药品", "创新药", "集采", "医保", "器械", "药明康德", "恒瑞医药", "迈瑞医疗", "联影医疗"],
    "房地产": ["房地产", "楼市", "住房", "公积金", "房贷", "保交楼", "万科", "保利", "融创", "保障房", "城中村"],
    "金融/银行": ["银行", "券商", "保险", "金融", "降准", "降息", "MLF", "LPR", "逆回购", "工商银行", "招商银行", "中信证券"],
    "人工智能/算力": ["人工智能", "AI", "算力", "大模型", "GPU", "智算", "数据要素", "浪潮信息", "中科曙光", "寒武纪", "科大讯飞"],
    "军工/国防": ["军工", "国防", "装备", "航天", "航空", "中航沈飞", "中航西飞", "中国船舶", "兵器"],
    "消费/零售": ["消费", "零售", "免税", "文旅", "促消费", "家电", "汽车", "以旧换新", "贵州茅台", "美的集团", "海尔智家"],
    "农业": ["农业", "种业", "粮食", "化肥", "猪肉", "转基因", "北大荒", "隆平高科", "牧原股份"],
    "环保/碳": ["环保", "碳中和", "碳达峰", "减排", "绿色", "新能源车", "排放"],
    "通信/5G": ["通信", "5G", "6G", "光纤", "基站", "中国电信", "中国移动", "中国联通", "中兴通讯"],
    "汽车": ["汽车", "新能源汽车", "智能驾驶", "车路协同", "自动驾驶", "比亚迪", "长城汽车", "理想汽车", "蔚来"],
}

# 利好/利空关键词
POSITIVE_KEYWORDS = ["支持", "鼓励", "促进", "推动", "加大", "加快", "降低", "减免", "补贴", "放松", "优化", "利好", "提振", "积极", "加强", "提升", "扩大", "实施", "推进", "落实", "完善", "保障", "增加", "减税", "降费", "优惠"]
NEGATIVE_KEYWORDS = ["限制", "收紧", "处罚", "禁止", "严控", "查处", "整顿", "规范", "约束", "利空", "风险", "警示", "监管", "约谈", "叫停", "冻结", "收缩", "提高", "加大力度", "打击", "违规"]

# ─── HTML 文本提取 ────────────────────────────────────────────────
class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._text = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._text.append(data)

    def get_text(self):
        return "".join(self._text)


def _html_to_text(html_str):
    if not html_str:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(html_str)
    except Exception:
        pass
    return parser.get_text()


def _clean_text(text):
    """清理文本：去 HTML 实体、多余空白、换行。"""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

# ─── HTTP 请求 ────────────────────────────────────────────────────
def _fetch(url, headers=None, timeout=REQUEST_TIMEOUT):
    """发起 HTTP GET 请求，返回文本。"""
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except Exception as e:
        sys.stderr.write(f"[fetch error] {url}: {e}\n")
        return ""

# ─── 新闻源: 财联社电报 ───────────────────────────────────────────
def _fetch_cls_telegraph(keywords=None, limit=10):
    """从财联社电报 API 获取最新电报，筛选政策相关。

    使用网页版 /v1/roll/get_roll_list 端点 + MD5(SHA1(qs)) 签名(逆向自 cls.cn 前端)。
    旧 nodeapi/updateTelegraphList 端点已下线(404)。
    """
    import hashlib

    params = {
        "app": "CailianpressWeb",
        "os": "web",
        "refresh_type": "1",
        "rn": max(limit, 20),
        "sv": "8.7.9",  # 网页当前版本,旧值 errno=10012
    }
    # 签名:参数排序后 key=value 用 & 连接,过滤空值,先 SHA1 再 MD5
    sign_parts = []
    for k in sorted(params):
        v = params[k]
        if v in (None, ""):
            continue
        sign_parts.append(f"{k}={v}")
    qs = "&".join(sign_parts)
    params["sign"] = hashlib.md5(hashlib.sha1(qs.encode("utf-8")).hexdigest().encode("utf-8")).hexdigest()

    url = "https://www.cls.cn/v1/roll/get_roll_list?" + urllib.parse.urlencode(params)
    raw = _fetch(url, headers={"Referer": "https://www.cls.cn/telegraph"})
    if not raw:
        return []
    results = []
    try:
        data = json.loads(raw)
        if data.get("errno") not in (0, "0"):
            sys.stderr.write(f"[cls error] errno={data.get('errno')} msg={data.get('msg')}\n")
            return []
        items = data.get("data", {}).get("roll_data", []) or []
        for item in items:
            content = _clean_text(item.get("content", "") or item.get("brief", ""))
            text = content
            if keywords:
                if not any(kw in text for kw in keywords):
                    continue
            elif not any(kw in text for kw in DEFAULT_KEYWORDS):
                continue
            ctime = item.get("ctime", 0)
            time_str = ""
            if ctime:
                try:
                    time_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError):
                    pass
            results.append({
                "title": content[:100],
                "source": "财联社",
                "time": time_str,
                "url": item.get("shareurl", "") or f"https://www.cls.cn/detail/{item.get('id', '')}",
                "summary": content[:200],
            })
            if len(results) >= limit:
                break
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        sys.stderr.write(f"[cls parse error] {e}\n")
    return results

# ─── 新闻源: 东方财富 ─────────────────────────────────────────────
def _fetch_eastmoney_news(keywords=None, limit=10):
    """从东方财富新闻 API 获取政策相关新闻。"""
    url = f"https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?client=web&biz=web_news_col&column=350&order=1&needInteractData=0&page_index=1&page_size={limit}"
    raw = _fetch(url)
    if not raw:
        return []
    results = []
    try:
        data = json.loads(raw)
        # data 字段可能为 null(接口改版需 req_trace 参数),容错处理
        data_obj = data.get("data") or {}
        if isinstance(data_obj, dict):
            items = data_obj.get("list", []) or []
        elif isinstance(data_obj, list):
            items = data_obj
        else:
            items = []
        for item in items:
            title = _clean_text(item.get("title", ""))
            content = _clean_text(item.get("digest", "") or item.get("content", ""))
            text = f"{title} {content}"
            if keywords:
                if not any(kw in text for kw in keywords):
                    continue
            pub_time = item.get("showtime", "") or item.get("publishDate", "")
            results.append({
                "title": title[:100],
                "source": "东方财富",
                "time": pub_time[:16] if pub_time else "",
                "url": item.get("url_w", "") or item.get("url", ""),
                "summary": content[:200] if content else title,
            })
            if len(results) >= limit:
                break
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        sys.stderr.write(f"[eastmoney parse error] {e}\n")
    return results

# ─── 新闻源: 新浪财经 ─────────────────────────────────────────────
def _fetch_sina_finance(keywords=None, limit=10):
    """从新浪财经获取政策新闻。"""
    url = f"https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k=&num={limit * 2}&page=1"
    raw = _fetch(url)
    if not raw:
        return []
    results = []
    try:
        data = json.loads(raw)
        # 新浪真实结构是 data["result"]["data"](旧代码误读 data["data"],导致永远空列表)
        result = data.get("result", {})
        items = result.get("data", []) if isinstance(result, dict) else []
        for item in items:
            title = _clean_text(item.get("title", ""))
            content = _clean_text(item.get("intro", "") or item.get("summary", ""))
            text = f"{title} {content}"
            if keywords:
                if not any(kw in text for kw in keywords):
                    continue
            elif not any(kw in text for kw in DEFAULT_KEYWORDS):
                continue
            pub_time = item.get("ctime", "")
            if pub_time:
                try:
                    pub_time = datetime.fromtimestamp(int(pub_time)).strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError):
                    pass
            results.append({
                "title": title[:100],
                "source": "新浪财经",
                "time": pub_time,
                "url": item.get("url", ""),
                "summary": content[:200] if content else title,
            })
            if len(results) >= limit:
                break
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        sys.stderr.write(f"[sina parse error] {e}\n")
    return results

# ─── 核心函数 ─────────────────────────────────────────────────────

def search_policy_news(keywords=None, limit=20):
    """
    搜索最新政策新闻。

    Args:
        keywords: 关键词列表，默认使用 DEFAULT_KEYWORDS
        limit: 返回条数上限

    Returns:
        [{title, source, time, url, summary}, ...]
    """
    if keywords is None:
        keywords = DEFAULT_KEYWORDS

    per_source = max(limit, 15)
    all_news = []

    all_news.extend(_fetch_cls_telegraph(keywords, per_source))
    all_news.extend(_fetch_eastmoney_news(keywords, per_source))
    all_news.extend(_fetch_sina_finance(keywords, per_source))

    # 去重（按标题前30字）
    seen = set()
    deduped = []
    for item in all_news:
        title_key = item["title"][:30]
        if title_key not in seen:
            seen.add(title_key)
            deduped.append(item)

    # 按时间排序（新的在前）
    deduped.sort(key=lambda x: x.get("time", ""), reverse=True)

    return deduped[:limit]


def extract_policy_points(text):
    """
    从政策新闻文本中提取关键要点。

    Args:
        text: 政策新闻文本

    Returns:
        要点字符串列表
    """
    if not text:
        return []

    points = []

    sentences = re.split(r"[。；！？\n]", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 8]

    action_patterns = [
        r"(发布|印发|出台|公布|实施|执行|开展|推进|落实|启动|批准|同意|决定|要求|明确|规定)",
        r"(支持|鼓励|促进|推动|加快|加大|加强|提升|扩大|优化|完善|保障)",
        r"(限制|禁止|严控|处罚|整顿|规范|约束|收紧|叫停|冻结)",
        r"(降准|降息|加息|减税|降费|补贴|优惠|减免|贴息)",
        r"(目标|规划|计划|方案|措施|意见|办法|通知|规定|条例)",
        r"\d+[%％]|\d+亿[元]|万亿",
    ]

    for sent in sentences:
        for pattern in action_patterns:
            if re.search(pattern, sent):
                sent = _clean_text(sent)
                if 8 <= len(sent) <= 150:
                    points.append(sent)
                break

    return points[:10]


def relate_stocks(policy_text):
    """
    根据政策文本关联板块和个股，判断情绪。

    Args:
        policy_text: 政策新闻文本

    Returns:
        {sectors: [...], stocks: [...], sentiment: "利好/利空/中性"}
    """
    if not policy_text:
        return {"sectors": [], "stocks": [], "sentiment": "中性"}

    sectors = []
    stocks = []

    for sector, keywords in SECTOR_KEYWORDS.items():
        matched = False
        for kw in keywords:
            if kw in policy_text:
                matched = True
                if kw not in stocks and len(kw) >= 4:
                    stocks.append(kw)
        if matched and sector not in sectors:
            sectors.append(sector)

    pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in policy_text)
    neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in policy_text)

    if pos_count > neg_count + 1:
        sentiment = "利好"
    elif neg_count > pos_count + 1:
        sentiment = "利空"
    else:
        sentiment = "中性"

    return {
        "sectors": sectors[:8],
        "stocks": stocks[:15],
        "sentiment": sentiment,
    }


def daily_brief():
    """
    生成政策日报：搜索当日政策新闻，提取要点，关联板块/个股。

    Returns:
        格式化的中文文本
    """
    today = datetime.now().strftime("%Y-%m-%d")
    news = search_policy_news(limit=30)

    if not news:
        return f"📋 A股政策日报 — {today}\n\n今日未抓取到政策相关新闻，可能是非交易日或数据源暂时不可用。"

    analyzed = []
    for item in news:
        full_text = f"{item['title']} {item['summary']}"
        points = extract_policy_points(full_text)
        relation = relate_stocks(full_text)
        analyzed.append({
            **item,
            "points": points,
            "relation": relation,
        })

    all_sectors = []
    all_stocks = []
    sentiment_count = {"利好": 0, "利空": 0, "中性": 0}
    for a in analyzed:
        for s in a["relation"]["sectors"]:
            if s not in all_sectors:
                all_sectors.append(s)
        for s in a["relation"]["stocks"]:
            if s not in all_stocks:
                all_stocks.append(s)
        sentiment_count[a["relation"]["sentiment"]] += 1

    lines = []
    lines.append(f"📋 A股政策日报 — {today}")
    lines.append("=" * 50)
    lines.append("")

    dominant = max(sentiment_count, key=sentiment_count.get)
    lines.append(f"📊 今日政策情绪: {dominant}（利好{sentiment_count['利好']} / 中性{sentiment_count['中性']} / 利空{sentiment_count['利空']}）")
    if all_sectors:
        lines.append(f"🏢 受影响板块: {', '.join(all_sectors[:8])}")
    if all_stocks:
        lines.append(f"📈 关联个股: {', '.join(all_stocks[:10])}")
    lines.append("")
    lines.append("-" * 50)
    lines.append("")

    lines.append("📰 重要政策动态：")
    lines.append("")
    for i, a in enumerate(analyzed[:15], 1):
        lines.append(f"{i}. [{a['source']}] {a['title']}")
        lines.append(f"   时间: {a['time']}")
        if a["points"]:
            lines.append(f"   要点:")
            for p in a["points"][:3]:
                lines.append(f"   • {p}")
        if a["relation"]["sectors"] or a["relation"]["sentiment"] != "中性":
            parts = []
            if a["relation"]["sectors"]:
                parts.append(f"板块: {', '.join(a['relation']['sectors'][:3])}")
            parts.append(f"情绪: {a['relation']['sentiment']}")
            lines.append(f"   {' | '.join(parts)}")
        if a["url"]:
            lines.append(f"   链接: {a['url']}")
        lines.append("")

    lines.append("-" * 50)
    lines.append("⚠️ 以上信息来自公开新闻源，仅供参考，不构成投资建议。")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return "\n".join(lines)


# ─── 命令行入口 ───────────────────────────────────────────────────
def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="A股政策监控工具")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    search_parser = subparsers.add_parser("search", help="搜索最新政策新闻")
    search_parser.add_argument("--keyword", "-k", action="append", dest="keywords",
                               help="搜索关键词（可多次指定）")
    search_parser.add_argument("--limit", "-l", type=int, default=DEFAULT_LIMIT,
                               help=f"返回条数上限（默认{DEFAULT_LIMIT}）")

    subparsers.add_parser("brief", help="生成政策日报")

    relate_parser = subparsers.add_parser("relate", help="分析文本关联板块/个股")
    relate_parser.add_argument("text", help="要分析的文本")

    args = parser.parse_args()

    if args.command == "search":
        keywords = args.keywords if args.keywords else None
        news = search_policy_news(keywords=keywords, limit=args.limit)
        if not news:
            print("未找到相关政策新闻。")
            return
        print(f"🔍 搜索到 {len(news)} 条政策新闻：\n")
        for i, item in enumerate(news, 1):
            print(f"{i}. [{item['source']}] {item['title']}")
            print(f"   时间: {item['time']}")
            print(f"   摘要: {item['summary'][:100]}")
            if item["url"]:
                print(f"   链接: {item['url']}")
            print()

    elif args.command == "brief":
        print(daily_brief())

    elif args.command == "relate":
        result = relate_stocks(args.text)
        points = extract_policy_points(args.text)
        print("📊 分析结果：")
        print(f"  板块: {', '.join(result['sectors']) if result['sectors'] else '无'}")
        print(f"  个股: {', '.join(result['stocks']) if result['stocks'] else '无'}")
        print(f"  情绪: {result['sentiment']}")
        if points:
            print(f"  政策要点:")
            for p in points:
                print(f"    • {p}")

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
