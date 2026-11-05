"""个股 AI 解读 service —— 3 维度并行分析。

借鉴 TradingAgents-astock 的多 Analyst 架构,但不引入 LangGraph:
- 量价技术面(TECHNICAL_PROMPT)
- 资金面/游资(CAPITAL_PROMPT,A 股核心)
- 基本面/估值(FUNDAMENTAL_PROMPT)
3 个维度用 ThreadPoolExecutor 并行调 LLM,任一失败不影响其它,合并后归档。
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from app.ai.client import AIClient, AIClientError
from app.ai.kb import format_for_prompt, search
from app.ai.prompts import ACTION_PROMPT, BUSINESS_PROMPT, CAPITAL_PROMPT, FUNDAMENTAL_PROMPT, TECHNICAL_PROMPT
from app.services import state

log = logging.getLogger("finance-agent.interpret")


def _extract_technical_data(d: dict) -> dict:
    return {"kline": d.get("kline", []), "realtime": d.get("realtime", {}), "minute": d.get("minute_analysis", {})}


def _extract_capital_data(d: dict) -> dict:
    return {
        "money_flow": d.get("money_flow", {}),
        "top_list": d.get("top_list_reason", "") or ("龙虎榜上榜" if d.get("on_top_list") else ""),
        "realtime": d.get("realtime", {}),
    }


def _extract_fundamental_data(d: dict) -> dict:
    return {"realtime": d.get("realtime", {})}


def _extract_business_data(d: dict) -> dict:
    return {"company": d.get("company", {})}


# 维度定义:(key, 中文标题, prompt 模板, 该维度数据提取-微调)
# 模板二级定义,提取-微调已在上方定义
DIMENSIONS = [
    ("technical", "📊 量价技术面", TECHNICAL_PROMPT, _extract_technical_data),
    ("capital", "💰 资金面 / 游资", CAPITAL_PROMPT, _extract_capital_data),
    ("fundamental", "🪙 基本面 / 估值", FUNDAMENTAL_PROMPT, _extract_fundamental_data),
    ("business", "🏭 公司画像 / 产业链定位", BUSINESS_PROMPT, _extract_business_data),
]


def build_rag_context(code: str, data: dict) -> str:
    """从 quant-kb 检索相关知识,注入各维度 system prompt。"""
    name = data.get("realtime", {}).get("name", "")
    keywords = [code, name, "量能", "资金流", "均线", "估值"]
    return format_for_prompt(search(keywords))


def _run_dimension(name: str, title: str, prompt_template: str, extractor, code: str, data: dict, ai: AIClient, context: str) -> tuple[str, str]:
    """单维度分析。返回 (维度名, markdown 或错误提示)。"""
    dim_data = extractor(data)
    system = prompt_template.format(**{k: json.dumps(v, ensure_ascii=False, default=str) for k, v in dim_data.items()})
    try:
        content = ai.complete(system=system, user=f"请分析股票 {code} 的该维度", context=context)
        return (name, content)
    except AIClientError as e:
        log.warning("维度 %s 分析失败(%s): %s", name, code, e)
        return (name, f"⚠️ {title} 维度分析暂不可用({e})。")


def interpret_stock(code: str, analyst_data: dict, ai: AIClient | None) -> str:
    """生成多维度 AI 解读并归档。ai=None 时返回降级提示。"""
    today = date.today().isoformat()
    archived = load_archived(code, today)
    if archived:
        return archived

    if ai is None:
        return "⚠️ AI 解读未启用。请在 .env 配置 LLM_API_KEY 后重试。原始数据已展示在上方。"

    context = build_rag_context(code, analyst_data)
    results: dict[str, str] = {}
    # 并行 N 维度(技术/资金/基本面/公司画像)
    with ThreadPoolExecutor(max_workers=len(DIMENSIONS)) as pool:
        futures = {
            pool.submit(_run_dimension, name, title, tpl, ext, code, analyst_data, ai, context): name
            for name, title, tpl, ext in DIMENSIONS
        }
        for fut in as_completed(futures):
            dim_name, content = fut.result()
            results[dim_name] = content

    # 按固定顺序合并(技术→资金→基本面→公司画像)
    sections = []
    for name, title, _, _ in DIMENSIONS:
        sections.append(f"## {title}\n\n{results.get(name, '⚠️ 该维度未生成。')}")

    markdown = f"# {code} AI 多维度解读\n\n" + "\n\n---\n\n".join(sections)
    markdown += "\n\n---\n*免责:数据来自免费行情源,分析仅供参考,不构成投资建议。*"
    archive(code, today, markdown)
    return markdown


def archive(code: str, day: str, markdown: str) -> None:
    """归档到 data/analyses/{code}-{day}.md。"""
    path = state.DATA_DIR / "analyses" / f"{code}-{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")


def load_archived(code: str, day: str) -> str | None:
    """读已归档解读,无则 None。"""
    path = state.DATA_DIR / "analyses" / f"{code}-{day}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def generate_action_advice(
    code: str,
    analyst_data: dict,
    account_summary: dict,
    ai: AIClient | None,
) -> str:
    """生成加购/操作建议(结合整个账户 + 该股分析)。单次 LLM 调用。

    - account_summary: 包含 total_assets/cash/positions_detail 等的账户汇总(review.summarize_account 输出)
    - 建议归档到 data/advice/{code}-{day}.md(同日去重)
    """
    today = date.today().isoformat()
    archived = _load_advice(code, today)
    if archived:
        return archived

    if ai is None:
        return "⚠️ AI 未启用。请在 .env 配置 LLM_API_KEY 后使用加购建议。"

    # 该股在账户中的持仓(从 positions_detail 找)
    position = next((p for p in account_summary.get("positions_detail", []) if p.get("code") == code), None)

    # 该股分析摘要(取关键指标,避免 prompt 过长)
    rt = analyst_data.get("realtime", {})
    analysis_digest = {
        "price": rt.get("price"),
        "change_pct": rt.get("change_pct"),
        "pe_ttm": rt.get("pe_ttm"),
        "pb": rt.get("pb"),
        "mcap_yi": rt.get("mcap_yi"),
        "money_flow_main_net": analyst_data.get("money_flow", {}).get("main_net"),
        "on_top_list": analyst_data.get("on_top_list"),
    }

    # 账户摘要(精简,只留决策相关字段)
    account_digest = {
        "total_assets": account_summary.get("total_assets"),
        "cash": account_summary.get("cash"),
        "market_value": account_summary.get("market_value"),
        "total_pnl_pct": account_summary.get("total_pnl_pct"),
        "positions": [
            {"code": p.get("code"), "name": p.get("name"), "market_value": p.get("market_value"),
             "unrealized_pnl_pct": p.get("unrealized_pnl_pct")}
            for p in account_summary.get("positions_detail", [])
        ],
    }

    context = build_rag_context(code, analyst_data)
    system = ACTION_PROMPT.format(
        code=code,
        position=json.dumps(position, ensure_ascii=False, default=str) if position else "无持仓(空仓)",
        account=json.dumps(account_digest, ensure_ascii=False, default=str),
        analysis=json.dumps(analysis_digest, ensure_ascii=False, default=str),
    )
    try:
        markdown = ai.complete(system=system, user=f"请给出 {code} 的操作建议", context=context)
    except AIClientError as e:
        return f"⚠️ AI 服务暂不可用({e})。"

    _archive_advice(code, today, markdown)
    return markdown


def _archive_advice(code: str, day: str, markdown: str) -> None:
    path = state.DATA_DIR / "advice" / f"{code}-{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")


def _load_advice(code: str, day: str) -> str | None:
    path = state.DATA_DIR / "advice" / f"{code}-{day}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None
