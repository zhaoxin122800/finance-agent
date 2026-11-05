#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
report-extractor: 从研报PDF/财报/财经网页中提取关键信息
独立可运行，核心功能不依赖外部库。

用法:
    python extract.py --pdf report.pdf
    python extract.py --url https://finance.example.com/report/...
    python extract.py --text "研报文本..."
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from html import unescape

# Windows UTF-8 兼容
if sys.platform == "win32":
    os.system("")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

# 关键词词典
RATING_KEYWORDS = [
    "买入", "增持", "推荐", "强推", "强烈推荐", "强烈买入",
    "中性", "持有", "减持", "卖出", "回避",
    "跑赢大盘", "跑输大盘", "同步大市",
    "Outperform", "Underperform", "Overweight", "Underweight",
    "Buy", "Hold", "Sell", "Neutral", "Add", "Reduce",
]

RISK_KEYWORDS = [
    "风险提示", "风险因素", "主要风险", "投资风险",
    "潜在风险", "不确定性", "Risks",
]

FINANCIAL_PATTERNS = {
    "revenue": [
        r"营业收入[:\s]*([\d,.]+)\s*亿",
        r"营收[:\s]*([\d,.]+)\s*亿",
        r"总收入[:\s]*([\d,.]+)\s*亿",
        r"Revenue[:\s]*([\d,.]+)\s*billion",
    ],
    "profit": [
        r"归母净利润[:\s]*([\d,.]+)\s*亿",
        r"净利润[:\s]*([\d,.]+)\s*亿",
        r"Net profit[:\s]*([\d,.]+)\s*billion",
    ],
    "pe": [
        r"PE[:\s（(]*([\d.]+)",
        r"市盈率[:\s]*([\d.]+)",
        r"P/E[:\s]*([\d.]+)",
    ],
    "pb": [
        r"PB[:\s（(]*([\d.]+)",
        r"市净率[:\s]*([\d.]+)",
        r"P/B[:\s]*([\d.]+)",
    ],
    "roe": [
        r"ROE[:\s（(]*([\d.]+)\s*%?",
        r"净资产收益率[:\s]*([\d.]+)\s*%?",
    ],
}

# 板块关键词 - 排除容易误匹配的短词
SECTOR_KEYWORDS = [
    "半导体", "芯片", "新能源", "光伏", "风电", "储能", "锂电池",
    "人工智能", "大数据", "云计算", "物联网",
    "医疗器械", "创新药", "中药",
    "白酒", "食品饮料", "零售",
    "保险", "证券", "金融",
    "房地产", "建材", "建筑",
    "军工", "航空航天",
    "电子", "通信", "计算机", "传媒",
    "化工", "钢铁", "有色", "煤炭", "石油",
    "农业", "纺织", "轻工",
    "电力", "环保", "机械",
    "交运", "航空",
    "医药", "生物", "消费", "银行", "汽车",
    "5G", "AI",
]

# 不应作为板块匹配的词（机构名常见组成部分）
SECTOR_EXCLUDE = {"证券"}


def _empty_report():
    return {
        "title": "",
        "institution": "",
        "analyst": "",
        "rating": "",
        "target_price": "",
        "current_price": "",
        "upside": "",
        "core_logic": [],
        "financials": {"revenue": "", "profit": "", "pe": "", "pb": "", "roe": ""},
        "risks": [],
        "sectors": [],
        "stocks": [],
    }


def _extract_title(text):
    """提取研报标题。优先取第一个有意义的行；单行文本按句号截断。"""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # 多行模式：取前10行中第一个合适的长行
    if len(lines) > 1:
        for line in lines[:10]:
            if len(line) > 8 and not any(line.startswith(kw) for kw in RATING_KEYWORDS):
                line = re.sub(r"^[\u4e00-\u9fff]{2,8}证券[\u4e00-\u9fff]*\s*", "", line)
                line = re.sub(r"^【.*?】\s*", "", line)
                if len(line) > 8:
                    return line[:200]
        for line in lines[:20]:
            if len(line) > 15:
                return line[:200]
    else:
        # 单行模式：按句号/分号截断，取第一句作为标题
        first_sentence = re.split(r"[。；;！!？?\n]", lines[0])
        if first_sentence and first_sentence[0]:
            title = first_sentence[0].strip()
            # 去除机构前缀
            title = re.sub(r"^[\u4e00-\u9fff]{2,8}证券[\u4e00-\u9fff]*\s*", "", title)
            title = re.sub(r"^【.*?】\s*", "", title)
            if len(title) > 5:
                return title[:200]
    return ""


def _extract_institution(text):
    patterns = [
        r"([\u4e00-\u9fff]{2,8}证券[\u4e00-\u9fff]*?(?:研究所|研究部)?)",
        r"([\u4e00-\u9fff]{2,6}基金(?:管理)?(?:公司)?)",
        r"([\u4e00-\u9fff]{2,6}(?:资本|投资)(?:管理)?(?:公司)?)",
        r"(中信[\u4e00-\u9fff]*|中金[\u4e00-\u9fff]*|国泰君安[\u4e00-\u9fff]*|华泰[\u4e00-\u9fff]*|招商证券[\u4e00-\u9fff]*|海通证券[\u4e00-\u9fff]*|广发证券[\u4e00-\u9fff]*|兴业证券[\u4e00-\u9fff]*|东方证券[\u4e00-\u9fff]*|平安证券[\u4e00-\u9fff]*|国信证券[\u4e00-\u9fff]*|银河证券[\u4e00-\u9fff]*)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text[:2000])
        if m:
            return m.group(1).strip()
    return ""


def _extract_analyst(text):
    patterns = [
        r"分析师[:：\s]*([\u4e00-\u9fff]{2,4})",
        r"研究员[:：\s]*([\u4e00-\u9fff]{2,4})",
        r"执证分析师[:：\s]*([\u4e00-\u9fff]{2,4})",
        r"作者[:：\s]*([\u4e00-\u9fff]{2,4})",
        r"([\u4e00-\u9fff]{2,4})\s*\(S\d{6,}\)",
        r"([\u4e00-\u9fff]{2,4})\s*分析师",
    ]
    for pattern in patterns:
        m = re.search(pattern, text[:3000])
        if m:
            return m.group(1).strip()
    return ""


def _extract_rating(text):
    priority = ["强烈买入", "强烈推荐", "买入", "增持", "推荐", "强推",
                "跑赢大盘", "中性", "持有", "同步大市",
                "减持", "卖出", "回避", "跑输大盘",
                "Outperform", "Overweight", "Buy", "Add",
                "Neutral", "Hold",
                "Underperform", "Underweight", "Sell", "Reduce"]
    text_lower = text.lower()
    for kw in priority:
        if kw in text:
            return kw
        if kw.lower() in text_lower:
            return kw
    return ""


def _extract_target_price(text):
    patterns = [
        r"目标价[:\s]*([\d,.]+)\s*元?",
        r"目标价格[:\s]*([\d,.]+)\s*元?",
        r"合理估值[:\s]*([\d,.]+)\s*元?",
        r"合理价格[:\s]*([\d,.]+)\s*元?",
        r"Target\s*Price[:\s]*([\d,.]+)",
        r"6\s*个月目标价[:\s]*([\d,.]+)\s*元?",
        r"12个月目标价[:\s]*([\d,.]+)\s*元?",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _extract_current_price(text):
    patterns = [
        r"当前价[:\s]*([\d,.]+)\s*元?",
        r"现价[:\s]*([\d,.]+)\s*元?",
        r"收盘价[:\s]*([\d,.]+)\s*元?",
        r"股价[:\s]*([\d,.]+)\s*元?",
        r"Current\s*Price[:\s]*([\d,.]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _extract_upside(text, target, current):
    patterns = [
        r"上涨空间[:\s]*([\d.]+)\s*%?",
        r"涨幅[:\s]*([\d.]+)\s*%?",
        r"upside[:\s]*([\d.]+)\s*%?",
        r"空间[:\s]*([\d.]+)\s*%?",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if not val.endswith("%"):
                val += "%"
            return val
    if target and current:
        try:
            t = float(target.replace(",", ""))
            c = float(current.replace(",", ""))
            if c > 0:
                upside = ((t - c) / c) * 100
                return f"{upside:.1f}%"
        except (ValueError, ZeroDivisionError):
            pass
    return ""


def _extract_core_logic(text):
    logics = []
    # 方案1: 找"核心逻辑"等段落标题
    section_patterns = [
        r"(?:核心逻辑|投资要点|推荐逻辑|投资逻辑|主要逻辑|核心观点|我们的观点)[:：\s]*\n((?:.*\n){1,15})",
        r"(?:核心逻辑|投资要点|推荐逻辑|投资逻辑|主要逻辑|核心观点|我们的观点)[:：\s]*(.+?)(?:\n\s*\n|\n[风险|财务|盈利|估值])",
    ]
    for pattern in section_patterns:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            section = m.group(1).strip()
            items = re.split(r"[\n]\s*(?:\d+[.、）)]|[•·①②③④⑤⑥⑦⑧⑨⑩])\s*", section)
            items = [item.strip().rstrip("。；;") for item in items if item.strip() and len(item.strip()) > 5]
            if items:
                logics.extend(items[:8])
                break
    # 方案1b: 单行文本中"核心逻辑："后面的编号内容
    if not logics:
        m = re.search(r"(?:核心逻辑|投资要点|推荐逻辑|投资逻辑|主要逻辑|核心观点)[:：\s]*(.+?)(?:风险提示|风险因素|$)", text, re.DOTALL)
        if m:
            section = m.group(1).strip()
            # 按编号分割
            items = re.split(r"\s*\d+[.、）)]\s*", section)
            items = [item.strip().rstrip("。；;") for item in items if item.strip() and len(item.strip()) > 5]
            if items:
                logics.extend(items[:8])
    # 方案2: 找带编号的要点行
    if not logics:
        bullet_pattern = r"(?:^|\n)\s*(?:\d+[.、）)]|[•·①②③④⑤⑥⑦⑧⑨⑩])\s*(.{10,120})"
        matches = re.findall(bullet_pattern, text)
        seen = set()
        for match in matches:
            match = match.strip().rstrip("。；;")
            if len(match) > 10 and match not in seen:
                seen.add(match)
                logics.append(match)
            if len(logics) >= 6:
                break
    # 方案3: 找"我们认为"、"预计"等句式
    if not logics:
        opinion_patterns = [
            r"我们认为[,，：:]?\s*(.+?)(?:[。；;\n]|\n)",
            r"预计[,，：:]?\s*(.+?)(?:[。；;\n]|\n)",
            r"我们判断[,，：:]?\s*(.+?)(?:[。；;\n]|\n)",
        ]
        for pattern in opinion_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                match = match.strip()
                if len(match) > 10:
                    logics.append(match)
                if len(logics) >= 5:
                    break
            if len(logics) >= 5:
                break
    return logics[:8]


def _extract_financials(text):
    financials = {"revenue": "", "profit": "", "pe": "", "pb": "", "roe": ""}
    for key, patterns in FINANCIAL_PATTERNS.items():
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                financials[key] = m.group(1).strip()
                break
    return financials


def _extract_risks(text):
    risks = []
    # Boundary keywords that mark end of risk section
    boundary_re = re.compile(r'\u76f8\u5173\u677f\u5757|\u63a8\u8350\u4e2a\u80a1|\u6838\u5fc3\u903b\u8f91|\u6295\u8d44\u8981\u70b9|\u76c8\u5229\u9884\u6d4b|\u4f30\u503c\u5206\u6790')
    for kw in RISK_KEYWORDS:
        patterns = [
            rf"{kw}[:\uff1a\s]*\n((?:.*\n){{1,10}})",
            rf"{kw}[:\uff1a\s]*(.+?)(?:\n\s*\n|\n[\u6295\u8d44|\u8d22\u52a1|\u76c8\u5229|\u4f30\u503c|\u6838\u5fc3])",
            rf"{kw}[:\uff1a\s]*(.+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.DOTALL)
            if m:
                section = m.group(1).strip()
                # Cut at boundary keywords for single-line text
                boundary_m = boundary_re.search(section)
                if boundary_m:
                    section = section[:boundary_m.start()].strip()
                items = re.split(r"(?:\n|\uff1b|;)\s*(?:\d+[.\u3001\uff09)]|[\u2022\u00b7\u2460-\u2469])?\s*", section)
                items = [item.strip().rstrip("\u3002\uff1b;") for item in items if item.strip() and len(item.strip()) > 5]
                # Filter out items containing non-risk content
                items = [item for item in items if not boundary_re.search(item)]
                if items:
                    risks.extend(items[:6])
                    break
        if risks:
            break
    if not risks:
        risk_sentences = re.findall(r"(.{10,80}\u98ce\u9669.{0,40})", text)
        seen = set()
        for sent in risk_sentences:
            sent = sent.strip().rstrip("\u3002\uff1b;")
            if sent not in seen and len(sent) > 10:
                seen.add(sent)
                risks.append(sent)
            if len(risks) >= 4:
                break
    return risks[:6]


def _extract_sectors(text):
    found = []
    text_lower = text.lower()
    for sector in SECTOR_KEYWORDS:
        # "证券"只在非机构名上下文匹配
        if sector in SECTOR_EXCLUDE:
            # 只匹配"板块"前的"证券"
            if re.search(rf"{sector}(?:板块|行业|概念)", text):
                found.append(sector)
            continue
        if sector in text or sector.lower() in text_lower:
            if sector not in found:
                found.append(sector)
    return found[:10]


def _extract_stocks(text):
    stocks = []
    patterns = [
        r"([\u4e00-\u9fff]{2,6})(?:\(|（)(\d{6})(?:\)|）)",
        r"([\u4e00-\u9fff]{2,6})\s*\((\d{4,6}\.?(?:SH|SZ|HK|US)?)\)",
        r"([\u4e00-\u9fff]{2,6})\s*\((\d{4,5})\.HK\)",
    ]
    seen = set()
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for name, code in matches:
            name = name.strip()
            if name not in seen and len(name) >= 2:
                seen.add(name)
                stocks.append(f"{name}({code})")
        if len(stocks) >= 10:
            break
    return stocks[:10]


def _read_pdf(pdf_path):
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n\n".join(text_parts)
    except ImportError:
        pass
    except Exception as e:
        print(f"[pdfplumber 读取失败] {e}", file=sys.stderr)
    try:
        import PyPDF2
        text_parts = []
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n\n".join(text_parts)
    except ImportError:
        pass
    except Exception as e:
        print(f"[PyPDF2 读取失败] {e}", file=sys.stderr)
    return ""


def _fetch_url(url):
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        encoding = "utf-8"
        content_type = resp.headers.get("Content-Type", "")
        if "charset=" in content_type:
            encoding = content_type.split("charset=")[-1].strip()
        else:
            meta_match = re.search(rb'charset=["\']?([\w-]+)', raw[:2048])
            if meta_match:
                encoding = meta_match.group(1).decode("ascii", errors="ignore")
        html = raw.decode(encoding, errors="replace")
        return _html_to_text(html)
    except urllib.error.URLError as e:
        print(f"[URL 抓取失败] {e}", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"[URL 处理失败] {e}", file=sys.stderr)
        return ""


def _html_to_text(html):
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    html = re.sub(r"<(?:br|/p|/div|/h[1-6]|/li)[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<(?:p|div|h[1-6]|li)[^>]*>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", html)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_report(text):
    if not text or not text.strip():
        return _empty_report()
    text = text.strip()
    text_clean = re.sub(r"[ \t]+", " ", text)
    text_clean = re.sub(r"\n{3,}", "\n\n", text_clean)
    report = _empty_report()
    report["title"] = _extract_title(text_clean)
    report["institution"] = _extract_institution(text_clean)
    report["analyst"] = _extract_analyst(text_clean)
    report["rating"] = _extract_rating(text_clean)
    report["target_price"] = _extract_target_price(text_clean)
    report["current_price"] = _extract_current_price(text_clean)
    report["upside"] = _extract_upside(text_clean, report["target_price"], report["current_price"])
    report["core_logic"] = _extract_core_logic(text_clean)
    report["financials"] = _extract_financials(text_clean)
    report["risks"] = _extract_risks(text_clean)
    report["sectors"] = _extract_sectors(text_clean)
    report["stocks"] = _extract_stocks(text_clean)
    return report


def extract_from_pdf(pdf_path):
    text = _read_pdf(pdf_path)
    if not text:
        print(f"[警告] 无法从PDF提取文本: {pdf_path}", file=sys.stderr)
        print("[提示] 可尝试使用 pdf skill 先读取PDF内容，再用 --text 模式提取", file=sys.stderr)
        return _empty_report()
    return extract_report(text)


def extract_from_url(url):
    text = _fetch_url(url)
    if not text:
        print(f"[警告] 无法从URL获取内容: {url}", file=sys.stderr)
        print("[提示] 可尝试使用 autoglm-open-link skill 获取网页正文，再用 --text 模式提取", file=sys.stderr)
        return _empty_report()
    return extract_report(text)


def format_brief(report):
    lines = []
    lines.append("=" * 60)
    lines.append("📊 研报摘要")
    lines.append("=" * 60)
    if report.get("title"):
        lines.append(f"\n📄 标题: {report['title']}")
    if report.get("institution"):
        lines.append(f"🏛️ 机构: {report['institution']}")
    if report.get("analyst"):
        lines.append(f"👤 分析师: {report['analyst']}")
    price_info = []
    if report.get("rating"):
        price_info.append(f"评级: {report['rating']}")
    if report.get("target_price"):
        price_info.append(f"目标价: {report['target_price']}元")
    if report.get("current_price"):
        price_info.append(f"当前价: {report['current_price']}元")
    if report.get("upside"):
        price_info.append(f"上涨空间: {report['upside']}")
    if price_info:
        lines.append(f"\n💰 {' | '.join(price_info)}")
    if report.get("core_logic"):
        lines.append("\n📝 核心逻辑:")
        for i, logic in enumerate(report["core_logic"], 1):
            lines.append(f"  {i}. {logic}")
    fin = report.get("financials", {})
    fin_items = []
    if fin.get("revenue"):
        fin_items.append(f"营收 {fin['revenue']}亿")
    if fin.get("profit"):
        fin_items.append(f"净利 {fin['profit']}亿")
    if fin.get("pe"):
        fin_items.append(f"PE {fin['pe']}")
    if fin.get("pb"):
        fin_items.append(f"PB {fin['pb']}")
    if fin.get("roe"):
        fin_items.append(f"ROE {fin['roe']}%")
    if fin_items:
        lines.append(f"\n📈 财务: {' | '.join(fin_items)}")
    if report.get("sectors"):
        lines.append(f"\n🏭 板块: {', '.join(report['sectors'])}")
    if report.get("stocks"):
        lines.append(f"\n🏷️ 个股: {', '.join(report['stocks'])}")
    if report.get("risks"):
        lines.append("\n⚠️ 风险提示:")
        for i, risk in enumerate(report["risks"], 1):
            lines.append(f"  {i}. {risk}")
    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="从研报PDF/财报/财经网页中提取关键信息",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python extract.py --pdf report.pdf
  python extract.py --url https://finance.example.com/report/...
  python extract.py --text "买入评级，目标价50元..."
        """
    )
    parser.add_argument("--pdf", metavar="PATH", help="PDF文件路径")
    parser.add_argument("--url", metavar="URL", help="网页URL")
    parser.add_argument("--text", metavar="TEXT", help="研报文本")
    parser.add_argument("--format", choices=["json", "brief"], default="json",
                        help="输出格式: json(默认) 或 brief(摘要)")
    args = parser.parse_args()
    if not args.pdf and not args.url and not args.text:
        parser.print_help()
        sys.exit(1)
    report = None
    if args.pdf:
        if not os.path.isfile(args.pdf):
            print(f"[错误] 文件不存在: {args.pdf}", file=sys.stderr)
            sys.exit(1)
        report = extract_from_pdf(args.pdf)
    elif args.url:
        report = extract_from_url(args.url)
    elif args.text:
        report = extract_report(args.text)
    if report is None:
        print("[错误] 提取失败", file=sys.stderr)
        sys.exit(1)
    if args.format == "brief":
        print(format_brief(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
