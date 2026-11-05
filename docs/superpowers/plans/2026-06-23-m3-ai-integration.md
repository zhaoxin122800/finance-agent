# M3 AI 接入实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **前置:** M1 + M2 已完成。本计划依赖:
> - `app.services.analyst.assemble(code, ds) -> dict`(M2 产物,返回 realtime/kline/money_flow/minute_analysis)
> - `app.config.Settings.ai_enabled`、`llm_base_url/llm_api_key/llm_model`
> - `app.config.QUANT_KB_DIR`(M1 Task 2 产物)
> - `app.services.state.save_json/load_json`
> - `app.services.account_seed` / `data/sim_account.json`(持仓真实来源)

**Goal:** 接入 OpenAI 兼容 LLM(GLM/DeepSeek 等),实现「个股 AI 解读」和「每日复盘」。**个股 AI 解读采用 3 维度并行分析**(借鉴 TradingAgents-astock 的多 Analyst 架构,但不引入 LangGraph):把 M2 的 analyst 数据按 **量价技术面 / 资金面游资 / 基本面估值** 三个维度分别调 LLM,每个维度用带「必采清单」的专用 prompt,3 份子报告并行生成后合并归档。「每日复盘」保持单次 LLM 调用。AI 全程可降级:key 未配按钮置灰,LLM 失败显示原始数据 + 友好提示,不阻塞非 AI 功能。quant-kb 作为 RAG 上下文按关键词检索后拼入 system prompt。

**Architecture:** `app/ai/client.py` 封装 OpenAI SDK(同步 `complete`),`app/ai/prompts.py` 放 4 个 prompt 模板(3 维度 + 复盘 + RAG 前缀),`app/ai/kb.py` 做 quant-kb 关键词检索。`services/interpret.py` 用 `concurrent.futures.ThreadPoolExecutor` **并行**调 3 个维度(各独立 LLM 调用),任一维度失败不影响其它,合并后归档;`services/review.py` 单次调 LLM。AI 调用在测试中**全部 mock**(设计 §9)。

**3 维度设计(借鉴自 TradingAgents-astock 的 7 Analyst,精选 3 个自用够用):**

| 维度 | 数据来源 | 必采清单(借鉴游资分析师 prompt 技巧) |
|------|---------|--------------------------------------|
| 量价技术面 | K线(带MA) + 分时量能 + 涨跌幅 | MA 位置、量价异动(放量/缩量)、关键支撑压力位 |
| 资金面/游资 | 龙虎榜 + 主力资金流 + 换手率 | 主力净流入、龙虎榜席位、换手异常、连板特征(若适用) |
| 基本面/估值 | PE/PB/市值(腾讯) + 行业对比 | 估值分位、市值水平、行业相对位置 |

每个维度独立 prompt + 必采清单,缺失数据标注 `[数据缺失: xxx]` 而非瞎编。

**Tech Stack:** 复用 M1/M2 栈 + openai SDK + concurrent.futures(标准库)。无新依赖。

---

## 文件结构

| 文件 | 责任 | 动作 |
|------|------|------|
| `app/ai/client.py` | OpenAI 兼容客户端 + 降级 | 新建 |
| `app/ai/prompts.py` | ANALYST/REVIEW/RAG prompt 模板 | 新建 |
| `app/ai/kb.py` | quant-kb 关键词检索 | 新建 |
| `app/ai/__init__.py` | 导出 get_ai_client | 已存在,改 |
| `app/services/interpret.py` | 个股 AI 解读 + 归档 | 新建 |
| `app/services/review.py` | 每日复盘装配 + AI | 新建 |
| `app/routes/analyst.py` | 追加 POST /analyst/{code}/interpret | 改 |
| `app/routes/review.py` | 复盘路由 | 新建 |
| `app/templates/analyst.html` | 追加 AI 解读区 | 改 |
| `app/templates/review.html` | 复盘页 | 新建 |
| `tests/test_ai_client.py` | client 单测(mock openai) | 新建 |
| `tests/test_ai_kb.py` | kb 检索单测 | 新建 |
| `tests/test_interpret_service.py` | interpret 单测 | 新建 |
| `tests/test_review_service.py` | review 单测 | 新建 |
| `tests/test_ai_routes.py` | AI 路由冒烟 | 新建 |

**关键约定:**
- AI 解读归档:`data/analyses/{code}-{YYYY-MM-DD}.md`,同名不覆盖(返回已存档)。
- 复盘归档:`data/reviews/{YYYY-MM-DD}.md`。
- `AIClient.complete` 失败抛 `AIClientError`,service 层 catch 后返回 `{"error": "...", "markdown": None}`,route 层据此显示降级提示。
- key 未配时 `get_ai_client()` 返回 `None`,route 据此把按钮置灰。

---

## Task 1: AI 客户端(TDD)

**Files:**
- Create: `app/ai/client.py`
- Test: `tests/test_ai_client.py`

- [ ] **Step 1: 写失败测试**

`tests/test_ai_client.py`:

```python
"""AI client 测试 —— mock openai.OpenAI,绝不打真实 LLM(设计 §9)。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.ai.client import AIClient, AIClientError


def _make_client():
    return AIClient(base_url="http://fake/v1", api_key="sk-fake", model="glm-4-flash")


def test_complete_returns_content_on_success():
    client = _make_client()
    with patch.object(client, "_client") as mock_client:
        mock_msg = MagicMock()
        mock_msg.message.content = "这是 AI 解读"
        mock_choice = MagicMock()
        mock_choice.message = mock_msg.message
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp
        result = client.complete(system="你是分析师", user="分析 600789")
    assert result == "这是 AI 解读"


def test_complete_includes_context_when_provided():
    client = _make_client()
    with patch.object(client, "_client") as mock_client:
        mock_msg = MagicMock()
        mock_msg.message.content = "ok"
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message = mock_msg.message
        mock_client.chat.completions.create.return_value = mock_resp
        client.complete(system="s", user="u", context="背景知识: MACD 金叉")
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        # context 应拼进某条 message
        all_text = " ".join(m.get("content", "") for m in messages)
        assert "MACD 金叉" in all_text


def test_complete_raises_on_api_error():
    client = _make_client()
    with patch.object(client, "_client") as mock_client:
        mock_client.chat.completions.create.side_effect = RuntimeError("rate limit")
        with pytest.raises(AIClientError) as exc_info:
            client.complete(system="s", user="u")
    assert "rate limit" in str(exc_info.value)


def test_client_constructs_openai_with_base_url_and_key():
    with patch("app.ai.client.OpenAI") as mock_openai_cls:
        AIClient(base_url="http://x/v1", api_key="sk-y", model="m")
    mock_openai_cls.assert_called_once()
    kwargs = mock_openai_cls.call_args.kwargs
    assert kwargs["base_url"] == "http://x/v1"
    assert kwargs["api_key"] == "sk-y"
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd D:/finance-agent && python -m pytest tests/test_ai_client.py -v`
Expected: FAIL —— `ImportError`

- [ ] **Step 3: 实现 AIClient**

`app/ai/client.py`:

```python
"""OpenAI 兼容 LLM 客户端。

设计 §6.2:AIClient.complete(system, user, context)。失败抛 AIClientError。
兼容 GLM/DeepSeek/通义/OpenAI —— 它们都遵循 OpenAI API 协议。
"""
from __future__ import annotations

import logging

from openai import OpenAI

log = logging.getLogger("finance-agent.ai")


class AIClientError(Exception):
    """LLM 调用失败。"""


class AIClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self._model = model
        self._client = OpenAI(base_url=base_url, api_key=api_key)

    def complete(self, system: str, user: str, context: str = "") -> str:
        """调 chat completion。context 拼到 system 末尾作为 RAG 背景。"""
        full_system = system
        if context:
            full_system = f"{system}\n\n【参考知识】\n{context}"
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": full_system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as e:
            log.warning("LLM 调用失败: %s", e)
            raise AIClientError(str(e)) from e
        if not resp.choices:
            raise AIClientError("LLM 返回空 choices")
        content = resp.choices[0].message.content or ""
        return content.strip()
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd D:/finance-agent && python -m pytest tests/test_ai_client.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/ai/client.py tests/test_ai_client.py
git commit -m "feat(ai): OpenAI 兼容客户端 + context 注入 + 错误封装"
```

---

## Task 2: prompts 模板

**Files:**
- Create: `app/ai/prompts.py`

- [ ] **Step 1: 实现 prompts.py**

```python
"""LLM prompt 模板(设计 §6.2)。

3 维度分析模板(借鉴 TradingAgents-astock 的多 Analyst 架构):
- TECHNICAL_PROMPT: 量价技术面(对应 Market Analyst)
- CAPITAL_PROMPT: 资金面/游资(对应 Hot Money,A 股核心)
- FUNDAMENTAL_PROMPT: 基本面/估值(对应 Fundamentals)
每个模板带「必采清单」—— 借鉴游资分析师 prompt,强制覆盖关键数据点,
缺失时标注 [数据缺失: xxx] 而非瞎编。

- REVIEW_PROMPT: 每日复盘(单次调用)
- RAG_PREFIX: 拼在 system 开头的角色定义
"""
from __future__ import annotations

RAG_PREFIX = """你是一位经验丰富的 A 股分析师助手。请基于提供的数据给出客观、谨慎的分析。
注意:
- 数据来自免费行情源,可能有延迟,分析仅供参考,不构成投资建议。
- 如数据缺失或异常,应明确指出,不要臆测,标注 [数据缺失: xxx]。
- 用 markdown 输出,结构清晰(小标题 + 要点列表)。
- 你只负责一个分析维度,聚焦深入,不要泛泛而谈。
"""

# ============================================================
# 维度1:量价技术面(对应 TradingAgents 的 Market Analyst)
# ============================================================
TECHNICAL_PROMPT = RAG_PREFIX + """
你负责该股的**量价技术面分析**。

📋 必采清单 — 以下数据点必须出现在报告中,无法获取时标注 [数据缺失: xxx]:
1. 当前价相对 MA5/MA10/MA20 的位置(之上/之下/缠绕)
2. 近期成交量趋势(放量/缩量/平稳),是否有单日异常放量
3. 关键支撑位与压力位(基于近期高低点)
4. 当日涨跌幅及振幅
5. 分时量能特征(若有分时数据):放量上涨/缩量回调/量价背离

分析框架:
- 均线多头/空头排列判断趋势方向
- 量价配合关系(放量突破=有效,缩量上涨=虚涨)
- 是否处于关键技术位置(突破/破位/回踩)

K线数据(JSON,含 ma5/ma10/ma20):
{kline}

实时行情(JSON):
{realtime}

分时量能(JSON,可能为空):
{minute}
"""

# ============================================================
# 维度2:资金面/游资(A 股核心,对应 Hot Money Tracker)
# ============================================================
CAPITAL_PROMPT = RAG_PREFIX + """
你负责该股的**资金面与游资动向分析**(A 股特有维度)。

📋 必采清单 — 以下数据点必须出现在报告中,无法获取时标注 [数据缺失: xxx]:
1. 主力资金净流入金额(超大单+大单),方向(流入/流出)
2. 是否上榜龙虎榜,买卖席位特征(机构/知名游资营业部)
3. 换手率水平(>10% 为异常活跃)
4. 若为连板股,判断板数与放量/缩量特征(首板放量=分歧,缩量=一致;三板以上=妖股谨慎)
5. 资金面总体判断:主力吸筹 / 主力出货 / 游资接力 / 散户主导 / 无明显信号

分析框架(A 股游资逻辑):
- 龙虎榜知名游资席位买入=强势信号;机构净买入=中长期资金
- 主力资金连续净流入+换手率适中=吸筹;放量滞涨=出货
- 板块资金轮动:资金从一板块撤出往往流入另一板块

资金流向数据(JSON):
{money_flow}

龙虎榜数据(JSON,可能为空):
{top_list}

实时行情(JSON,含换手率 turnover_pct):
{realtime}
"""

# ============================================================
# 维度3:基本面/估值(对应 Fundamentals Analyst)
# ============================================================
FUNDAMENTAL_PROMPT = RAG_PREFIX + """
你负责该股的**基本面与估值分析**。

📋 必采清单 — 以下数据点必须出现在报告中,无法获取时标注 [数据缺失: xxx]:
1. PE_TTM(滚动市盈率)绝对值,及行业常见区间内的相对位置
2. PB(市净率)水平
3. 总市值与流通市值(大盘/中盘/小盘)
4. 估值结论:低估 / 合理 / 高估(需说明判断依据)
5. 基本面风险提示(如 PE 为负/极高、市值过小流动性风险)

分析框架:
- PE 分位:与行业均值/历史区间对比
- 市值规模:大盘股(>500亿)/中盘/小盘,小盘注意流动性
- PB<1 可能为破净,需结合行业判断

实时行情(JSON,含 pe_ttm/pb/mcap_yi/float_mcap_yi):
{realtime}
"""

# ============================================================
# 每日复盘(单次调用)
# ============================================================
REVIEW_PROMPT = RAG_PREFIX + """
请生成今日复盘报告,输出包含:
1. **账户表现**:总资产变动、盈亏来源
2. **持仓诊断**:各持仓的当日表现与异动
3. **市场环境**:大盘与板块的整体氛围(基于板块数据)
4. **操作回顾**:当日买卖是否合理
5. **明日关注**:需要盯的价位/事件

账户数据(JSON):
{account}

板块数据(JSON):
{sectors}
"""
```

- [ ] **Step 2: 冒烟验证模板可格式化**

Run: `cd D:/finance-agent && python -c "from app.ai.prompts import TECHNICAL_PROMPT, CAPITAL_PROMPT, FUNDAMENTAL_PROMPT, REVIEW_PROMPT; print(TECHNICAL_PROMPT.format(kline='{}', realtime='{}', minute='{}')[:40]); print(CAPITAL_PROMPT.format(money_flow='{}', top_list='{}', realtime='{}')[:40]); print(FUNDAMENTAL_PROMPT.format(realtime='{}')[:40]); print(REVIEW_PROMPT.format(account='{}', sectors='{}')[:40])"`
Expected: 打印四段开头,无 KeyError

- [ ] **Step 3: Commit**

```bash
git add app/ai/prompts.py
git commit -m "feat(ai): analyst/review/rag prompt 模板"
```

---

## Task 3: quant-kb 关键词检索(TDD)

**Files:**
- Create: `app/ai/kb.py`
- Test: `tests/test_ai_kb.py`

- [ ] **Step 1: 写失败测试**

`tests/test_ai_kb.py`:

```python
"""quant-kb 检索测试 —— 用临时 kb 目录。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.ai import kb


@pytest.fixture
def fake_kb(tmp_path, monkeypatch):
    """造 2 个假 md,含关键词。"""
    (tmp_path / "terms.md").write_text("# 术语\n\n## T+1\n当天买入次日才能卖出。\n## MACD\n异动移动平均指标。\n", encoding="utf-8")
    (tmp_path / "strategies.md").write_text("# 策略\n\n## 均线交叉\nMA5 上穿 MA20 买入。\n", encoding="utf-8")
    monkeypatch.setattr(kb, "QUANT_KB_DIR", tmp_path)
    return tmp_path


def test_search_returns_matching_snippets(fake_kb):
    result = kb.search(["T+1"])
    assert any("T+1" in s for s in result)


def test_search_no_match_returns_empty(fake_kb):
    result = kb.search(["完全不存在的词"])
    assert result == []


def test_search_aggregates_across_files(fake_kb):
    """关键词分散在多个文件时都要召回。"""
    result = kb.search(["T+1", "均线"])
    joined = "\n".join(result)
    assert "T+1" in joined
    assert "均线" in joined


def test_search_deduplicates(fake_kb):
    """同一关键词多次匹配不重复返回同一段。"""
    result = kb.search(["T+1", "T+1"])
    t1_count = sum(1 for s in result if "T+1" in s)
    assert t1_count == 1


def test_search_limits_snippet_length(fake_kb):
    """单条 snippet 不过长(避免撑爆 prompt)。"""
    (fake_kb / "big.md").write_text("# 大文件\n\n" + ("很长的内容 " * 500), encoding="utf-8")
    result = kb.search(["大文件"])
    assert all(len(s) <= 600 for s in result)


def test_format_for_prompt_joins_snippets(fake_kb):
    snippets = kb.search(["T+1"])
    formatted = kb.format_for_prompt(snippets)
    assert "T+1" in formatted
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd D:/finance-agent && python -m pytest tests/test_ai_kb.py -v`
Expected: FAIL —— `ImportError`

- [ ] **Step 3: 实现 kb.py**

`app/ai/kb.py`:

```python
"""quant-kb 简易关键词检索。

设计 §4.9 尾注:quant-kb 不单独成页,作为 RAG 上下文。
YAGNI:不用向量库,按段落分块 + 关键词子串匹配,足够自用场景。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from app.config import QUANT_KB_DIR

log = logging.getLogger("finance-agent.kb")

MAX_SNIPPET_CHARS = 600
MAX_SNIPPETS = 8


def _split_paragraphs(text: str) -> list[str]:
    """按空行/标题分块,保留小段落。"""
    blocks = re.split(r"\n(?=#{1,4}\s)|\n{2,}", text)
    return [b.strip() for b in blocks if b.strip()]


def search(keywords: list[str]) -> list[str]:
    """在 quant-kb 全部 md 里按关键词召回段落。返回去重后的 snippet 列表。"""
    if not keywords:
        return []
    snippets: list[str] = []
    seen: set[str] = set()
    if not QUANT_KB_DIR.exists():
        return []
    for md_path in sorted(QUANT_KB_DIR.glob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("读取 %s 失败: %s", md_path, e)
            continue
        for para in _split_paragraphs(text):
            if any(kw in para for kw in keywords):
                snippet = para[:MAX_SNIPPET_CHARS]
                if snippet in seen:
                    continue
                seen.add(snippet)
                snippets.append(snippet)
                if len(snippets) >= MAX_SNIPPETS:
                    return snippets
    return snippets


def format_for_prompt(snippets: list[str]) -> str:
    """把召回的 snippet 拼成可塞进 prompt 的字符串。"""
    if not snippets:
        return ""
    return "\n---\n".join(snippets)
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd D:/finance-agent && python -m pytest tests/test_ai_kb.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app/ai/kb.py tests/test_ai_kb.py
git commit -m "feat(ai): quant-kb 关键词检索 + 长度/数量限制"
```

---

## Task 4: ai 包工厂 + 降级

**Files:**
- Modify: `app/ai/__init__.py`

- [ ] **Step 1: 实现工厂**

`app/ai/__init__.py`:

```python
"""ai 包 —— 根据 config 决定返回 AIClient 还是 None(未配 key)。"""
from __future__ import annotations

from app.ai.client import AIClient, AIClientError
from app.config import get_settings

__all__ = ["AIClient", "AIClientError", "get_ai_client"]


def get_ai_client() -> AIClient | None:
    """未配 key 时返回 None(设计 §8:AI 按钮置灰)。"""
    s = get_settings()
    if not s.ai_enabled:
        return None
    return AIClient(base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.llm_model)
```

- [ ] **Step 2: 验证未配 key 返回 None**

Run: `cd D:/finance-agent && python -c "import os; os.environ.pop('LLM_API_KEY', None); from app.ai import get_ai_client; print(get_ai_client())"`
Expected: 打印 `None`

- [ ] **Step 3: Commit**

```bash
git add app/ai/__init__.py
git commit -m "feat(ai): get_ai_client 工厂 + 未配 key 降级 None"
```

---

## Task 5: 个股 AI 解读 service(TDD)

**Files:**
- Create: `app/services/interpret.py`
- Test: `tests/test_interpret_service.py`

- [ ] **Step 1: 写失败测试**

`tests/test_interpret_service.py`:

```python
"""interpret service 测试 —— mock AIClient + DataSource。"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from app.services import interpret


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(interpret, "DATA_DIR", tmp_path)
    yield tmp_path


@pytest.fixture
def fake_analyst_data():
    return {
        "code": "600789",
        "realtime": {"name": "鲁信创投", "price": 10.5, "change_pct": 1.2, "pe_ttm": 25.0, "pb": 3.0, "mcap_yi": 100.0, "turnover_pct": 5.0},
        "kline": [{"date": "2026-06-20", "close": 10.5, "ma5": 10.3, "ma10": 10.1, "ma20": 9.8, "volume": 1000}],
        "money_flow": {"main_net": 5000000, "super_large": 3000000, "large": 2000000},
        "minute_analysis": {"volume_profile": "放量"},
        "top_list_reason": "",
        "on_top_list": False,
    }


def test_interpret_calls_3_dimensions_in_parallel(fake_analyst_data):
    """3 维度并行:ai.complete 应被调用 3 次(技术/资金/基本面)。"""
    ai = MagicMock()
    ai.complete.side_effect = ["技术面报告", "资金面报告", "基本面报告"]
    md = interpret.interpret_stock("600789", fake_analyst_data, ai)
    assert ai.complete.call_count == 3
    # 合并后应含三段
    assert "技术面报告" in md
    assert "资金面报告" in md
    assert "基本面报告" in md


def test_interpret_archives_merged_report(fake_analyst_data):
    """合并报告归档到 data/analyses/。"""
    ai = MagicMock()
    ai.complete.side_effect = ["技术", "资金", "基本面"]
    md = interpret.interpret_stock("600789", fake_analyst_data, ai)
    today = date.today().isoformat()
    archived = interpret.load_archived("600789", today)
    assert archived == md


def test_interpret_returns_archived_on_second_call(fake_analyst_data):
    """同一天重复解读返回已归档,不重复调 LLM。"""
    ai = MagicMock()
    ai.complete.side_effect = ["技术", "资金", "基本面"]
    interpret.interpret_stock("600789", fake_analyst_data, ai)
    ai.complete.reset_mock()
    again = interpret.interpret_stock("600789", fake_analyst_data, ai)
    assert again is not None
    ai.complete.assert_not_called()


def test_interpret_one_dimension_failure_doesnt_break_others(fake_analyst_data):
    """单个维度失败不影响其它,失败的维度显示错误,成功的正常。"""
    from app.ai.client import AIClientError
    ai = MagicMock()
    # 技术面成功、资金面失败、基本面成功
    ai.complete.side_effect = ["技术面报告", AIClientError("资金面超时"), "基本面报告"]
    md = interpret.interpret_stock("600789", fake_analyst_data, ai)
    assert "技术面报告" in md
    assert "基本面报告" in md
    assert "资金面" in md and ("超时" in md or "失败" in md or "不可用" in md)


def test_interpret_all_dimensions_failure_returns_friendly(fake_analyst_data):
    """3 个维度全失败时返回统一降级提示。"""
    from app.ai.client import AIClientError
    ai = MagicMock()
    ai.complete.side_effect = AIClientError("服务不可用")
    md = interpret.interpret_stock("600789", fake_analyst_data, ai)
    assert "不可用" in md or "失败" in md


def test_interpret_without_ai_client_returns_disabled(fake_analyst_data):
    """ai=None 时返回降级提示,不调 LLM。"""
    result = interpret.interpret_stock("600789", fake_analyst_data, ai=None)
    assert "未启用" in result or "不可用" in result


def test_interpret_includes_rag_context(fake_analyst_data):
    """每个维度的 system prompt 都注入 quant-kb RAG 上下文。"""
    ai = MagicMock()
    ai.complete.side_effect = ["技术", "资金", "基本面"]
    with pytest.MonkeyPatch().context() as m:
        m.setattr(interpret, "build_rag_context", lambda code, data: "T+1 知识")
        interpret.interpret_stock("600789", fake_analyst_data, ai)
    # 每次调用的 context 参数都应含 RAG
    for call in ai.complete.call_args_list:
        assert "T+1 知识" in call.kwargs.get("context", "")
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd D:/finance-agent && python -m pytest tests/test_interpret_service.py -v`
Expected: FAIL —— `ImportError`

- [ ] **Step 3: 实现 interpret service**

`app/services/interpret.py`:

```python
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
from app.ai.prompts import CAPITAL_PROMPT, FUNDAMENTAL_PROMPT, TECHNICAL_PROMPT
from app.config import DATA_DIR

log = logging.getLogger("finance-agent.interpret")

# 维度定义:(key, prompt 模板, 该维度需要的数据字段提取函数)
DIMENSIONS = [
    ("technical", TECHNICAL_PROMPT, _extract_technical_data),
    ("capital", CAPITAL_PROMPT, _extract_capital_data),
    ("fundamental", FUNDAMENTAL_PROMPT, _extract_fundamental_data),
]


def _extract_technical_data(d: dict) -> dict:
    return {"kline": d.get("kline", []), "realtime": d.get("realtime", {}), "minute": d.get("minute_analysis", {})}


def _extract_capital_data(d: dict) -> dict:
    return {"money_flow": d.get("money_flow", {}), "top_list": d.get("top_list_reason", ""), "realtime": d.get("realtime", {})}


def _extract_fundamental_data(d: dict) -> dict:
    return {"realtime": d.get("realtime", {})}


def build_rag_context(code: str, data: dict) -> str:
    """从 quant-kb 检索相关知识,注入各维度 system prompt。"""
    name = data.get("realtime", {}).get("name", "")
    keywords = [code, name, "量能", "资金流", "均线", "估值"]
    return format_for_prompt(search(keywords))


def _run_dimension(name: str, prompt_template: str, extractor, code: str, data: dict, ai: AIClient, context: str) -> tuple[str, str]:
    """单维度分析。返回 (维度名, markdown 或错误提示)。"""
    dim_data = extractor(data)
    system = prompt_template.format(**{k: json.dumps(v, ensure_ascii=False, default=str) for k, v in dim_data.items()})
    try:
        content = ai.complete(system=system, user=f"请分析股票 {code} 的该维度", context=context)
        return (name, content)
    except AIClientError as e:
        log.warning("维度 %s 分析失败(%s): %s", name, code, e)
        return (name, f"⚠️ {name} 维度分析暂不可用({e})。")


def interpret_stock(code: str, analyst_data: dict, ai: AIClient | None) -> str:
    """生成 3 维度 AI 解读并归档。ai=None 时返回降级提示。"""
    today = date.today().isoformat()
    archived = load_archived(code, today)
    if archived:
        return archived

    if ai is None:
        return "⚠️ AI 解读未启用。请在 .env 配置 LLM_API_KEY 后重试。原始数据已展示在上方。"

    context = build_rag_context(code, analyst_data)
    results: dict[str, str] = {}
    # 并行 3 维度
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_run_dimension, name, tpl, ext, code, analyst_data, ai, context): name
            for name, tpl, ext in DIMENSIONS
        }
        for fut in as_completed(futures):
            dim_name, content = fut.result()
            results[dim_name] = content

    # 按固定顺序合并(技术→资金→基本面)
    sections = []
    titles = {"technical": "📈 量价技术面", "capital": "💰 资金面 / 游资", "fundamental": "📊 基本面 / 估值"}
    for name, _, _ in DIMENSIONS:
        title = titles[name]
        sections.append(f"## {title}\n\n{results.get(name, '⚠️ 该维度未生成。')}")

    markdown = f"# {code} AI 多维度解读\n\n" + "\n\n---\n\n".join(sections)
    markdown += "\n\n---\n*免责:数据来自免费行情源,分析仅供参考,不构成投资建议。*"
    archive(code, today, markdown)
    return markdown


def archive(code: str, day: str, markdown: str) -> Path:
    """归档到 data/analyses/{code}-{day}.md。"""
    path = DATA_DIR / "analyses" / f"{code}-{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path


def load_archived(code: str, day: str) -> str | None:
    """读已归档解读,无则 None。"""
    path = DATA_DIR / "analyses" / f"{code}-{day}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd D:/finance-agent && python -m pytest tests/test_interpret_service.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/interpret.py tests/test_interpret_service.py
git commit -m "feat(services): 个股 AI 3 维度并行解读(技术/资金/基本面,借鉴 TradingAgents)"
```

---

## Task 6: 每日复盘 service(TDD)

**Files:**
- Create: `app/services/review.py`
- Test: `tests/test_review_service.py`

- [ ] **Step 1: 写失败测试**

`tests/test_review_service.py`:

```python
"""review service 测试。"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.services import review


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "DATA_DIR", tmp_path)
    yield tmp_path


def test_summarize_account_computes_pnl():
    """从 sim_account + 实时价计算总资产/盈亏。"""
    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 11.0, "name": "鲁信创投"}}
    account = {
        "initial_capital": 1000.0, "cash": 800.0,
        "positions": {"600789": {"qty": 100, "cost_price": 10.0, "name": "鲁信创投"}},
        "history": [],
    }
    summary = review.summarize_account(account, ds)
    assert summary["cash"] == 800.0
    assert summary["market_value"] == 1100.0  # 11.0 * 100
    assert summary["total_assets"] == 1900.0
    assert summary["total_pnl"] == 900.0  # 1900 - 1000


def test_summarize_account_handles_empty_positions():
    ds = MagicMock()
    ds.get_realtime.return_value = {}
    account = {"initial_capital": 1000.0, "cash": 1000.0, "positions": {}, "history": []}
    summary = review.summarize_account(account, ds)
    assert summary["market_value"] == 0.0
    assert summary["total_assets"] == 1000.0


def test_summarize_account_today_history():
    """只统计今天的交易。"""
    ds = MagicMock()
    ds.get_realtime.return_value = {}
    today = date.today().isoformat()
    account = {
        "initial_capital": 1000.0, "cash": 1000.0, "positions": {},
        "history": [
            {"type": "buy", "code": "600789", "time": today + "T10:00:00", "amount": 1000, "fee": 5},
            {"type": "sell", "code": "600789", "time": "2020-01-01T10:00:00", "amount": 500, "fee": 5},
        ],
    }
    summary = review.summarize_account(account, ds)
    assert summary["today_trades_count"] == 1


def test_generate_review_calls_llm_and_archives():
    ai = MagicMock()
    ai.complete.return_value = "## 今日复盘\n账户表现良好"
    ds = MagicMock()
    ds.get_realtime.return_value = {}
    ds.get_sectors.return_value = [{"name": "银行", "change_pct": 1.5}]
    account = {"initial_capital": 1000.0, "cash": 1000.0, "positions": {}, "history": []}
    md = review.generate_review(account, ds, ai)
    assert "今日复盘" in md
    today = date.today().isoformat()
    assert review.load_archived(today) == md


def test_generate_review_returns_archived_on_repeat():
    ai = MagicMock()
    ai.complete.return_value = "首次"
    ds = MagicMock()
    ds.get_realtime.return_value = {}
    ds.get_sectors.return_value = []
    account = {"initial_capital": 1000.0, "cash": 1000.0, "positions": {}, "history": []}
    review.generate_review(account, ds, ai)
    ai.complete.reset_mock()
    again = review.generate_review(account, ds, ai)
    assert again == "首次"
    ai.complete.assert_not_called()


def test_generate_review_without_ai_returns_disabled():
    ds = MagicMock()
    account = {"initial_capital": 1000.0, "cash": 1000.0, "positions": {}, "history": []}
    result = review.generate_review(account, ds, ai=None)
    assert "未启用" in result
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd D:/finance-agent && python -m pytest tests/test_review_service.py -v`
Expected: FAIL —— `ImportError`

- [ ] **Step 3: 实现 review service**

`app/services/review.py`:

```python
"""每日复盘 service。

设计 §4.4:账户变动 + 持仓异动 + 板块数据 → LLM → 归档。
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from app.ai.client import AIClient, AIClientError
from app.ai.prompts import REVIEW_PROMPT
from app.config import DATA_DIR

log = logging.getLogger("finance-agent.review")


def summarize_account(account: dict, datasource: Any) -> dict:
    """计算总资产/盈亏/今日交易数。"""
    positions = account.get("positions", {})
    market_value = 0.0
    if positions:
        quotes = datasource.get_realtime(list(positions.keys()))
        for code, pos in positions.items():
            price = quotes.get(code, {}).get("price", 0) or 0
            market_value += price * pos.get("qty", 0)

    cash = account.get("cash", 0)
    initial = account.get("initial_capital", 0)
    total_assets = cash + market_value

    today = date.today().isoformat()
    today_trades = [t for t in account.get("history", []) if str(t.get("time", "")).startswith(today)]

    return {
        "cash": cash,
        "market_value": round(market_value, 2),
        "total_assets": round(total_assets, 2),
        "total_pnl": round(total_assets - initial, 2),
        "total_pnl_pct": round((total_assets / initial - 1) * 100, 2) if initial else 0,
        "today_trades_count": len(today_trades),
        "today_trades": today_trades,
    }


def generate_review(account: dict, datasource: Any, ai: AIClient | None) -> str:
    today = date.today().isoformat()
    archived = load_archived(today)
    if archived:
        return archived

    summary = summarize_account(account, datasource)
    sectors = datasource.get_sectors()

    if ai is None:
        return "⚠️ AI 复盘未启用。请在 .env 配置 LLM_API_KEY。账户数据已展示在上方。"

    system = REVIEW_PROMPT.format(
        account=json.dumps({**summary, "positions": account.get("positions", {})}, ensure_ascii=False, default=str),
        sectors=json.dumps(sectors, ensure_ascii=False, default=str),
    )
    try:
        markdown = ai.complete(system=system, user=f"请生成 {today} 的复盘报告")
    except AIClientError as e:
        return f"⚠️ AI 服务暂不可用({e})。账户数据已展示。"

    archive(today, markdown)
    return markdown


def archive(day: str, markdown: str) -> Path:
    path = DATA_DIR / "reviews" / f"{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path


def load_archived(day: str) -> str | None:
    path = DATA_DIR / "reviews" / f"{day}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd D:/finance-agent && python -m pytest tests/test_review_service.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/review.py tests/test_review_service.py
git commit -m "feat(services): 每日复盘 账户汇总 + AI 复盘报告 + 归档"
```

---

## Task 7: AI 解读路由 + 模板

**Files:**
- Modify: `app/routes/analyst.py`(加 POST endpoint)
- Modify: `app/templates/analyst.html`(加 AI 解读区)
- Test: `tests/test_ai_routes.py`

- [ ] **Step 1: 写路由测试**

`tests/test_ai_routes.py`:

```python
"""AI 路由冒烟测试。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_analyst_interpret_post_returns_markdown(client):
    fake_data = {"code": "600789", "realtime": {}, "kline": [], "money_flow": {}, "minute_analysis": {}}
    with patch("app.routes.analyst.assemble", return_value=fake_data), \
         patch("app.routes.analyst.interpret_stock", return_value="## AI 解读内容") as mock_interp:
        resp = client.post("/analyst/600789/interpret")
    assert resp.status_code == 200
    assert "AI 解读内容" in resp.text
    mock_interp.assert_called_once()


def test_review_page_returns_200(client):
    with patch("app.routes.review.review.summarize_account", return_value={"total_assets": 1000}), \
         patch("app.routes.review.review.load_archived", return_value=None), \
         patch("app.routes.review.get_ai_client", return_value=None):
        resp = client.get("/review")
    assert resp.status_code == 200
    assert "复盘" in resp.text


def test_review_generate_post(client):
    with patch("app.routes.review.review.summarize_account", return_value={"total_assets": 1000}), \
         patch("app.routes.review.review.generate_review", return_value="## 复盘") as mock_gen:
        resp = client.post("/review/generate")
    assert resp.status_code == 200
    assert "复盘" in resp.text
    mock_gen.assert_called_once()
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd D:/finance-agent && python -m pytest tests/test_ai_routes.py -v`
Expected: FAIL —— endpoint 不存在

- [ ] **Step 3: 修改 analyst 路由加 interpret endpoint**

在 `app/routes/analyst.py` 末尾追加:

```python
from fastapi.responses import HTMLResponse

from app.ai import get_ai_client
from app.services import interpret


@router.post("/analyst/{code}/interpret", response_class=HTMLResponse)
def interpret_page(request: Request, code: str):
    data = analyst.assemble(code, get_datasource())
    markdown = interpret.interpret_stock(code, data, get_ai_client())
    return templates.TemplateResponse(
        "analyst.html",
        {"request": request, "d": data, "interpretation": markdown},
    )
```

- [ ] **Step 4: 修改 analyst.html 加 AI 解读区**

在 `app/templates/analyst.html` 的「分时量能分析」section 之后、`{% endblock %}`(content)之前插入:

```html
<h2>AI 多维度解读</h2>
<div class="card">
    {% if interpretation %}
    <div class="ai-result">{{ interpretation }}</div>
    {% else %}
    <form method="post" action="/analyst/{{ d.code }}/interpret">
        <p class="dim">并行分析 3 个维度(量价技术面 / 资金面游资 / 基本面估值),约需 10-20 秒。</p>
        <button type="submit">🤖 生成 AI 多维度解读</button>
    </form>
    {% endif %}
</div>
```

- [ ] **Step 5: 实现 review 路由**

`app/routes/review.py`:

```python
"""每日复盘路由。

GET  /review           查看今日复盘(账户汇总 + 已归档复盘)
POST /review/generate  生成/刷新今日 AI 复盘
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.ai import get_ai_client
from app.config import PROJECT_ROOT
from app.datasources import get_datasource
from app.services import review
from app.services.state import load_json

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))

ACCOUNT_FILE = "sim_account.json"


def _context(request: Request) -> dict:
    account = load_json(ACCOUNT_FILE, default={"initial_capital": 1000, "cash": 1000, "positions": {}, "history": []})
    summary = review.summarize_account(account, get_datasource())
    from datetime import date
    archived = review.load_archived(date.today().isoformat())
    return {"request": request, "summary": summary, "archived": archived, "ai_enabled": get_ai_client() is not None}


@router.get("/review", response_class=HTMLResponse)
def page(request: Request):
    return templates.TemplateResponse("review.html", _context(request))


@router.post("/review/generate", response_class=HTMLResponse)
def generate(request: Request):
    account = load_json(ACCOUNT_FILE, default={"initial_capital": 1000, "cash": 1000, "positions": {}, "history": []})
    markdown = review.generate_review(account, get_datasource(), get_ai_client())
    ctx = _context(request)
    ctx["archived"] = markdown
    return templates.TemplateResponse("review.html", ctx)
```

- [ ] **Step 6: 实现 review.html 模板**

`app/templates/review.html`:

```html
{% extends "base.html" %}
{% block title %}每日复盘 - Finance Agent{% endblock %}
{% block content %}
<h1>每日复盘</h1>

<div class="cards-row">
    <div class="card"><div class="label">总资产</div><div class="value">{{ '%.2f' % summary.total_assets }}</div></div>
    <div class="card"><div class="label">现金</div><div class="value">{{ '%.2f' % summary.cash }}</div></div>
    <div class="card"><div class="label">持仓市值</div><div class="value">{{ '%.2f' % summary.market_value }}</div></div>
    <div class="card"><div class="label">总盈亏</div><div class="value {{ 'up' if summary.total_pnl > 0 else 'down' }}">{{ '%+.2f' % summary.total_pnl }} ({{ '%.2f' % summary.total_pnl_pct }}%)</div></div>
    <div class="card"><div class="label">今日交易</div><div class="value">{{ summary.today_trades_count }}</div></div>
</div>

<h2>AI 复盘报告</h2>
<div class="card">
    {% if archived %}
    <div class="ai-result">{{ archived }}</div>
    {% elif ai_enabled %}
    <form method="post" action="/review/generate">
        <button type="submit">🤖 生成今日复盘</button>
    </form>
    {% else %}
    <p class="muted">⚠️ AI 未启用(缺少 LLM_API_KEY),无法生成 AI 复盘。账户数据已展示在上方。</p>
    {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 7: 注册 review 路由 + 从 pages.py 占位移除**

在 `app/main.py` 的 `create_app()` 追加:
```python
    from app.routes.review import router as review_router
    app.include_router(review_router)
```
在 `app/routes/pages.py` 的 `PLACEHOLDER_PAGES` 删除 `"review"` key。

- [ ] **Step 8: 运行测试,确认通过**

Run: `cd D:/finance-agent && python -m pytest tests/test_ai_routes.py tests/test_market_routes.py tests/test_routes.py -v`
Expected: 全部 passed

- [ ] **Step 9: Commit**

```bash
git add app/routes/analyst.py app/routes/review.py app/templates/analyst.html app/templates/review.html app/routes/pages.py app/main.py tests/test_ai_routes.py
git commit -m "feat(routes): AI 解读 + 每日复盘 endpoint 与页面"
```

---

## Task 8: README 进度更新

- [ ] **Step 1:** 在 `README.md` 把 `- [ ] **M3 AI 接入**` 改为 `- [x] **M3 AI 接入**`

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README 标注 M3 完成"
```

---

## M3 验收清单

```bash
cd D:/finance-agent
uv run python -m pytest -v
uv run python -m app.main
```

**通过标准:**
- [ ] 全部 pytest 通过(M1+M2+M3,预计 ~52 条;其中 interpret 7 条含 3 维度并行)
- [ ] 未配 `LLM_API_KEY` 时:个股分析页 AI 按钮位置显示「请配置」提示,复盘页显示「AI 未启用」
- [ ] 配置真实 key 后:个股分析页点「生成 AI 多维度解读」,约 10-20 秒后出**含 3 个小节**(量价技术面/资金面游资/基本面估值)的报告
- [ ] AI 报告含「必采清单」要求的数据点,缺失项标注 [数据缺失: xxx]
- [ ] 刷新页面仍显示(已归档 `data/analyses/{code}-{date}.md`),重复点不重复调 LLM
- [ ] 单个维度失败不影响其它(失败的维度显示错误,成功的正常)—— 可临时改 prompt 触发测试
- [ ] 复盘页点「生成今日复盘」出 markdown,`data/reviews/<date>.md` 生成
- [ ] LLM 调用全失败时,页面显示「AI 服务暂不可用」+ 原始数据,不 500
- [ ] `data/analyses/` 和 `data/reviews/` 目录自动创建
- [ ] quant-kb 关键词检索的结果注入到每个维度的 system prompt(可临时 log 验证)
