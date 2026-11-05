# M4 完整功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **前置:** M1 + M2 + M3 已完成。本计划依赖:
> - `vendors.sim_trade`(M1 打过路径补丁,`ACCOUNT_FILE` 已指向 `data/sim_account.json`)
> - `vendors.monitor.search_policy_news/extract_policy_points/relate_stocks/daily_brief`
> - `vendors.extract.extract_report/extract_from_pdf/extract_from_url`
> - `app.datasources.get_datasource()`(M1)
> - `app.services.state.load_json/save_json`(M1)
> - `app.services.watchlist.load_watchlist`(M2,风控读取自选股阈值)
> - `app.config.METHODOLOGY_FILE`(M1,回测方法论)
> - `app.templates/base.html`、路由注册模式(M1-M3)

**Goal:** 补齐剩余 5 个功能页 —— 虚拟账户(买卖/持仓/历史)、政策监控(新闻+日报+关联)、研报提炼(PDF/URL/文本)、策略回测(3 内置策略+收益曲线+夏普/回撤)、风险预警(自选股规则触发看板+归档)。完成后设计文档的 8 个面板全部可用。

**Architecture:** 各 service 包装对应 vendors 脚本。**sim_trade 的特殊性**:它的 `buy/sell/show_account/show_history` 直接打印到 stdout 且 `get_price` 网络取价,service 层用 `contextlib.redirect_stdout` 捕获输出 + 直接读 `data/sim_account.json` 装配结构化数据(不依赖它的 print)。回测引擎新写,遵循 `backtest_methodology.md` 的「加摩擦、找最容易崩的」原则。风控读 `watchlist.json` 的阈值 + 实时行情计算触发。

**Tech Stack:** 复用全部已有栈。研报 PDF 读取依赖 `pdfplumber`/`PyPDF2`(vendors.extract 内 try-import,可选)→ 列入 pyproject optional 依赖。

---

## 文件结构

| 文件 | 责任 | 动作 |
|------|------|------|
| `app/services/account.py` | 包装 sim_trade + 装配账户视图 | 新建 |
| `app/services/policy.py` | 包装 monitor + 关联高亮 | 新建 |
| `app/services/report.py` | 包装 extract + 提炼历史 | 新建 |
| `app/services/backtest.py` | 回测引擎(新写)+ 3 策略 | 新建 |
| `app/services/risk.py` | 风险规则引擎 + 触发归档 | 新建 |
| `app/routes/account.py policy.py report.py backtest.py risk.py` | 5 路由 | 新建 |
| `app/templates/account.html policy.html report.html backtest.html risk.html` | 5 页面 | 新建 |
| `pyproject.toml` | 加 pdfplumber optional | 改 |
| `tests/test_account_service.py test_policy_service.py test_report_service.py test_backtest_service.py test_risk_service.py` | service 单测 | 新建 |
| `tests/test_m4_routes.py` | 路由冒烟 | 新建 |

---

## Task 1: 账户 service(TDD)

**Files:**
- Create: `app/services/account.py`
- Test: `tests/test_account_service.py`

- [ ] **Step 1: 写失败测试**

`tests/test_account_service.py`:

```python
"""account service 测试 —— mock vendors.sim_trade + DataSource。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import account


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(account, "DATA_DIR", tmp_path)
    yield tmp_path


@pytest.fixture
def seeded_account_file(isolated_data_dir):
    """种子一个有效 sim_account.json。"""
    import json
    acct = {"initial_capital": 1000.0, "cash": 1000.0, "positions": {}, "history": [], "created_at": "2026-06-22", "updated_at": "2026-06-22"}
    (isolated_data_dir / "sim_account.json").write_text(json.dumps(acct), encoding="utf-8")


def test_load_account_returns_dict(seeded_account_file):
    acct = account.load_account()
    assert acct["cash"] == 1000.0
    assert acct["positions"] == {}


def test_load_account_returns_fresh_when_missing(isolated_data_dir):
    """文件不存在时返回初始账户。"""
    acct = account.load_account()
    assert acct["initial_capital"] == 1000.0


def test_account_view_computes_market_value(seeded_account_file):
    """装配持仓 + 实时价 → 总资产/盈亏。"""
    import json
    acct = account.load_account()
    acct["positions"] = {"600789": {"qty": 100, "cost_price": 10.0, "name": "鲁信创投"}}
    acct["cash"] = 500.0
    (isolated_data_dir / "sim_account.json").write_text(json.dumps(acct), encoding="utf-8")

    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 12.0, "name": "鲁信创投"}}
    view = account.build_account_view(ds)
    assert view["cash"] == 500.0
    assert view["market_value"] == 1200.0
    assert view["total_assets"] == 1700.0
    assert view["total_pnl"] == 700.0
    pos_row = view["positions"][0]
    assert pos_row["code"] == "600789"
    assert pos_row["pnl_pct"] == 20.0  # (12/10 - 1)*100


def test_buy_calls_sim_trade_and_captures_result(seeded_account_file):
    """调 sim_trade.buy,捕获其 stdout 输出判断成功/失败。"""
    with patch("app.services.account.sim_trade") as mock_st:
        mock_st.buy.return_value = None  # sim_trade.buy 打印,无返回值
        result = account.buy("600789", qty=100)
    mock_st.buy.assert_called_once_with("600789", qty=100, amount=None)
    assert result["ok"] is True


def test_buy_reports_error_when_sim_trade_raises(seeded_account_file):
    with patch("app.services.account.sim_trade") as mock_st:
        mock_st.buy.side_effect = RuntimeError("资金不足")
        result = account.buy("600789", qty=100)
    assert result["ok"] is False
    assert "资金不足" in result["error"]


def test_sell_calls_sim_trade(seeded_account_file):
    with patch("app.services.account.sim_trade") as mock_st:
        mock_st.sell.return_value = None
        result = account.sell("600789", qty=100)
    mock_st.sell.assert_called_once_with("600789", qty=100, all=False)
    assert result["ok"] is True


def test_history_returns_account_history(seeded_account_file):
    import json
    acct = account.load_account()
    acct["history"] = [{"type": "buy", "code": "600789", "time": "2026-06-22T10:00:00"}]
    (isolated_data_dir / "sim_account.json").write_text(json.dumps(acct), encoding="utf-8")
    history = account.history()
    assert len(history) == 1
    assert history[0]["code"] == "600789"
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd D:/finance-agent && python -m pytest tests/test_account_service.py -v`
Expected: FAIL —— `ImportError`

- [ ] **Step 3: 实现 account service**

`app/services/account.py`:

```python
"""虚拟账户 service —— 包装 vendors.sim_trade。

sim_trade 的 buy/sell 直接打印到 stdout,这里:
- 交易动作:转调 sim_trade.buy/sell,失败时 catch 异常返回结构化错误。
- 账户视图:直接读 data/sim_account.json + 调 DataSource 取现价装配。
设计 §4.9:sim_account.json 是唯一真实来源。
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import DATA_DIR
from app.services import state
from app.services.account_seed import INITIAL_CAPITAL
from vendors import sim_trade  # M1 已打路径补丁,ACCOUNT_FILE 指向 data/

log = logging.getLogger("finance-agent.account")

ACCOUNT_FILE = "sim_account.json"


def load_account() -> dict:
    data = state.load_json(ACCOUNT_FILE, default=None)
    if data is None:
        return {
            "initial_capital": INITIAL_CAPITAL, "cash": INITIAL_CAPITAL,
            "positions": {}, "history": [],
        }
    return data


def build_account_view(datasource: Any) -> dict:
    """装配账户视图:总资产/盈亏/持仓(含现价与盈亏%)。"""
    acct = load_account()
    positions = acct.get("positions", {})
    rows = []
    market_value = 0.0
    total_cost = 0.0
    quotes = datasource.get_realtime(list(positions.keys())) if positions else {}

    for code, pos in positions.items():
        q = quotes.get(code, {})
        price = q.get("price") or 0
        qty = pos.get("qty", 0)
        cost_price = pos.get("cost_price", 0)
        mv = price * qty
        cv = cost_price * qty
        pnl = mv - cv
        pnl_pct = (price / cost_price - 1) * 100 if cost_price else 0
        rows.append({
            "code": code, "name": pos.get("name") or q.get("name") or code,
            "qty": qty, "cost_price": cost_price, "price": price,
            "market_value": round(mv, 2), "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
        })
        market_value += mv
        total_cost += cv

    cash = acct.get("cash", 0)
    total_assets = cash + market_value
    return {
        "cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "total_assets": round(total_assets, 2),
        "total_pnl": round(total_assets - acct.get("initial_capital", total_assets), 2),
        "positions": rows,
    }


def buy(code: str, qty: int | None = None, amount: float | None = None) -> dict:
    try:
        sim_trade.buy(code, qty=qty, amount=amount)
        return {"ok": True}
    except Exception as e:
        log.warning("买入失败 %s: %s", code, e)
        return {"ok": False, "error": str(e)}


def sell(code: str, qty: int | None = None, all_: bool = False) -> dict:
    try:
        sim_trade.sell(code, qty=qty, all=all_)
        return {"ok": True}
    except Exception as e:
        log.warning("卖出失败 %s: %s", code, e)
        return {"ok": False, "error": str(e)}


def history() -> list[dict]:
    return load_account().get("history", [])
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd D:/finance-agent && python -m pytest tests/test_account_service.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/account.py tests/test_account_service.py
git commit -m "feat(services): 虚拟账户 包装 sim_trade + 账户视图装配"
```

---

## Task 2: 账户路由 + 页面

**Files:**
- Create: `app/routes/account.py`
- Create: `app/templates/account.html`
- Modify: `app/routes/pages.py`(移除占位)、`app/main.py`(注册)

- [ ] **Step 1: 写路由测试**

`tests/test_m4_routes.py`:

```python
"""M4 路由冒烟。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_account_page_200(client):
    with patch("app.routes.account.build_account_view", return_value={"cash": 1000, "market_value": 0, "total_assets": 1000, "total_pnl": 0, "positions": []}), \
         patch("app.routes.account.history", return_value=[]):
        resp = client.get("/account")
    assert resp.status_code == 200
    assert "账户" in resp.text


def test_account_buy_post(client):
    with patch("app.routes.account.buy", return_value={"ok": True}) as mock_buy, \
         patch("app.routes.account.build_account_view", return_value={"cash": 0, "market_value": 0, "total_assets": 0, "total_pnl": 0, "positions": []}), \
         patch("app.routes.account.history", return_value=[]):
        resp = client.post("/account/api/buy", data={"code": "600789", "qty": "100"})
    assert resp.status_code in (200, 303)
    mock_buy.assert_called_once()


def test_account_sell_post(client):
    with patch("app.routes.account.sell", return_value={"ok": True}) as mock_sell, \
         patch("app.routes.account.build_account_view", return_value={"cash": 0, "market_value": 0, "total_assets": 0, "total_pnl": 0, "positions": []}), \
         patch("app.routes.account.history", return_value=[]):
        resp = client.post("/account/api/sell", data={"code": "600789", "qty": "100"})
    assert resp.status_code in (200, 303)
    mock_sell.assert_called_once()


def test_policy_page_200(client):
    with patch("app.routes.policy.policy.search_news", return_value=[]):
        resp = client.get("/policy")
    assert resp.status_code == 200


def test_report_page_200(client):
    with patch("app.routes.report.report.list_history", return_value=[]):
        resp = client.get("/report")
    assert resp.status_code == 200


def test_report_extract_text_post(client):
    with patch("app.routes.report.report.extract_and_save", return_value={"title": "x", "rating": "买入"}) as mock_ext:
        resp = client.post("/report/api/extract", data={"text": "某研报内容"})
    assert resp.status_code == 200
    mock_ext.assert_called_once()


def test_backtest_page_200(client):
    resp = client.get("/backtest")
    assert resp.status_code == 200


def test_risk_page_200(client):
    with patch("app.routes.risk.risk.scan", return_value=[]):
        resp = client.get("/risk")
    assert resp.status_code == 200
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd D:/finance-agent && python -m pytest tests/test_m4_routes.py -v -k account`
Expected: FAIL

- [ ] **Step 3: 实现账户路由**

`app/routes/account.py`:

```python
"""虚拟账户路由。

GET  /account              账户页(视图+持仓+历史)
POST /account/api/buy      买入
POST /account/api/sell     卖出
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT
from app.datasources import get_datasource
from app.services import account

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


def _ctx(request: Request) -> dict:
    return {
        "request": request,
        "view": account.build_account_view(get_datasource()),
        "history": account.history(),
    }


@router.get("/account", response_class=HTMLResponse)
def page(request: Request):
    return templates.TemplateResponse("account.html", _ctx(request))


@router.post("/account/api/buy")
def buy(code: str = Form(...), qty: int = Form(None), amount: float = Form(None)):
    account.buy(code.strip(), qty=qty, amount=amount)
    return RedirectResponse(url="/account", status_code=303)


@router.post("/account/api/sell")
def sell(code: str = Form(...), qty: int = Form(None), all: bool = Form(False)):
    account.sell(code.strip(), qty=qty, all_=all)
    return RedirectResponse(url="/account", status_code=303)
```

- [ ] **Step 4: 实现 account.html**

```html
{% extends "base.html" %}
{% block title %}虚拟账户 - Finance Agent{% endblock %}
{% block content %}
<h1>虚拟账户 (1000元)</h1>

<div class="cards-row">
    <div class="card"><div class="label">总资产</div><div class="value">{{ '%.2f' % view.total_assets }}</div></div>
    <div class="card"><div class="label">现金</div><div class="value">{{ '%.2f' % view.cash }}</div></div>
    <div class="card"><div class="label">持仓市值</div><div class="value">{{ '%.2f' % view.market_value }}</div></div>
    <div class="card"><div class="label">总盈亏</div><div class="value {{ 'up' if view.total_pnl > 0 else 'down' }}">{{ '%+.2f' % view.total_pnl }}</div></div>
</div>

<h2>交易</h2>
<form class="card" method="post" action="/account/api/buy" style="display:flex; gap:8px; flex-wrap:wrap;">
    <input name="code" placeholder="代码" required>
    <input name="qty" type="number" step="100" placeholder="数量(100整数倍)">
    <input name="amount" type="number" step="0.01" placeholder="或金额">
    <button type="submit">买入</button>
</form>
<form class="card" method="post" action="/account/api/sell" style="display:flex; gap:8px; flex-wrap:wrap;">
    <input name="code" placeholder="代码" required>
    <input name="qty" type="number" placeholder="数量">
    <label><input type="checkbox" name="all" value="true"> 全部</label>
    <button type="submit" class="btn-danger">卖出</button>
</form>

<h2>持仓</h2>
<table>
    <tr><th>代码</th><th>名称</th><th>数量</th><th>成本</th><th>现价</th><th>市值</th><th>盈亏</th></tr>
    {% for p in view.positions %}
    <tr>
        <td>{{ p.code }}</td><td>{{ p.name }}</td><td>{{ p.qty }}</td>
        <td>{{ '%.3f' % p.cost_price }}</td><td>{{ p.price or '—' }}</td>
        <td>{{ '%.2f' % p.market_value }}</td>
        <td class="{{ 'up' if p.pnl > 0 else 'down' }}">{{ '%+.2f' % p.pnl }} ({{ '%.2f' % p.pnl_pct }}%)</td>
    </tr>
    {% else %}
    <tr><td colspan="7" class="muted">空仓</td></tr>
    {% endfor %}
</table>

<h2>交易历史</h2>
<table>
    <tr><th>时间</th><th>类型</th><th>代码</th><th>名称</th><th>价格</th><th>数量</th><th>金额</th><th>手续费</th></tr>
    {% for t in history %}
    <tr>
        <td>{{ t.time[:19] }}</td>
        <td>{{ '买入' if t.type == 'buy' else '卖出' }}</td>
        <td>{{ t.code }}</td><td>{{ t.name }}</td>
        <td>{{ '%.2f' % t.price }}</td><td>{{ t.qty }}</td>
        <td>{{ '%.2f' % t.amount }}</td><td>{{ '%.2f' % t.fee }}</td>
    </tr>
    {% else %}
    <tr><td colspan="8" class="muted">暂无交易</td></tr>
    {% endfor %}
</table>
{% endblock %}
```

- [ ] **Step 5: 注册路由 + 移除占位**

`app/main.py` `create_app()` 追加 `from app.routes.account import router as account_router; app.include_router(account_router)`。
`app/routes/pages.py` 的 `PLACEHOLDER_PAGES` 删除 `"account"`。

- [ ] **Step 6: 运行测试,确认通过**

Run: `cd D:/finance-agent && python -m pytest tests/test_m4_routes.py -v -k account`
Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
git add app/routes/account.py app/templates/account.html app/routes/pages.py app/main.py tests/test_m4_routes.py
git commit -m "feat(routes): 虚拟账户 买卖/持仓/历史"
```

---

## Task 3: 政策 service + 路由

**Files:**
- Create: `app/services/policy.py`、`app/routes/policy.py`、`app/templates/policy.html`

- [ ] **Step 1: 写 service 测试**

`tests/test_policy_service.py`:

```python
from __future__ import annotations
from unittest.mock import patch, MagicMock
from app.services import policy


def test_search_news_calls_monitor_and_returns_list():
    fake = [{"title": "央行降准", "source": "cls", "time": "2026-06-22", "url": "http://x", "summary": "..."}]
    with patch("app.services.policy.monitor") as mock_m:
        mock_m.search_policy_news.return_value = fake
        result = policy.search_news(keywords=["央行"])
    mock_m.search_policy_news.assert_called_once()
    assert result == fake


def test_search_news_failure_returns_empty():
    with patch("app.services.policy.monitor") as mock_m:
        mock_m.search_policy_news.side_effect = RuntimeError("net")
        result = policy.search_news()
    assert result == []


def test_enrich_adds_relation_fields():
    fake = [{"title": "支持半导体产业", "source": "x", "time": "t", "url": "", "summary": ""}]
    with patch("app.services.policy.monitor") as mock_m:
        mock_m.search_policy_news.return_value = fake
        mock_m.relate_stocks.return_value = {"sectors": ["半导体/芯片"], "stocks": [], "sentiment": "利好"}
        result = policy.search_news(enrich=True)
    assert result[0]["relation"]["sentiment"] == "利好"


def test_daily_brief_returns_string():
    with patch("app.services.policy.monitor") as mock_m:
        mock_m.daily_brief.return_value = "📋 政策日报..."
        result = policy.daily_brief()
    assert "政策日报" in result
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd D:/finance-agent && python -m pytest tests/test_policy_service.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 policy service**

`app/services/policy.py`:

```python
"""政策监控 service —— 包装 vendors.monitor。"""
from __future__ import annotations

import logging

from vendors import monitor

log = logging.getLogger("finance-agent.policy")


def search_news(keywords: list[str] | None = None, enrich: bool = False) -> list[dict]:
    try:
        news = monitor.search_policy_news(keywords=keywords, limit=30)
    except Exception as e:
        log.warning("search_policy_news 失败: %s", e)
        return []
    if enrich:
        for item in news:
            text = f"{item.get('title', '')} {item.get('summary', '')}"
            try:
                item["relation"] = monitor.relate_stocks(text)
            except Exception as e:
                log.warning("relate_stocks 失败: %s", e)
                item["relation"] = {"sectors": [], "stocks": [], "sentiment": "中性"}
    return news


def daily_brief() -> str:
    try:
        return monitor.daily_brief()
    except Exception as e:
        log.warning("daily_brief 失败: %s", e)
        return f"⚠️ 政策日报生成失败({e})。"
```

- [ ] **Step 4: 实现 policy 路由 + 页面**

`app/routes/policy.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT
from app.services import policy

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@router.get("/policy", response_class=HTMLResponse)
def page(request: Request):
    news = policy.search_news(enrich=True)
    brief = policy.daily_brief()
    return templates.TemplateResponse("policy.html", {"request": request, "news": news, "brief": brief})
```

`app/templates/policy.html`:

```html
{% extends "base.html" %}
{% block title %}政策监控 - Finance Agent{% endblock %}
{% block content %}
<h1>政策监控</h1>
<h2>政策日报</h2>
<div class="card"><pre>{{ brief }}</pre></div>
<h2>政策新闻</h2>
<table>
    <tr><th>时间</th><th>来源</th><th>标题</th><th>板块</th><th>情绪</th></tr>
    {% for n in news %}
    <tr>
        <td>{{ n.time }}</td><td>{{ n.source }}</td>
        <td><a href="{{ n.url }}" target="_blank">{{ n.title }}</a></td>
        <td>{{ n.relation.sectors | join(', ') }}</td>
        <td class="{{ 'up' if n.relation.sentiment == '利好' else 'down' if n.relation.sentiment == '利空' else '' }}">{{ n.relation.sentiment }}</td>
    </tr>
    {% else %}
    <tr><td colspan="5" class="muted">暂无政策新闻(可能非交易日)</td></tr>
    {% endfor %}
</table>
{% endblock %}
```

`app/main.py` 注册 `policy_router`;`pages.py` 删 `"policy"`。

- [ ] **Step 5: 运行测试 + Commit**

Run: `cd D:/finance-agent && python -m pytest tests/test_policy_service.py tests/test_m4_routes.py -v -k policy`
Expected: 5 passed

```bash
git add app/services/policy.py app/routes/policy.py app/templates/policy.html app/routes/pages.py app/main.py tests/test_policy_service.py tests/test_m4_routes.py
git commit -m "feat(routes): 政策监控 新闻+日报+板块关联高亮"
```

---

## Task 4: 研报 service + 路由 + PDF 依赖

**Files:**
- Modify: `pyproject.toml`(加 pdf optional 依赖)
- Create: `app/services/report.py`、`app/routes/report.py`、`app/templates/report.html`

- [ ] **Step 1: 加 optional 依赖**

修改 `pyproject.toml`,在 `[project.optional-dependencies]` 下追加:

```toml
pdf = [
    "pdfplumber>=0.10",
]
```

- [ ] **Step 2: 写 service 测试**

`tests/test_report_service.py`:

```python
from __future__ import annotations
import json
from unittest.mock import patch, MagicMock
import pytest
from app.services import report


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "DATA_DIR", tmp_path)
    return tmp_path


def test_extract_text_calls_vendors():
    with patch("app.services.report.extract") as mock_e:
        mock_e.extract_report.return_value = {"title": "x", "rating": "买入"}
        result = report.extract_and_save("研报正文...")
    mock_e.extract_report.assert_called_once_with("研报正文...")
    assert result["rating"] == "买入"


def test_extract_saves_history(isolated_data_dir):
    with patch("app.services.report.extract") as mock_e:
        mock_e.extract_report.return_value = {"title": "t", "rating": "增持"}
        report.extract_and_save("text")
    hist = report.list_history()
    assert len(hist) == 1
    assert hist[0]["rating"] == "增持"


def test_extract_from_pdf_passes_path(isolated_data_dir):
    with patch("app.services.report.extract") as mock_e:
        mock_e.extract_from_pdf.return_value = {"title": "pdf"}
        report.extract_and_save(pdf_path="fake.pdf")
    mock_e.extract_from_pdf.assert_called_once_with("fake.pdf")


def test_extract_from_url_passes_url(isolated_data_dir):
    with patch("app.services.report.extract") as mock_e:
        mock_e.extract_from_url.return_value = {"title": "url"}
        report.extract_and_save(url="http://x")
    mock_e.extract_from_url.assert_called_once_with("http://x")


def test_list_history_sorted_desc(isolated_data_dir):
    import time
    with patch("app.services.report.extract") as mock_e:
        mock_e.extract_report.return_value = {"title": "a"}
        report.extract_and_save("t1")
        time.sleep(0.01)
        mock_e.extract_report.return_value = {"title": "b"}
        report.extract_and_save("t2")
    hist = report.list_history()
    assert hist[0]["title"] == "b"  # 最新在前
```

> **注意** fixture 必须用 `return tmp_path`(不是 `yield`),与其它 service 测试一致。

- [ ] **Step 3: 运行,确认失败**

Run: `cd D:/finance-agent && python -m pytest tests/test_report_service.py -v`
Expected: FAIL

- [ ] **Step 4: 实现 report service**

`app/services/report.py`:

```python
"""研报提炼 service —— 包装 vendors.extract + 历史归档。"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from app.config import DATA_DIR
from vendors import extract

log = logging.getLogger("finance-agent.report")

HISTORY_FILE = "report_history.json"


def extract_and_save(text: str | None = None, pdf_path: str | None = None, url: str | None = None) -> dict:
    try:
        if pdf_path:
            result = extract.extract_from_pdf(pdf_path)
        elif url:
            result = extract.extract_from_url(url)
        else:
            result = extract.extract_report(text or "")
    except Exception as e:
        log.warning("研报提炼失败: %s", e)
        result = {"error": str(e)}
    result["extracted_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _append_history(result)
    return result


def _append_history(item: dict) -> None:
    from app.services.state import load_json, save_json
    hist = load_json(HISTORY_FILE, default=[])
    if not isinstance(hist, list):
        hist = []
    hist.append(item)
    save_json(HISTORY_FILE, hist)


def list_history() -> list[dict]:
    from app.services.state import load_json
    hist = load_json(HISTORY_FILE, default=[])
    if not isinstance(hist, list):
        return []
    return sorted(hist, key=lambda x: x.get("extracted_at", ""), reverse=True)
```

- [ ] **Step 5: 实现 report 路由 + 页面**

`app/routes/report.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import tempfile

from app.config import PROJECT_ROOT, DATA_DIR
from app.services import report

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@router.get("/report", response_class=HTMLResponse)
def page(request: Request):
    return templates.TemplateResponse("report.html", {"request": request, "result": None, "history": report.list_history()})


@router.post("/report/api/extract", response_class=HTMLResponse)
def extract_text(request: Request, text: str = Form("")):
    result = report.extract_and_save(text=text) if text else {"error": "请输入文本"}
    return templates.TemplateResponse("report.html", {"request": request, "result": result, "history": report.list_history()})


@router.post("/report/api/extract_url", response_class=HTMLResponse)
def extract_url(request: Request, url: str = Form(...)):
    result = report.extract_and_save(url=url)
    return templates.TemplateResponse("report.html", {"request": request, "result": result, "history": report.list_history()})


@router.post("/report/api/extract_pdf", response_class=HTMLResponse)
async def extract_pdf(request: Request, file: UploadFile = File(...)):
    tmp = Path(tempfile.mkdtemp()) / file.filename
    tmp.write_bytes(await file.read())
    result = report.extract_and_save(pdf_path=str(tmp))
    return templates.TemplateResponse("report.html", {"request": request, "result": result, "history": report.list_history()})
```

`app/templates/report.html`:

```html
{% extends "base.html" %}
{% block title %}研报提炼 - Finance Agent{% endblock %}
{% block content %}
<h1>研报提炼</h1>

<form class="card" method="post" action="/report/api/extract">
    <h3>粘贴研报文本</h3>
    <textarea name="text" rows="6" style="width:100%" placeholder="粘贴研报全文..."></textarea>
    <button type="submit">提炼</button>
</form>

<form class="card" method="post" action="/report/api/extract_url">
    <h3>输入研报 URL</h3>
    <input name="url" style="width:70%" placeholder="https://...">
    <button type="submit">提炼</button>
</form>

<form class="card" method="post" action="/report/api/extract_pdf" enctype="multipart/form-data">
    <h3>上传 PDF</h3>
    <input type="file" name="file" accept=".pdf">
    <button type="submit">提炼</button>
    <p class="muted">PDF 提炼需安装 pdfplumber: <code>uv pip install pdfplumber</code></p>
</form>

{% if result %}
<h2>提炼结果</h2>
<div class="card">
    {% if result.error %}
    <p class="error-banner">{{ result.error }}</p>
    {% else %}
    <p><strong>标题:</strong> {{ result.title }}</p>
    <p><strong>机构:</strong> {{ result.institution }} | <strong>分析师:</strong> {{ result.analyst }}</p>
    <p><strong>评级:</strong> {{ result.rating }} | <strong>目标价:</strong> {{ result.target_price }} | <strong>现价:</strong> {{ result.current_price }} | <strong>上行空间:</strong> {{ result.upside }}</p>
    <p><strong>核心逻辑:</strong></p>
    <ul>{% for l in result.core_logic %}<li>{{ l }}</li>{% endfor %}</ul>
    <p><strong>风险提示:</strong></p>
    <ul>{% for r in result.risks %}<li>{{ r }}</li>{% endfor %}</ul>
    <p><strong>板块:</strong> {{ result.sectors | join(', ') }}</p>
    {% endif %}
</div>
{% endif %}

<h2>提炼历史</h2>
<table>
    <tr><th>时间</th><th>标题</th><th>评级</th><th>目标价</th></tr>
    {% for h in history %}
    <tr><td>{{ h.extracted_at }}</td><td>{{ h.title or '—' }}</td><td>{{ h.rating or '—' }}</td><td>{{ h.target_price or '—' }}</td></tr>
    {% else %}
    <tr><td colspan="4" class="muted">暂无历史</td></tr>
    {% endfor %}
</table>
{% endblock %}
```

`app/main.py` 注册 `report_router`;`pages.py` 删 `"report"`。

- [ ] **Step 6: 运行测试 + Commit**

Run: `cd D:/finance-agent && python -m pytest tests/test_report_service.py tests/test_m4_routes.py -v -k report`
Expected: 6 passed

```bash
git add app/services/report.py app/routes/report.py app/templates/report.html app/routes/pages.py app/main.py pyproject.toml tests/test_report_service.py tests/test_m4_routes.py
git commit -m "feat(routes): 研报提炼 文本/URL/PDF + 历史归档"
```

---

## Task 5: 回测引擎 service(TDD)

**Files:**
- Create: `app/services/backtest.py`
- Test: `tests/test_backtest_service.py`

- [ ] **Step 1: 写失败测试**

`tests/test_backtest_service.py`:

```python
from __future__ import annotations
from unittest.mock import MagicMock
import pytest
from app.services import backtest


@pytest.fixture
def uptrend_klines():
    """构造一段持续上涨的日K(10天,从10元涨到19元)。"""
    return [{"date": f"2026-06-{i:02d}", "open": 10+i-1, "high": 10+i, "low": 9+i-1, "close": 10+i, "volume": 1000} for i in range(1, 11)]


def test_ma_cross_strategy_buys_on_golden_cross(uptrend_klines):
    """MA5 上穿 MA20 应产生买入信号。"""
    signals = backtest.ma_cross_signals(uptrend_klines, fast=3, slow=5)
    buys = [s for s in signals if s["action"] == "buy"]
    assert len(buys) >= 1


def test_run_backtest_returns_metrics(uptrend_klines):
    ds = MagicMock()
    ds.get_kline.return_value = uptrend_klines
    result = backtest.run(ds, code="600789", strategy="ma_cross", start="2026-06-01", end="2026-06-10")
    assert "total_return_pct" in result
    assert "max_drawdown_pct" in result
    assert "sharpe" in result
    assert "win_rate" in result
    assert "trades" in result
    assert "equity_curve" in result


def test_run_backtest_applies_commission(uptrend_klines):
    """遵循 backtest_methodology:加摩擦。每笔交易扣手续费。"""
    ds = MagicMock()
    ds.get_kline.return_value = uptrend_klines
    result = backtest.run(ds, code="600789", strategy="ma_cross", start="2026-06-01", end="2026-06-10", commission_rate=0.001)
    # 有交易时,扣除手续费后的收益应低于无手续费
    assert result["commission_paid"] >= 0


def test_run_unknown_strategy_raises(uptrend_klines):
    ds = MagicMock()
    ds.get_kline.return_value = uptrend_klines
    with pytest.raises(ValueError):
        backtest.run(ds, code="600789", strategy="nonexistent", start="2026-06-01", end="2026-06-10")


def test_max_drawdown_calculation():
    """峰值到谷底的跌幅。"""
    curve = [100, 110, 105, 90, 95]  # 110→90 = -18.18%
    dd = backtest._max_drawdown_pct(curve)
    assert abs(dd - (-18.18)) < 0.1


def test_list_strategies():
    """列出 3 个内置策略名。"""
    names = backtest.list_strategies()
    assert set(names) >= {"ma_cross", "volume_breakout", "top_list_follow"}


def test_volume_breakout_strategy():
    """放量突破:当日量 > 5日均量*1.5 且收阳 → 买入。"""
    klines = [
        {"date": "2026-06-01", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-02", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-03", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-04", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-05", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2026-06-06", "open": 10, "high": 11, "low": 10, "close": 11, "volume": 200},  # 放量+收阳
    ]
    signals = backtest.volume_breakout_signals(klines, vol_window=5, multiplier=1.5)
    buys = [s for s in signals if s["action"] == "buy"]
    assert len(buys) >= 1
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd D:/finance-agent && python -m pytest tests/test_backtest_service.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 backtest service**

`app/services/backtest.py`:

```python
"""策略回测引擎(新写)。

遵循 vendors/backtest_methodology.md 「加摩擦、找最容易崩的」原则:
- 每笔交易扣 commission_rate(默认 0.00025,匹配 sim_trade)
- 卖出加印花税 stamp_tax(默认 0.001)
- 滑点用收盘价成交(保守近似)
指标:总收益、最大回撤、夏普(年化)、胜率。
"""
from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger("finance-agent.backtest")

DEFAULT_COMMISSION = 0.00025
DEFAULT_STAMP_TAX = 0.001  # 卖出单边


def list_strategies() -> list[str]:
    return ["ma_cross", "volume_breakout", "top_list_follow"]


def _sma(values: list[float], window: int) -> list[float | None]:
    out = [None] * len(values)
    for i in range(window - 1, len(values)):
        out[i] = sum(values[i - window + 1 : i + 1]) / window
    return out


def ma_cross_signals(klines: list[dict], fast: int = 5, slow: int = 20) -> list[dict]:
    """MA fast 上穿 slow 买入,下穿卖出。"""
    closes = [k["close"] for k in klines]
    ma_fast = _sma(closes, fast)
    ma_slow = _sma(closes, slow)
    signals = []
    for i in range(1, len(klines)):
        if ma_fast[i] is None or ma_slow[i] is None or ma_fast[i - 1] is None or ma_slow[i - 1] is None:
            continue
        crossed_up = ma_fast[i - 1] <= ma_slow[i - 1] and ma_fast[i] > ma_slow[i]
        crossed_down = ma_fast[i - 1] >= ma_slow[i - 1] and ma_fast[i] < ma_slow[i]
        if crossed_up:
            signals.append({"date": klines[i]["date"], "action": "buy", "price": klines[i]["close"]})
        elif crossed_down:
            signals.append({"date": klines[i]["date"], "action": "sell", "price": klines[i]["close"]})
    return signals


def volume_breakout_signals(klines: list[dict], vol_window: int = 5, multiplier: float = 1.5) -> list[dict]:
    """放量突破:当日量 > N日均量*multiplier 且收阳 → 买;反向收阴 → 卖。"""
    signals = []
    vols = [k["volume"] for k in klines]
    for i in range(vol_window, len(klines)):
        avg_vol = sum(vols[i - vol_window : i]) / vol_window
        is_up = klines[i]["close"] > klines[i]["open"]
        if vols[i] > avg_vol * multiplier:
            if is_up:
                signals.append({"date": klines[i]["date"], "action": "buy", "price": klines[i]["close"]})
            else:
                signals.append({"date": klines[i]["date"], "action": "sell", "price": klines[i]["close"]})
    return signals


def top_list_follow_signals(klines: list[dict], **_) -> list[dict]:
    """龙虎榜跟随:简化版,首日买入、末日卖出(真实需结合 get_top_list,M4 先占位)。"""
    if len(klines) < 2:
        return []
    return [
        {"date": klines[0]["date"], "action": "buy", "price": klines[0]["close"]},
        {"date": klines[-1]["date"], "action": "sell", "price": klines[-1]["close"]},
    ]


_STRATEGY_FNS = {
    "ma_cross": ma_cross_signals,
    "volume_breakout": volume_breakout_signals,
    "top_list_follow": top_list_follow_signals,
}


def _max_drawdown_pct(equity: list[float]) -> float:
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = (v - peak) / peak * 100 if peak else 0
        max_dd = min(max_dd, dd)
    return round(max_dd, 2)


def run(
    datasource: Any,
    code: str,
    strategy: str,
    start: str,
    end: str,
    fast: int = 5,
    slow: int = 20,
    commission_rate: float = DEFAULT_COMMISSION,
    stamp_tax: float = DEFAULT_STAMP_TAX,
    initial_capital: float = 10000.0,
) -> dict:
    if strategy not in _STRATEGY_FNS:
        raise ValueError(f"未知策略: {strategy},可选 {list(_STRATEGY_FNS)}")

    # 取一段日K(数据量足够,多取一些确保覆盖窗口)
    klines = datasource.get_kline(code, days=120, scale="240")
    # 按 start/end 过滤日期(简化:klines 已按日期升序)
    klines = [k for k in klines if start <= k["date"] <= end]
    if len(klines) < max(fast, slow) + 1:
        return {"error": f"K线数据不足({len(klines)} 根),至少需 {max(fast, slow)+1} 根"}

    fn = _STRATEGY_FNS[strategy]
    kwargs = {"fast": fast, "slow": slow} if strategy == "ma_cross" else {}
    signals = fn(klines, **kwargs)

    cash = initial_capital
    position = 0
    trades = []
    commission_paid = 0.0
    equity_curve = []

    for sig in signals:
        price = sig["price"]
        if sig["action"] == "buy" and position == 0:
            qty = int(cash / (price * (1 + commission_rate)))
            qty = (qty // 100) * 100
            if qty <= 0:
                continue
            fee = price * qty * commission_rate
            cash -= price * qty + fee
            commission_paid += fee
            position = qty
            trades.append({"date": sig["date"], "action": "buy", "price": price, "qty": qty, "fee": round(fee, 2)})
        elif sig["action"] == "sell" and position > 0:
            revenue = price * position
            fee = revenue * (commission_rate + stamp_tax)
            cash += revenue - fee
            commission_paid += fee
            trades.append({"date": sig["date"], "action": "sell", "price": price, "qty": position, "fee": round(fee, 2)})
            position = 0

    # 末日强制平仓计算终值
    last_price = klines[-1]["close"]
    final_equity = cash + position * last_price

    # 构造每日权益曲线(简化:按 kline 日期)
    for k in klines:
        mark_to_market = cash + position * k["close"]
        equity_curve.append({"date": k["date"], "equity": round(mark_to_market, 2)})

    total_return_pct = (final_equity / initial_capital - 1) * 100
    eq_values = [e["equity"] for e in equity_curve] or [initial_capital]

    # 夏普(简化:日收益标准差,年化 sqrt(252))
    daily_returns = []
    for i in range(1, len(eq_values)):
        if eq_values[i - 1] > 0:
            daily_returns.append(eq_values[i] / eq_values[i - 1] - 1)
    if daily_returns:
        mean_r = sum(daily_returns) / len(daily_returns)
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)) or 1e-9
        sharpe = round(mean_r / std_r * math.sqrt(252), 2)
    else:
        sharpe = 0.0

    wins = [t for t in trades if t["action"] == "sell"]
    win_rate = 0.0
    if wins and len(trades) >= 2:
        # 简化:盈利的卖出占比
        win_count = 0
        buys = [t for t in trades if t["action"] == "buy"]
        for b, s in zip(buys, wins):
            if s["price"] > b["price"]:
                win_count += 1
        win_rate = round(win_count / len(wins) * 100, 2) if wins else 0.0

    return {
        "code": code,
        "strategy": strategy,
        "start": start,
        "end": end,
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": _max_drawdown_pct(eq_values),
        "sharpe": sharpe,
        "win_rate": win_rate,
        "trades": trades,
        "equity_curve": equity_curve,
        "commission_paid": round(commission_paid, 2),
        "final_equity": round(final_equity, 2),
    }
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd D:/finance-agent && python -m pytest tests/test_backtest_service.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/backtest.py tests/test_backtest_service.py
git commit -m "feat(services): 回测引擎 ma_cross/volume_breakout/top_list + 摩擦/回撤/夏普"
```

---

## Task 6: 回测路由 + 页面

**Files:**
- Create: `app/routes/backtest.py`、`app/templates/backtest.html`

- [ ] **Step 1: 实现路由**

`app/routes/backtest.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT
from app.datasources import get_datasource
from app.services import backtest

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@router.get("/backtest", response_class=HTMLResponse)
def page(request: Request):
    return templates.TemplateResponse("backtest.html", {
        "request": request, "strategies": backtest.list_strategies(), "result": None,
    })


@router.post("/backtest/run", response_class=HTMLResponse)
def run(request: Request, code: str = Form(...), strategy: str = Form(...), start: str = Form(...), end: str = Form(...)):
    result = backtest.run(get_datasource(), code=code, strategy=strategy, start=start, end=end)
    return templates.TemplateResponse("backtest.html", {
        "request": request, "strategies": backtest.list_strategies(), "result": result,
        "code": code, "strategy": strategy, "start": start, "end": end,
    })
```

`app/templates/backtest.html`:

```html
{% extends "base.html" %}
{% block title %}策略回测 - Finance Agent{% endblock %}
{% block content %}
<h1>策略回测</h1>
<p class="muted">遵循「加摩擦、找最容易崩的」原则 —— 含佣金 0.025% + 印花税 0.1%。</p>

<form class="card" method="post" action="/backtest/run">
    <input name="code" placeholder="股票代码 如 600789" required value="{{ code or '' }}">
    <select name="strategy">
        {% for s in strategies %}<option value="{{ s }}" {{ 'selected' if s == strategy else '' }}>{{ s }}</option>{% endfor %}
    </select>
    <input name="start" type="date" required value="{{ start or '' }}">
    <input name="end" type="date" required value="{{ end or '' }}">
    <button type="submit">运行回测</button>
</form>

{% if result %}
<h2>回测结果</h2>
{% if result.error %}
<p class="error-banner">{{ result.error }}</p>
{% else %}
<div class="cards-row">
    <div class="card"><div class="label">总收益</div><div class="value {{ 'up' if result.total_return_pct > 0 else 'down' }}">{{ '%+.2f' % result.total_return_pct }}%</div></div>
    <div class="card"><div class="label">最大回撤</div><div class="value down">{{ result.max_drawdown_pct }}%</div></div>
    <div class="card"><div class="label">夏普</div><div class="value">{{ result.sharpe }}</div></div>
    <div class="card"><div class="label">胜率</div><div class="value">{{ result.win_rate }}%</div></div>
    <div class="card"><div class="label">手续费</div><div class="value">{{ result.commission_paid }}</div></div>
</div>
<div id="equity-chart" style="width:100%; height:300px;" data-curve='{{ result.equity_curve | tojson }}'></div>
<h3>交易明细({{ result.trades | length }} 笔)</h3>
<table>
    <tr><th>日期</th><th>动作</th><th>价格</th><th>数量</th><th>手续费</th></tr>
    {% for t in result.trades %}<tr><td>{{ t.date }}</td><td>{{ t.action }}</td><td>{{ t.price }}</td><td>{{ t.qty }}</td><td>{{ t.fee }}</td></tr>{% endfor %}
</table>
{% endif %}
{% endif %}
{% endblock %}
{% block scripts %}
<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
<script>
const ec = document.getElementById('equity-chart');
if (ec && ec.dataset.curve && typeof LightweightCharts !== 'undefined') {
    const curve = JSON.parse(ec.dataset.curve);
    if (curve.length) {
        const chart = LightweightCharts.createChart(ec, { width: ec.clientWidth, height: 300, layout: { background: { color: '#fff' }, textColor: '#333' } });
        const line = chart.addLineSeries({ color: '#2563eb' });
        line.setData(curve.map(p => ({ time: p.date, value: p.equity })));
        chart.timeScale().fitContent();
    }
}
</script>
{% endblock %}
```

`app/main.py` 注册;`pages.py` 删 `"backtest"`。

- [ ] **Step 2: 运行测试 + Commit**

Run: `cd D:/finance-agent && python -m pytest tests/test_m4_routes.py::test_backtest_page_200 -v`
Expected: PASS

```bash
git add app/routes/backtest.py app/templates/backtest.html app/routes/pages.py app/main.py
git commit -m "feat(routes): 策略回测 选择策略/区间 + 收益曲线"
```

---

## Task 7: 风险预警 service(TDD)

**Files:**
- Create: `app/services/risk.py`
- Test: `tests/test_risk_service.py`

- [ ] **Step 1: 写失败测试**

`tests/test_risk_service.py`:

```python
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from app.services import risk


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(risk, "DATA_DIR", tmp_path)
    yield tmp_path


@pytest.fixture(autouse=True)
def stub_watchlist(monkeypatch):
    monkeypatch.setattr(risk, "load_watchlist_meta", lambda: {
        "600789": {"name": "鲁信创投", "up_alert_pct": 5.0, "down_alert_pct": -3.0}
    })


def test_scan_detects_down_alert():
    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 9.5, "change_pct": -5.0, "name": "鲁信创投"}}
    ds.get_kline.return_value = []
    alerts = risk.scan(ds)
    assert len(alerts) == 1
    assert alerts[0]["code"] == "600789"
    assert "down" in alerts[0]["rules"]


def test_scan_detects_volume_spike():
    """放量异常:当日量 > 5日均量*2。"""
    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 10.0, "change_pct": 0.5, "volume": 10000, "name": "鲁信创投"}}
    ds.get_kline.return_value = [{"date": f"2026-06-{i:02d}", "close": 10, "volume": 1000} for i in range(1, 11)]
    alerts = risk.scan(ds)
    vol_alerts = [a for a in alerts if "volume_spike" in a["rules"]]
    assert len(vol_alerts) == 1


def test_scan_detects_ma_break():
    """破均线:现价跌破 20日均线。"""
    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 8.0, "change_pct": -2.0, "volume": 100, "name": "鲁信创投"}}
    ds.get_kline.return_value = [{"date": f"2026-06-{i:02d}", "close": 10, "volume": 100} for i in range(1, 21)]
    alerts = risk.scan(ds)
    ma_alerts = [a for a in alerts if "ma_break" in a["rules"]]
    assert len(ma_alerts) == 1


def test_scan_no_alert_when_quiet():
    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 10.0, "change_pct": 0.5, "volume": 100, "name": "鲁信创投"}}
    ds.get_kline.return_value = [{"date": f"2026-06-{i:02d}", "close": 10, "volume": 100} for i in range(1, 21)]
    alerts = risk.scan(ds)
    assert alerts == []


def test_scan_archives_alerts(isolated_data_dir):
    ds = MagicMock()
    ds.get_realtime.return_value = {"600789": {"price": 9.0, "change_pct": -5.0, "volume": 100, "name": "鲁信创投"}}
    ds.get_kline.return_value = []
    risk.scan(ds)
    # 归档文件存在
    import glob
    files = list((isolated_data_dir / "alerts").glob("*.json")) if (isolated_data_dir / "alerts").exists() else []
    assert len(files) >= 1


def test_scan_handles_empty_watchlist(monkeypatch):
    monkeypatch.setattr(risk, "load_watchlist_meta", lambda: {})
    ds = MagicMock()
    alerts = risk.scan(ds)
    assert alerts == []
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd D:/finance-agent && python -m pytest tests/test_risk_service.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 risk service**

`app/services/risk.py`:

```python
"""风险预警 service。

设计 §4.8:对自选股扫描规则:跌幅超阈值、放量异常、破均线。
触发归档到 data/alerts/。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from app.config import DATA_DIR
from app.services.watchlist import load_watchlist

log = logging.getLogger("finance-agent.risk")


def load_watchlist_meta() -> dict[str, dict]:
    """复用 watchlist 的自选股(代码+阈值)。"""
    return load_watchlist()


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0


def scan(datasource: Any) -> list[dict]:
    wl = load_watchlist_meta()
    if not wl:
        return []
    codes = list(wl.keys())
    quotes = datasource.get_realtime(codes)
    alerts = []
    for code in codes:
        meta = wl[code]
        q = quotes.get(code, {})
        change_pct = q.get("change_pct")
        price = q.get("price")
        rules = []

        # 规则1:涨跌幅超阈值
        up_t = meta.get("up_alert_pct")
        down_t = meta.get("down_alert_pct")
        if change_pct is not None:
            if up_t is not None and change_pct >= up_t:
                rules.append("up_threshold")
            if down_t is not None and change_pct <= down_t:
                rules.append("down_threshold")

        # 规则2/3:需 K线
        klines = datasource.get_kline(code, days=30, scale="240") if price else []
        # 放量异常
        if klines and len(klines) >= 6:
            recent_vols = [k["volume"] for k in klines[-6:-1]]
            avg_vol = _avg(recent_vols)
            today_vol = klines[-1]["volume"]
            if avg_vol > 0 and today_vol > avg_vol * 2:
                rules.append("volume_spike")
        # 破 20 日均线
        if klines and len(klines) >= 20 and price:
            ma20 = _avg([k["close"] for k in klines[-20:]])
            if price < ma20:
                rules.append("ma_break")

        if rules:
            alert = {
                "code": code,
                "name": q.get("name") or meta.get("name") or code,
                "price": price,
                "change_pct": change_pct,
                "rules": rules,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            alerts.append(alert)

    if alerts:
        _archive(alerts)
    return alerts


def _archive(alerts: list[dict]) -> None:
    path = DATA_DIR / "alerts" / f"{time.strftime('%Y-%m-%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(alerts, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd D:/finance-agent && python -m pytest tests/test_risk_service.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/risk.py tests/test_risk_service.py
git commit -m "feat(services): 风险预警 阈值/放量/破均线扫描 + 归档"
```

---

## Task 8: 风险预警路由 + 页面

**Files:**
- Create: `app/routes/risk.py`、`app/templates/risk.html`

- [ ] **Step 1: 实现路由**

`app/routes/risk.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT
from app.datasources import get_datasource
from app.services import risk

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@router.get("/risk", response_class=HTMLResponse)
def page(request: Request):
    alerts = risk.scan(get_datasource())
    return templates.TemplateResponse("risk.html", {"request": request, "alerts": alerts})
```

`app/templates/risk.html`:

```html
{% extends "base.html" %}
{% block title %}风险预警 - Finance Agent{% endblock %}
{% block content %}
<h1>风险预警</h1>
{% if alerts %}
<div class="error-banner">⚠️ 当前有 {{ alerts | length }} 条预警,请关注。</div>
{% endif %}
<table>
    <tr><th>代码</th><th>名称</th><th>现价</th><th>涨跌幅</th><th>触发规则</th><th>时间</th></tr>
    {% for a in alerts %}
    <tr class="alert-row">
        <td>{{ a.code }}</td><td>{{ a.name }}</td><td>{{ a.price }}</td>
        <td class="down">{{ a.change_pct }}%</td>
        <td>{{ a.rules | join(', ') }}</td>
        <td>{{ a.time }}</td>
    </tr>
    {% else %}
    <tr><td colspan="6" class="muted">✅ 暂无预警。规则在自选股页设置阈值后生效。</td></tr>
    {% endfor %}
</table>
<p class="muted">规则: down_threshold=跌破阈值 | volume_spike=放量2倍 | ma_break=破20日均线</p>
{% endblock %}
```

`app/main.py` 注册;`pages.py` 删 `"risk"`(此时 PLACEHOLDER_PAGES 应为空,占位路由可删)。

- [ ] **Step 2: 运行测试 + Commit**

Run: `cd D:/finance-agent && python -m pytest tests/test_m4_routes.py::test_risk_page_200 -v`
Expected: PASS

```bash
git add app/routes/risk.py app/templates/risk.html app/routes/pages.py app/main.py
git commit -m "feat(routes): 风险预警看板 + 触发归档"
```

---

## Task 9: 清理 M1 占位路由 + 最终验收

**Files:**
- Modify: `app/routes/pages.py`(PLACEHOLDER_PAGES 现已空,保留 index 路由)

- [ ] **Step 1: 简化 pages.py —— 只留首页**

M4 完成后,8 个功能页都有专门路由,`pages.py` 的 `placeholder` 函数不再需要。重写 `app/routes/pages.py`:

```python
"""首页路由。8 个功能页由各自模块处理。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT, get_settings

router = APIRouter(prefix="")
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "ai_enabled": get_settings().ai_enabled},
    )
```

- [ ] **Step 2: 更新 README**

`README.md` 进度块把 M4 改为 `[x]`,并在功能表下补一句「✅ 全部 8 个面板已实现」。

- [ ] **Step 3: 全量测试 + 手动验收**

Run:
```bash
cd D:/finance-agent
uv run python -m pytest -v       # 全部通过
uv run python -m app.main        # 手动点遍 8 个 tab
```

- [ ] **Step 4: Commit**

```bash
git add app/routes/pages.py README.md
git commit -m "feat: M4 完成 —— 8 面板全部实现,清理占位路由"
```

---

## M4 验收清单

**通过标准:**
- [ ] 全部 pytest 通过(M1+M2+M3+M4,预计 ~85 条)
- [ ] 虚拟账户页能买/卖(100 整数倍),持仓表显示成本/现价/盈亏,历史表有记录
- [ ] 政策监控页显示日报 + 新闻列表 + 板块/情绪高亮
- [ ] 研报页能粘贴文本提炼出评级/目标价/逻辑;PDF 上传需先装 pdfplumber
- [ ] 回测页选策略 + 区间后出收益曲线/回撤/夏普/胜率/手续费
- [ ] 风险预警页对设了阈值的自选股显示触发(交易时段内)
- [ ] `data/alerts/` 自动归档触发记录
- [ ] 所有页面任一数据源失败时显示占位符,不 500
- [ ] 8 个导航 tab 全部可点击进入真实功能页(无 🚧 占位)

---

## 四个里程碑全部完成后的最终状态

- 8 个 Web 面板全部可用:自选股 / 个股分析 / 虚拟账户 / 每日复盘 / 政策监控 / 研报提炼 / 策略回测 / 风险预警
- AI 解读(M3)与 AI 复盘(M3)在配 key 后可用,未配则降级
- vendors/ 资产原样保留,运行时通过 `vendors/__init__.py` 路径补丁工作
- 设计文档第 1-10 节全部落地,第 11 节待定项均已决定(lightweight-charts / 不纳入 fund-manager / 浏览器原生告警)
