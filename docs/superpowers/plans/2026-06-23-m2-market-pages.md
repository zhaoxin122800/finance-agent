# M2 行情页实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **前置:** M1 骨架已完成(`DataSource`/`FreeSource`/`state`/导航/模板基座就绪)。本计划依赖以下 M1 产物,签名固定不变:
> - `app.datasources.get_datasource() -> DataSource`
> - `DataSource.get_realtime/get_kline/get_minute/get_money_flow/get_top_list/get_sectors`
> - `app.services.state.load_json/save_json(filename, ...)`
> - `app.templates/base.html` 的 `{% block content %}`

**Goal:** 实现自选股监控(增删 + 实时行情表格 + 涨跌提醒阈值)和个股分析(K线图 + 分时量能 + 资金流 + 龙虎榜,无 AI 解读 —— AI 留给 M3)。两个页面通过 `services` 层包装 `vendors` + `DataSource`,所有网络/解析失败在 service 层兜底为空值,页面绝不 500。

**Architecture:** `services/watchlist.py` 管 `data/watchlist.json`(代码 + 名称 + 涨/跌阈值),调 `DataSource.get_realtime` 批量取价;`services/analyst.py` 装配个股分析数据(实时 + K线 + 分时量能 + 资金流 + 龙虎榜)并校验。前端用 lightweight-charts 画 K线(设计 §11 待定项,本计划决定用 lightweight-charts:轻量、无依赖、CDN 引入)。

**Tech Stack:** 复用 M1 栈 + lightweight-charts(CDN,前端)。

---

## 文件结构

| 文件 | 责任 | 动作 |
|------|------|------|
| `app/services/watchlist.py` | 自选股 CRUD + 行情装配 | 新建 |
| `app/services/analyst.py` | 个股分析数据装配 | 新建 |
| `app/routes/watchlist.py` | 自选股路由(GET 列表/POST 增/POST 删/POST 阈值) | 新建 |
| `app/routes/analyst.py` | 个股分析路由(GET /analyst/{code}) | 新建 |
| `app/templates/watchlist.html` | 自选股表格页 | 新建 |
| `app/templates/analyst.html` | 个股分析页(K线 + 量能 + 资金流) | 新建 |
| `app/static/app.js` | lightweight-charts 渲染 + 30s 轮询 | 新建 |
| `tests/test_watchlist_service.py` | watchlist service 单测 | 新建 |
| `tests/test_analyst_service.py` | analyst service 单测 | 新建 |
| `tests/test_market_routes.py` | 路由冒烟 | 新建 |

**关键约定(来自设计 §4.1 / §4.9):**
- 自选股独立文件 `data/watchlist.json`,**与持仓 `sim_account.json` 区分**(自选=关注列表,持仓=真买了的)。
- 阈值:`{code: {name, up_alert_pct: float|None, down_alert_pct: float|None}}`。`None` 表示不设。
- 轮询:前端每 30s `fetch` `/watchlist/api/quotes`,不引 SSE(M2 先简单,SSE 留待 M4 优化)。

---

## Task 1: watchlist service(TDD)

**Files:**
- Create: `app/services/watchlist.py`
- Test: `tests/test_watchlist_service.py`

- [ ] **Step 1: 写失败测试**

`tests/test_watchlist_service.py`:

```python
"""watchlist service 测试 —— 全 mock DataSource,不打网络。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services import watchlist


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(watchlist, "DATA_DIR", tmp_path)
    yield tmp_path


@pytest.fixture
def fake_ds():
    return MagicMock()


def test_empty_watchlist_returns_empty_list(fake_ds):
    """无自选股时返回 []。"""
    ds = fake_ds
    result = watchlist.get_watchlist_with_quotes(ds)
    assert result == []


def test_add_stock_persists_to_watchlist(fake_ds):
    ds = fake_ds
    watchlist.add_stock("600789", "鲁信创投")
    saved = watchlist.load_watchlist()
    assert "600789" in saved
    assert saved["600789"]["name"] == "鲁信创投"


def test_add_stock_with_thresholds(fake_ds):
    ds = fake_ds
    watchlist.add_stock("600789", "鲁信创投", up_alert_pct=5.0, down_alert_pct=-3.0)
    saved = watchlist.load_watchlist()
    assert saved["600789"]["up_alert_pct"] == 5.0
    assert saved["600789"]["down_alert_pct"] == -3.0


def test_add_duplicate_stock_updates_name_and_thresholds(fake_ds):
    ds = fake_ds
    watchlist.add_stock("600789", "旧名")
    watchlist.add_stock("600789", "新名", up_alert_pct=8.0)
    saved = watchlist.load_watchlist()
    assert saved["600789"]["name"] == "新名"
    assert saved["600789"]["up_alert_pct"] == 8.0


def test_remove_stock(fake_ds):
    ds = fake_ds
    watchlist.add_stock("600789", "鲁信创投")
    watchlist.add_stock("002446", "纳思达")
    watchlist.remove_stock("600789")
    saved = watchlist.load_watchlist()
    assert "600789" not in saved
    assert "002446" in saved


def test_set_thresholds(fake_ds):
    ds = fake_ds
    watchlist.add_stock("600789", "鲁信创投")
    watchlist.set_thresholds("600789", up_alert_pct=7.0, down_alert_pct=None)
    saved = watchlist.load_watchlist()
    assert saved["600789"]["up_alert_pct"] == 7.0
    assert saved["600789"]["down_alert_pct"] is None


def test_get_watchlist_with_quotes_merges_realtime(fake_ds):
    """装配:把 watchlist 的 name/threshold 与实时行情合并。"""
    ds = fake_ds
    ds.get_realtime.return_value = {
        "600789": {"code": "600789", "name": "鲁信创投", "price": 10.5, "change_pct": 1.2, "volume": 1000},
    }
    watchlist.add_stock("600789", "鲁信创投", up_alert_pct=5.0)
    result = watchlist.get_watchlist_with_quotes(ds)
    assert len(result) == 1
    item = result[0]
    assert item["code"] == "600789"
    assert item["price"] == 10.5
    assert item["change_pct"] == 1.2
    assert item["up_alert_pct"] == 5.0


def test_get_watchlist_handles_missing_realtime(fake_ds):
    """行情取不到(code 错误或停牌)时该行 price=None,不崩。"""
    ds = fake_ds
    ds.get_realtime.return_value = {}  # 全空
    watchlist.add_stock("600789", "鲁信创投")
    result = watchlist.get_watchlist_with_quotes(ds)
    assert len(result) == 1
    assert result[0]["price"] is None
    assert result[0]["code"] == "600789"


def test_get_watchlist_alerts_when_threshold_breached(fake_ds):
    """涨跌幅超过阈值时 alert 字段非空。"""
    ds = fake_ds
    ds.get_realtime.return_value = {
        "600789": {"code": "600789", "price": 11.0, "change_pct": 6.5, "volume": 100, "name": "鲁信创投"},
    }
    watchlist.add_stock("600789", "鲁信创投", up_alert_pct=5.0)
    result = watchlist.get_watchlist_with_quotes(ds)
    assert result[0]["alert"] == "up"  # 6.5 > 5.0


def test_get_watchlist_no_alert_within_threshold(fake_ds):
    ds = fake_ds
    ds.get_realtime.return_value = {
        "600789": {"code": "600789", "price": 10.1, "change_pct": 1.0, "volume": 100, "name": "鲁信创投"},
    }
    watchlist.add_stock("600789", "鲁信创投", up_alert_pct=5.0, down_alert_pct=-3.0)
    result = watchlist.get_watchlist_with_quotes(ds)
    assert result[0]["alert"] is None
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd D:/finance-agent && python -m pytest tests/test_watchlist_service.py -v`
Expected: FAIL —— `ImportError`

- [ ] **Step 3: 实现 watchlist service**

`app/services/watchlist.py`:

```python
"""自选股监控 service —— 管理 data/watchlist.json + 装配实时行情。

设计 §4.1:自选股是"关注列表",与持仓(sim_account.json)区分。
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import DATA_DIR
from app.services import state

log = logging.getLogger("finance-agent.watchlist")

WATCHLIST_FILE = "watchlist.json"


def load_watchlist() -> dict[str, dict]:
    """返回 {code: {name, up_alert_pct, down_alert_pct}}。"""
    data = state.load_json(WATCHLIST_FILE, default={})
    return data if isinstance(data, dict) else {}


def _save(raw: dict[str, dict]) -> None:
    state.save_json(WATCHLIST_FILE, raw)


def add_stock(code: str, name: str = "", up_alert_pct: float | None = None, down_alert_pct: float | None = None) -> None:
    wl = load_watchlist()
    existing = wl.get(code, {})
    wl[code] = {
        "name": name or existing.get("name", code),
        "up_alert_pct": up_alert_pct if up_alert_pct is not None else existing.get("up_alert_pct"),
        "down_alert_pct": down_alert_pct if down_alert_pct is not None else existing.get("down_alert_pct"),
    }
    _save(wl)


def remove_stock(code: str) -> None:
    wl = load_watchlist()
    wl.pop(code, None)
    _save(wl)


def set_thresholds(code: str, up_alert_pct: float | None, down_alert_pct: float | None) -> None:
    wl = load_watchlist()
    if code not in wl:
        wl[code] = {"name": code, "up_alert_pct": None, "down_alert_pct": None}
    wl[code]["up_alert_pct"] = up_alert_pct
    wl[code]["down_alert_pct"] = down_alert_pct
    _save(wl)


def get_watchlist_with_quotes(datasource: Any) -> list[dict]:
    """装配自选股 + 实时行情。返回按 code 排序的列表。"""
    wl = load_watchlist()
    if not wl:
        return []
    codes = list(wl.keys())
    quotes = datasource.get_realtime(codes)
    rows = []
    for code in sorted(codes):
        meta = wl[code]
        q = quotes.get(code, {})
        change_pct = q.get("change_pct")
        alert = _check_alert(change_pct, meta.get("up_alert_pct"), meta.get("down_alert_pct"))
        rows.append({
            "code": code,
            "name": q.get("name") or meta.get("name") or code,
            "price": q.get("price"),
            "change_pct": change_pct,
            "volume": q.get("volume"),
            "up_alert_pct": meta.get("up_alert_pct"),
            "down_alert_pct": meta.get("down_alert_pct"),
            "alert": alert,
        })
    return rows


def _check_alert(change_pct: float | None, up: float | None, down: float | None) -> str | None:
    if change_pct is None:
        return None
    if up is not None and change_pct >= up:
        return "up"
    if down is not None and change_pct <= down:
        return "down"
    return None
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd D:/finance-agent && python -m pytest tests/test_watchlist_service.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/watchlist.py tests/test_watchlist_service.py
git commit -m "feat(services): watchlist CRUD + 行情装配 + 阈值预警检测"
```

---

## Task 2: analyst service(TDD)

**Files:**
- Create: `app/services/analyst.py`
- Test: `tests/test_analyst_service.py`

- [ ] **Step 1: 写失败测试**

`tests/test_analyst_service.py`:

```python
"""analyst service 测试 —— mock DataSource + vendors.analyze。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import analyst


@pytest.fixture
def fake_ds():
    return MagicMock()


def test_assemble_returns_combined_data(fake_ds):
    """装配:realtime + kline + minute_analysis + money_flow + top_list。"""
    ds = fake_ds
    ds.get_realtime.return_value = {"600789": {"code": "600789", "name": "鲁信创投", "price": 10.5, "change_pct": 1.2}}
    ds.get_kline.return_value = [{"date": "2026-06-20", "open": 10.0, "high": 10.8, "low": 9.9, "close": 10.5, "volume": 1000}]
    ds.get_money_flow.return_value = {"main_net": 5000000, "super_large": 3000000, "large": 2000000, "medium": -500000, "small": -1000000}
    ds.get_top_list.return_value = [{"code": "600789", "name": "鲁信创投", "net_buy": 5000000, "reason": "日涨幅偏离值"}]

    with patch("app.services.analyst.analyze") as mock_analyze:
        mock_analyze.analyze_stock.return_value = {
            "code": "600789", "name": "鲁信创投", "realtime": {"price": 10.5},
            "minute_analysis": {"volume_profile": "放量上涨"},
        }
        result = analyst.assemble("600789", ds)

    assert result["code"] == "600789"
    assert result["realtime"]["price"] == 10.5
    assert len(result["kline"]) == 1
    assert result["money_flow"]["main_net"] == 5000000
    assert result["minute_analysis"]["volume_profile"] == "放量上涨"
    assert result["on_top_list"] is True


def test_assemble_handles_all_sources_failing(fake_ds):
    """所有数据源失败时返回带 error 的结构,不抛异常(设计 §8)。"""
    ds = fake_ds
    ds.get_realtime.return_value = {}
    ds.get_kline.return_value = []
    ds.get_money_flow.return_value = {}
    ds.get_top_list.return_value = []
    with patch("app.services.analyst.analyze") as mock_analyze:
        mock_analyze.analyze_stock.return_value = {"error": "无法获取行情"}
        result = analyst.assemble("000000", ds)
    assert result["code"] == "000000"
    assert result["realtime"] == {}
    assert result["kline"] == []
    assert result["error"] == "无法获取行情"


def test_assemble_includes_60_day_kline_by_default(fake_ds):
    """默认拉 60 日日 K(给 K线图用)。"""
    ds = fake_ds
    ds.get_realtime.return_value = {}
    ds.get_kline.return_value = []
    ds.get_money_flow.return_value = {}
    ds.get_top_list.return_value = []
    with patch("app.services.analyst.analyze") as mock_analyze:
        mock_analyze.analyze_stock.return_value = {"code": "600789", "realtime": {}}
        analyst.assemble("600789", ds)
    ds.get_kline.assert_called_once_with("600789", 60, "240")


def test_assemble_detects_top_list_membership(fake_ds):
    """当 code 在龙虎榜里时 on_top_list=True 并附 reason。"""
    ds = fake_ds
    ds.get_realtime.return_value = {"600789": {"price": 10.5}}
    ds.get_kline.return_value = []
    ds.get_money_flow.return_value = {}
    ds.get_top_list.return_value = [{"code": "600789", "reason": "日涨幅偏离值7%"}]
    with patch("app.services.analyst.analyze") as mock_analyze:
        mock_analyze.analyze_stock.return_value = {"code": "600789", "realtime": {"price": 10.5}}
        result = analyst.assemble("600789", ds)
    assert result["on_top_list"] is True
    assert result["top_list_reason"] == "日涨幅偏离值7%"
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd D:/finance-agent && python -m pytest tests/test_analyst_service.py -v`
Expected: FAIL —— `ImportError`

- [ ] **Step 3: 实现 analyst service**

`app/services/analyst.py`:

```python
"""个股分析 service —— 装配实时/K线/分时量能/资金流/龙虎榜。

设计 §4.2:数据来自 DataSource + vendors.analyze。AI 解读在 M3。
"""
from __future__ import annotations

import logging
from typing import Any

from vendors import analyze  # 原样资产

log = logging.getLogger("finance-agent.analyst")


def assemble(code: str, datasource: Any) -> dict:
    """装配个股分析数据。所有子调用独立兜底,任一失败不影响其它字段。"""
    quotes = datasource.get_realtime([code])
    realtime = quotes.get(code, {})

    kline = datasource.get_kline(code, days=60, scale="240")
    money_flow = datasource.get_money_flow(code)

    # 分时量能(vendors.analyze 自己拉分时数据 + 分析)
    try:
        analysis = analyze.analyze_stock(code, with_minute=True, realtime_cache={})
    except Exception as e:
        log.warning("analyze_stock 失败(%s): %s", code, e)
        analysis = {"error": str(e)}

    top_list = datasource.get_top_list()
    on_top = next((t for t in top_list if t.get("code") == code), None)

    return {
        "code": code,
        "realtime": realtime,
        "kline": kline,
        "money_flow": money_flow,
        "minute_analysis": analysis.get("minute_analysis", {}),
        "error": analysis.get("error"),
        "on_top_list": on_top is not None,
        "top_list_reason": on_top.get("reason", "") if on_top else "",
    }
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd D:/finance-agent && python -m pytest tests/test_analyst_service.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/analyst.py tests/test_analyst_service.py
git commit -m "feat(services): analyst 装配 realtime/kline/量能/资金流/龙虎榜"
```

---

## Task 3: 自选股路由

**Files:**
- Create: `app/routes/watchlist.py`
- Modify: `app/main.py`(注册路由)

- [ ] **Step 1: 写路由冒烟测试**

`tests/test_market_routes.py`:

```python
"""watchlist + analyst 路由冒烟测试。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_watchlist_page_returns_200(client):
    with patch("app.routes.watchlist.get_watchlist_with_quotes", return_value=[]):
        resp = client.get("/watchlist")
    assert resp.status_code == 200
    assert "自选股" in resp.text


def test_watchlist_api_quotes_returns_json(client):
    with patch("app.routes.watchlist.get_watchlist_with_quotes", return_value=[{"code": "600789", "price": 10.5}]):
        resp = client.get("/watchlist/api/quotes")
    assert resp.status_code == 200
    assert resp.json() == [{"code": "600789", "price": 10.5}]


def test_watchlist_add_post(client):
    with patch("app.routes.watchlist.add_stock") as mock_add:
        resp = client.post("/watchlist/api/add", data={"code": "600789", "name": "鲁信创投"})
    assert resp.status_code in (200, 303)
    mock_add.assert_called_once()


def test_watchlist_remove_post(client):
    with patch("app.routes.watchlist.remove_stock") as mock_remove:
        resp = client.post("/watchlist/api/remove", data={"code": "600789"})
    assert resp.status_code in (200, 303)
    mock_remove.assert_called_once()


def test_analyst_page_returns_200(client):
    fake_data = {"code": "600789", "realtime": {"name": "鲁信创投", "price": 10.5}, "kline": [], "money_flow": {}, "minute_analysis": {}, "on_top_list": False, "top_list_reason": ""}
    with patch("app.routes.analyst.assemble", return_value=fake_data):
        resp = client.get("/analyst/600789")
    assert resp.status_code == 200
    assert "600789" in resp.text


def test_analyst_index_without_code_shows_form(client):
    resp = client.get("/analyst")
    assert resp.status_code == 200
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd D:/finance-agent && python -m pytest tests/test_market_routes.py -v`
Expected: FAIL —— 路由不存在(当前 /watchlist 是 M1 的占位)

- [ ] **Step 3: 实现 watchlist 路由**

`app/routes/watchlist.py`:

```python
"""自选股路由。

GET  /watchlist              页面
GET  /watchlist/api/quotes   JSON 行情(前端 30s 轮询)
POST /watchlist/api/add      增加自选
POST /watchlist/api/remove   删除自选
POST /watchlist/api/threshold  设阈值
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT
from app.datasources import get_datasource
from app.services import watchlist

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@router.get("/watchlist", response_class=HTMLResponse)
def page(request: Request):
    rows = watchlist.get_watchlist_with_quotes(get_datasource())
    return templates.TemplateResponse("watchlist.html", {"request": request, "rows": rows})


@router.get("/watchlist/api/quotes")
def api_quotes():
    rows = watchlist.get_watchlist_with_quotes(get_datasource())
    return JSONResponse(rows)


@router.post("/watchlist/api/add")
def api_add(code: str = Form(...), name: str = Form(""), up_alert_pct: float | None = Form(None), down_alert_pct: float | None = Form(None)):
    watchlist.add_stock(code.strip(), name.strip(), up_alert_pct, down_alert_pct)
    return RedirectResponse(url="/watchlist", status_code=303)


@router.post("/watchlist/api/remove")
def api_remove(code: str = Form(...)):
    watchlist.remove_stock(code.strip())
    return RedirectResponse(url="/watchlist", status_code=303)


@router.post("/watchlist/api/threshold")
def api_threshold(code: str = Form(...), up_alert_pct: float | None = Form(None), down_alert_pct: float | None = Form(None)):
    watchlist.set_thresholds(code.strip(), up_alert_pct, down_alert_pct)
    return RedirectResponse(url="/watchlist", status_code=303)
```

- [ ] **Step 4: 实现 analyst 路由**

`app/routes/analyst.py`:

```python
"""个股分析路由。

GET /analyst          输入框页(无 code)
GET /analyst/{code}   分析结果页(K线 + 量能 + 资金流)
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT
from app.datasources import get_datasource
from app.services import analyst

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@router.get("/analyst", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("analyst_index.html", {"request": request})


@router.get("/analyst/{code}", response_class=HTMLResponse)
def analyze_page(request: Request, code: str):
    data = analyst.assemble(code, get_datasource())
    return templates.TemplateResponse("analyst.html", {"request": request, "d": data})
```

- [ ] **Step 5: 注册路由 —— 修改 main.py**

在 `app/main.py` 的 `create_app()` 内 `app.include_router(pages_router)` 后追加:

```python
    from app.routes.watchlist import router as watchlist_router
    from app.routes.analyst import router as analyst_router
    app.include_router(watchlist_router)
    app.include_router(analyst_router)
```

> **注意**:M1 的 `pages.py` 有一个兜底 `GET /{page}` 路由会捕获 `/analyst`。需要在 pages.py 里把 `/analyst` 和 `/watchlist` 从占位里移除,否则 analyst 的 `GET /analyst`(无 code)会被占位吞掉。修改 `pages.py` 的 `PLACEHOLDER_PAGES`:删除 `"watchlist"` 和 `"analyst"` 两个 key(M2 起它们有专门路由)。

- [ ] **Step 6: 修改 pages.py 移除已实现页**

编辑 `app/routes/pages.py`,把 `PLACEHOLDER_PAGES` 改为:

```python
PLACEHOLDER_PAGES = {
    "account": "虚拟账户",
    "review": "每日复盘",
    "policy": "政策监控",
    "report": "研报提炼",
    "backtest": "策略回测",
    "risk": "风险预警",
}
```

- [ ] **Step 7: 运行测试,确认通过**

Run: `cd D:/finance-agent && python -m pytest tests/test_market_routes.py tests/test_routes.py -v`
Expected: market_routes 6 passed + M1 routes 仍通过

- [ ] **Step 8: Commit**

```bash
git add app/routes/watchlist.py app/routes/analyst.py app/routes/pages.py app/main.py tests/test_market_routes.py
git commit -m "feat(routes): 自选股 CRUD + 个股分析路由,移除 M1 占位"
```

---

## Task 4: 自选股页面模板

**Files:**
- Create: `app/templates/watchlist.html`

- [ ] **Step 1: 实现 watchlist.html**

```html
{% extends "base.html" %}
{% block title %}自选股 - Finance Agent{% endblock %}
{% block content %}
<h1>自选股监控</h1>

<form class="card" method="post" action="/watchlist/api/add">
    <h3>添加自选</h3>
    <input name="code" placeholder="代码 如 600789" required>
    <input name="name" placeholder="名称(可选)">
    <input name="up_alert_pct" type="number" step="0.1" placeholder="涨提醒% (可选)">
    <input name="down_alert_pct" type="number" step="0.1" placeholder="跌提醒% (可选, 负数)">
    <button type="submit">添加</button>
</form>

<table id="watchlist-table">
    <thead>
        <tr><th>代码</th><th>名称</th><th>现价</th><th>涨跌幅</th><th>成交量(手)</th><th>提醒</th><th>操作</th></tr>
    </thead>
    <tbody>
    {% for r in rows %}
        <tr class="{{ 'alert-row' if r.alert else '' }}">
            <td>{{ r.code }}</td>
            <td>{{ r.name }}</td>
            <td>{{ r.price if r.price is not none else '—' }}</td>
            <td class="{{ 'up' if (r.change_pct or 0) > 0 else 'down' if (r.change_pct or 0) < 0 else '' }}">
                {{ '%.2f' % r.change_pct if r.change_pct is not none else '—' }}%
            </td>
            <td>{{ r.volume if r.volume is not none else '—' }}</td>
            <td>
                {% if r.alert == 'up' %}🔺 涨超阈值{% elif r.alert == 'down' %}🔻 跌破阈值{% endif %}
                {% if not r.alert %}—{% endif %}
            </td>
            <td>
                <form method="post" action="/watchlist/api/remove" style="display:inline">
                    <input type="hidden" name="code" value="{{ r.code }}">
                    <button type="submit" class="btn-danger">删</button>
                </form>
            </td>
        </tr>
    {% else %}
        <tr><td colspan="7" class="muted">暂无自选股,用上方表单添加。</td></tr>
    {% endfor %}
    </tbody>
</table>

<script>
// 30s 轮询刷新行情(设计 §4.1)
async function refreshQuotes() {
    try {
        const resp = await fetch('/watchlist/api/quotes');
        const rows = await resp.json();
        const tbody = document.querySelector('#watchlist-table tbody');
        tbody.innerHTML = rows.map(r => `
            <tr class="${r.alert ? 'alert-row' : ''}">
                <td>${r.code}</td>
                <td>${r.name}</td>
                <td>${r.price !== null ? r.price : '—'}</td>
                <td class="${(r.change_pct||0) > 0 ? 'up' : (r.change_pct||0) < 0 ? 'down' : ''}">
                    ${r.change_pct !== null ? r.change_pct.toFixed(2) + '%' : '—'}
                </td>
                <td>${r.volume !== null ? r.volume : '—'}</td>
                <td>${r.alert === 'up' ? '🔺 涨超阈值' : r.alert === 'down' ? '🔻 跌破阈值' : '—'}</td>
                <td>
                    <form method="post" action="/watchlist/api/remove" style="display:inline">
                        <input type="hidden" name="code" value="${r.code}">
                        <button type="submit" class="btn-danger">删</button>
                    </form>
                </td>
            </tr>
        `).join('') || '<tr><td colspan="7" class="muted">暂无自选股</td></tr>';
    } catch (e) { console.warn('刷新失败', e); }
}
setInterval(refreshQuotes, 30000);
</script>
{% endblock %}
```

- [ ] **Step 2: 运行路由测试,确认页面渲染**

Run: `cd D:/finance-agent && python -m pytest tests/test_market_routes.py::test_watchlist_page_returns_200 -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add app/templates/watchlist.html
git commit -m "feat(templates): 自选股表格页 + 30s 轮询刷新"
```

---

## Task 5: 个股分析页面模板 + K线图

**Files:**
- Create: `app/templates/analyst_index.html`
- Create: `app/templates/analyst.html`
- Create: `app/static/app.js`

- [ ] **Step 1: 实现 analyst_index.html**

```html
{% extends "base.html" %}
{% block title %}个股分析 - Finance Agent{% endblock %}
{% block content %}
<h1>个股分析</h1>
<form class="card" action="/analyst" method="get" onsubmit="redirect(); return false;">
    <label>输入股票代码:</label>
    <input id="code-input" placeholder="如 600789" required>
    <button type="submit">分析</button>
</form>
<script>
function redirect() {
    const code = document.getElementById('code-input').value.trim();
    window.location.href = '/analyst/' + code;
}
</script>
{% endblock %}
```

- [ ] **Step 2: 实现 analyst.html**

```html
{% extends "base.html" %}
{% block title %}{{ d.code }} 分析 - Finance Agent{% endblock %}
{% block content %}
<h1>{{ d.realtime.name or d.code }} ({{ d.code }})</h1>

{% if d.error %}
<div class="error-banner">{{ d.error }}</div>
{% endif %}

<div class="cards-row">
    <div class="card">
        <div class="label">现价</div>
        <div class="value">{{ d.realtime.price or '—' }}</div>
    </div>
    <div class="card">
        <div class="label">涨跌幅</div>
        <div class="value {{ 'up' if (d.realtime.change_pct or 0) > 0 else 'down' }}">{{ '%.2f' % d.realtime.change_pct if d.realtime.change_pct is not none else '—' }}%</div>
    </div>
    {% if d.on_top_list %}
    <div class="card highlight">🐲 龙虎榜: {{ d.top_list_reason }}</div>
    {% endif %}
</div>

<h2>K线图(60日)</h2>
<div id="kline-chart" style="width:100%; height:400px;"></div>

<h2>资金流向(东财)</h2>
<table>
    <tr><th>主力净流入</th><th>超大单</th><th>大单</th><th>中单</th><th>小单</th></tr>
    <tr>
        <td>{{ d.money_flow.main_net or 0 }}</td>
        <td>{{ d.money_flow.super_large or 0 }}</td>
        <td>{{ d.money_flow.large or 0 }}</td>
        <td>{{ d.money_flow.medium or 0 }}</td>
        <td>{{ d.money_flow.small or 0 }}</td>
    </tr>
</table>

<h2>分时量能分析</h2>
<div class="card">
    {% if d.minute_analysis %}
    <pre>{{ d.minute_analysis | tojson(indent=2) }}</pre>
    {% else %}
    <p class="muted">无分时数据(可能非交易时段)</p>
    {% endif %}
</div>
{% endblock %}

{% block scripts %}
<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
<script>
const klineData = {{ d.kline | tojson }};
</script>
<script src="/static/app.js"></script>
{% endblock %}
```

- [ ] **Step 3: 实现 app.js(K线渲染)**

`app/static/app.js`:

```javascript
// lightweight-charts K线渲染(设计 §11 决定:用 lightweight-charts)
function renderKline() {
    const container = document.getElementById('kline-chart');
    if (!container || typeof LightweightCharts === 'undefined') return;
    if (!klineData || klineData.length === 0) {
        container.innerHTML = '<p class="muted">无K线数据</p>';
        return;
    }
    const chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: 400,
        layout: { background: { color: '#fff' }, textColor: '#333' },
    });
    const candleSeries = chart.addCandlestickSeries({
        upColor: '#ef5350', downColor: '#26a69a',  // A股红涨绿跌
        borderUpColor: '#ef5350', borderDownColor: '#26a69a',
        wickUpColor: '#ef5350', wickDownColor: '#26a69a',
    });
    candleSeries.setData(klineData.map(k => ({
        time: k.date,
        open: k.open, high: k.high, low: k.low, close: k.close,
    })));
    const volumeSeries = chart.addHistogramSeries({
        color: '#999', priceFormat: { type: 'volume' }, priceScaleId: '',
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    volumeSeries.setData(klineData.map(k => ({ time: k.date, value: k.volume, color: k.close >= k.open ? '#ef535080' : '#26a69a80' })));
    chart.timeScale().fitContent();
}
document.addEventListener('DOMContentLoaded', renderKline);
```

- [ ] **Step 4: 运行路由测试 + 手动验收**

Run: `cd D:/finance-agent && python -m pytest tests/test_market_routes.py -v`
Expected: 6 passed

手动: `uv run python -m app.main`,访问 `/watchlist` 添加 600789,访问 `/analyst/600789` 看 K线(交易时段内)。

- [ ] **Step 5: Commit**

```bash
git add app/templates/analyst_index.html app/templates/analyst.html app/static/app.js
git commit -m "feat(templates): 个股分析页 + lightweight-charts K线(红涨绿跌)"
```

---

## Task 6: 扩展 style.css

**Files:**
- Modify: `app/static/style.css`(追加表格/卡片/alert 样式)

- [ ] **Step 1: 追加样式**

在 `app/static/style.css` 末尾追加:

```css
table { width: 100%; border-collapse: collapse; background: #fff; margin-top: 12px; }
th, td { padding: 8px 12px; border-bottom: 1px solid #e5e7eb; text-align: left; font-size: 14px; }
th { background: #f9fafb; font-weight: 600; }
.card { background: #fff; padding: 16px; border-radius: 6px; margin: 12px 0; }
.cards-row { display: flex; gap: 12px; flex-wrap: wrap; }
.cards-row .card { flex: 1; min-width: 140px; text-align: center; }
.card .label { color: #6b7280; font-size: 12px; }
.card .value { font-size: 24px; font-weight: bold; }
.card.highlight { background: #fef3c7; }
.up { color: #dc2626; }       /* A股红涨 */
.down { color: #059669; }     /* 绿跌 */
.alert-row { background: #fef2f2; }
.error-banner { background: #fee2e2; color: #991b1b; padding: 12px; border-radius: 6px; margin: 12px 0; }
.btn-danger { background: #ef4444; color: #fff; border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer; }
input, button { padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 14px; }
button { background: #2563eb; color: #fff; border: none; cursor: pointer; }
button:hover { opacity: 0.9; }
form.card input { margin-right: 8px; }
pre { background: #f9fafb; padding: 12px; border-radius: 4px; overflow-x: auto; font-size: 12px; }
h1, h2, h3 { margin: 16px 0 8px; }
```

- [ ] **Step 2: Commit**

```bash
git add app/static/style.css
git commit -m "style: 表格/卡片/alert/表单样式"
```

---

## Task 7: 更新 README 进度

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 把 M2 checkbox 改为 [x]**

修改 `README.md` 的进度块,把 `- [ ] **M2 行情页**` 改为 `- [x] **M2 行情页**`。

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README 标注 M2 完成"
```

---

## M2 验收清单

```bash
cd D:/finance-agent
uv run python -m pytest -v          # 全部通过
uv run python -m app.main           # 手动验收
```

**通过标准:**
- [ ] 所有 pytest 通过(M1 + M2 新增,预计 ~30 条)
- [ ] 自选股页能添加/删除股票,30s 后行情自动刷新
- [ ] 设涨跌阈值后,触发行情时行变红 + 显示提醒图标
- [ ] 个股分析页输入代码后显示 K线图(红涨绿跌)+ 资金流表格 + 分时量能
- [ ] 任一数据源失败时页面显示占位符(—),不 500
- [ ] AI 解读按钮**不**出现(M3 才加)
