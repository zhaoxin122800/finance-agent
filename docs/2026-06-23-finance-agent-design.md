# Finance Agent — 设计文档

- **日期**: 2026-06-23
- **项目位置**: `D:\finance-agent\`
- **作者**: 用户 + ZCode
- **状态**: 设计已确认，待写实现计划

---

## 1. 目标与范围

### 1.1 一句话目标

一个**自用**的本地 Web 金融助手，整合已有 A 股数据/分析/模拟交易/政策/研报等 Python 资产，提供自选股监控、个股 AI 分析、每日复盘、策略回测、风险预警等功能。

### 1.2 不做什么（YAGNI 边界）

- 不做多用户、登录、权限（自用）
- 不做云端部署、对外服务（本地跑）
- 不做对话式 agent 编排（autoclaw 已有，这里走"面板点按钮"交互）
- 不做行情撮合 / 实盘交易（只用 sim_trade 虚拟账户）
- **不纳入 skill-vetter**（那是 autoclaw 的安全工具，跟金融无关）

### 1.3 已确认的技术取舍

| 维度 | 决定 |
|------|------|
| 动机 | 自用工具 |
| 形态 | 本地 Web 面板（浏览器开 `localhost:8000`） |
| 后端 | Python 单体 FastAPI |
| 前端 | Jinja2 模板 + 少量 JS + lightweight-charts（K线） |
| 数据源 | 复用 `a-shares-data/data.py`（免费新浪/搜狐），预留 `DataSource` 接口可换付费源 |
| AI | 接 OpenAI 兼容 API（GLM/DeepSeek/通义），配置存 `.env` |
| 现成资产 | `data.py` / `analyze.py` / `portfolio.py` / `sim_trade.py` / `monitor.py` / `extract.py` / quant-kb 知识 / fund-manager 脚本 → **全部 vendored 进项目** |
| 项目位置 | `D:\finance-agent\` 独立目录，不进 travel-map |

---

## 2. 现成资产盘点（vendored 依赖）

从 `C:\Users\18600\.openclaw-autoclaw\` 复制进 `D:\finance-agent\vendors\`，保持原样不改动（便于以后同步升级）。

| 资产 | 来源 | 提供能力 | 关键接口 |
|------|------|---------|---------|
| `data.py` | skills/a-shares-data/scripts | A股数据层 | `get_realtime` `get_kline` `get_minute` `get_sectors` `get_top_list` `get_money_flow` |
| `analyze.py` | skills/a-stock-analysis/scripts | 实时行情 + 分时量能分析 | `analyze_stock(code, with_minute)` `fetch_realtime_sina` |
| `portfolio.py` | skills/a-stock-analysis/scripts | 持仓管理 | `load_portfolio` `add_position` `analyze_portfolio` |
| `sim_trade.py` | workspace | 1000元虚拟账户 | `buy` `sell` `show_account` `show_history` |
| `monitor.py` | skills/policy-monitor/scripts | 政策新闻 | `search_policy_news` `daily_brief` |
| `extract.py` | skills/report-extractor/scripts | 研报提炼 | `extract_report(text)` `extract_from_pdf` `extract_from_url` |
| `quant-kb/` | skills/quant-kb/knowledge | 量化知识库（5个 md） | 只读文件：terms/indicators/rules/strategies/faq |
| `backtest-expert/` | skills/backtest-expert/references | 回测方法论 | methodology.md（指导原则，非代码） |
| `fund-manager/` | skills/fund-manager/scripts | 基金估值/行业热度 | 多脚本，依赖 akshare（**可选**，先不启用） |

**状态文件**：`sim_account.json` 复制进 `data/` 作为初始账户状态。

---

## 3. 架构

```
┌──────────────────────────────────────────────────────────┐
│  浏览器  localhost:8000                                   │
│  ┌────┬────┬────┬────┬────┬────┬────┬────┐               │
│  │自选│个股│账户│复盘│政策│研报│回测│风控│  顶部导航      │
│  └────┴────┴────┴────┴────┴────┴────┴────┘               │
└──────────────────────┬───────────────────────────────────┘
                       │ HTTP / SSE
┌──────────────────────▼───────────────────────────────────┐
│  FastAPI 应用        app/                                 │
│   ├─ routes/        8 个功能页路由                        │
│   ├─ services/      业务逻辑（包装 vendors）              │
│   ├─ ai/            LLM 客户端（OpenAI 兼容）             │
│   ├─ datasources/   DataSource 接口 + 默认实现            │
│   └─ templates/     Jinja2                                │
└──────┬─────────────────────────────────┬─────────────────┘
       │                                 │
┌──────▼──────────┐               ┌──────▼─────────────────┐
│ services 层      │               │ vendors/ (原样复制)     │
│ 包装+缓存+AI 调用 │  ───────────► │ data.py sim_trade.py …  │
└─────────────────┘               └─────────────────────────┘
```

**关键原则**：vendors/ 里的脚本**不被修改**。services 层通过 `import` 调用它们的函数，并负责：
- 缓存（行情请求节流，避免被新浪封）
- 错误兜底（vendors 函数失败时返回安全默认值）
- AI 增值（拿 vendors 的原始数据丢给 LLM 生成解读）

---

## 4. 功能模块（8 个 Web 面板页）

### 4.1 自选股监控 Watchlist（新建 + 复用 portfolio.py）
- 自选股列表表格：代码 / 名称 / 现价 / 涨跌幅 / 成交量 / 更新时间
- 30 秒自动刷新（SSE 推送或前端轮询）
- 增删自选股（复用 `portfolio.py` 的 add/remove）
- 每只股票可设涨跌提醒阈值（存 `data/watchlist.json`）

### 4.2 个股分析 Stock-Analyst（新建 + AI）
- 输入代码 → 展示：K线图（lightweight-charts）+ 分时量能（analyze.py）+ 资金流（data.py）+ 龙虎榜
- **AI 解读按钮**：把上述原始数据打包成 prompt，调 LLM 生成一段文字解读
- 解读结果缓存到 `data/analyses/<code>-<date>.md`

### 4.3 虚拟账户 Account（复用 sim_trade.py）
- 账户卡片：总资产 / 现金 / 持仓市值 / 今日盈亏
- 持仓表格：代码 / 名称 / 数量 / 成本价 / 现价 / 盈亏%
- 买卖表单（调 sim_trade.buy/sell）
- 交易历史列表

### 4.4 每日复盘 Daily-Review（新建 + AI）
- 当日账户变动汇总（开仓/平仓/盈亏）
- 持仓异动（复用 analyze_portfolio）
- **AI 复盘报告**：把当日数据 + 大盘板块数据丢给 LLM，生成复盘 markdown
- 历史复盘归档 `data/reviews/<date>.md`

### 4.5 政策监控 Policy（复用 monitor.py）
- 政策新闻列表（search_policy_news）
- 政策日报生成（daily_brief）
- 关联板块/个股高亮

### 4.6 研报提炼 Report（复用 extract.py）
- 上传 PDF / 粘贴文本 / 输入 URL → 提炼评级/目标价/核心逻辑/风险
- 提炼历史列表

### 4.7 策略回测 Backtest（新建）
- 选策略（内置几个：均线交叉、放量突破、龙虎榜跟随）
- 选股票池 + 时间区间 → 跑回测
- 输出：收益曲线、胜率、最大回撤、夏普
- 遵循 backtest-expert/methodology.md 的"加摩擦、找最容易崩的"原则

### 4.8 风险预警 Risk-Alert（新建）
- 自选股触发规则看板：跌幅 > X%、放量异常、破均线
- 触发记录归档 `data/alerts/`
- 触发时面板顶部红色横幅 + 可选桌面通知

> **量化知识库 quant-kb** 不单独成页，作为 AI 解读的 RAG 上下文（AI 生成解读时自动检索相关知识）。

### 4.9 持仓来源统一约定（消除歧义）

`sim_trade.py` 和 `portfolio.py` 各自维护一份持仓，会冲突。约定：
- **以 `sim_trade.py` 的账户持仓为唯一真实来源**（`data/sim_account.json`），因为它带成本价/数量/盈亏计算。
- `portfolio.py` 的 `data/portfolio.json` **不复用**（仅 vendored 保留，不写入）。
- 自选股监控（4.1）用独立的 `data/watchlist.json`，**与持仓区分**：自选股是"关注列表"，持仓是"真买了的"。一只股票可以在自选里但没持仓，也可以既持仓又在自选。

---

## 5. 目录结构

```
D:\finance-agent\
├── docs/
│   └── 2026-06-23-finance-agent-design.md   # 本文档
├── vendors/                                  # 原样复制，不改
│   ├── data.py
│   ├── analyze.py
│   ├── portfolio.py
│   ├── sim_trade.py
│   ├── monitor.py
│   ├── extract.py
│   ├── quant_kb/
│   │   ├── terms.md indicators.md rules.md strategies.md faq.md
│   └── backtest_methodology.md
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 读 .env（LLM key、数据源选择）
│   ├── datasources/
│   │   ├── __init__.py
│   │   ├── base.py          # DataSource 抽象接口
│   │   └── free_source.py   # 默认实现，调 vendors/data.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── watchlist.py     # 包装 portfolio.py + 阈值
│   │   ├── analyst.py       # 包装 analyze.py + AI 解读
│   │   ├── account.py       # 包装 sim_trade.py
│   │   ├── review.py        # 每日复盘 + AI
│   │   ├── policy.py        # 包装 monitor.py
│   │   ├── report.py        # 包装 extract.py
│   │   ├── backtest.py      # 回测引擎（新写）
│   │   └── risk.py          # 风险预警（新写）
│   ├── ai/
│   │   ├── __init__.py
│   │   └── client.py        # OpenAI 兼容客户端 + prompt 模板
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── watchlist.py account.py analyst.py review.py
│   │   ├── policy.py report.py backtest.py risk.py
│   ├── templates/
│   │   ├── base.html        # 顶部导航 + 布局
│   │   ├── watchlist.html account.html analyst.html ...
│   └── static/
│       ├── style.css
│       └── app.js           # 轮询、K线渲染、表单提交
├── data/                    # 运行时状态（gitignore）
│   ├── sim_account.json     # 虚拟账户（从 workspace 复制初始版）
│   ├── watchlist.json       # 自选股 + 阈值
│   ├── portfolio.json       # portfolio.py 的持仓
│   ├── analyses/            # AI 解读归档
│   ├── reviews/             # 复盘归档
│   └── alerts/              # 预警归档
├── tests/
│   ├── test_datasources.py
│   ├── test_services.py
│   └── test_routes.py
├── .env.example             # LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
├── .gitignore
├── pyproject.toml           # uv 管理
└── README.md
```

---

## 6. 关键接口设计

### 6.1 DataSource 抽象（预留付费源）

```python
# app/datasources/base.py
class DataSource(Protocol):
    def get_realtime(self, codes: list[str]) -> dict[str, dict]: ...
    def get_kline(self, code: str, days: int = 30, scale: str = "240") -> list[dict]: ...
    def get_minute(self, code: str) -> list[dict]: ...
    def get_sectors(self) -> list[dict]: ...
    def get_money_flow(self, code: str) -> dict: ...
    def get_top_list(self, date: str | None = None) -> list[dict]: ...
```

默认实现 `FreeSource` 直接转调 `vendors.data`。将来接 Tushare/同花顺只需新增 `PaidSource` 并在 config 里切换。

### 6.2 AI 客户端

```python
# app/ai/client.py
class AIClient:
    def __init__(self, base_url: str, api_key: str, model: str): ...
    def complete(self, system: str, user: str, context: str = "") -> str: ...
```

三个 prompt 模板（写在 `app/ai/prompts.py`）：
- `ANALYST_PROMPT`：个股分析（输入行情+量能+资金流，输出解读）
- `REVIEW_PROMPT`：每日复盘（输入账户+持仓+板块，输出复盘报告）
- `RAG_PREFIX`：从 quant_kb 检索相关条款拼进 system prompt

> **【2026-06-23 更新】** M3 计划已将个股 AI 解读从单 `ANALYST_PROMPT` 升级为 **3 维度并行分析**。借鉴自 [`simonlin1212/TradingAgents-astock`](https://github.com/simonlin1212/TradingAgents-astock) 的多 Analyst 架构(7 Analyst),精选 3 个自用够用:
> - `TECHNICAL_PROMPT` 量价技术面(对应 Market Analyst)
> - `CAPITAL_PROMPT` 资金面/游资(对应 Hot Money Tracker,A 股核心维度)
> - `FUNDAMENTAL_PROMPT` 基本面/估值(对应 Fundamentals Analyst)
>
> 关键借鉴点:
> 1. **必采清单 prompt 技巧**——每个维度末尾列必覆盖数据点,缺失标注 `[数据缺失: xxx]` 而非瞎编(来自游资分析师 prompt)
> 2. **3 维度 ThreadPoolExecutor 并行**——延迟≈最慢维度(10-20s),任一失败不影响其它
> 3. **不引入 LangGraph**——保持 finance-agent 轻量,用标准库 concurrent.futures 即可
>
> 详细见 `docs/superpowers/plans/2026-06-23-m3-ai-integration.md` Task 2/5。

### 6.3 配置（.env）

```
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_API_KEY=your-key
LLM_MODEL=glm-4-flash
DATA_SOURCE=free          # free | paid（将来）
CACHE_TTL_REALTIME=30     # 秒
HOST=127.0.0.1
PORT=8000
```

---

## 7. 数据流（以"个股分析"为例）

```
用户在浏览器输入 600789，点"AI 分析"
  │
  ▼
GET /analyst/600789
  │
  ▼
analyst.py service:
  ├─ ds.get_realtime(["600789"])      ──► vendors.data.get_realtime
  ├─ ds.get_kline("600789", 90)       ──► vendors.data.get_kline
  ├─ analyze.analyze_stock("600789")  ──► vendors.analyze（量能）
  ├─ ds.get_money_flow("600789")      ──► vendors.data.get_money_flow
  └─ 拼装成 AnalystData
  │
  ▼  渲染 analyst.html（K线图 + 量能 + 资金流表格）
  │
  ▼  用户点"AI 解读"
POST /analyst/600789/interpret
  │
  ▼
ai.client.complete(ANALYST_PROMPT, json.dumps(AnalystData))
  │
  ▼
返回 markdown 解读 → 写入 data/analyses/600789-2026-06-23.md → 页面展示
```

---

## 8. 错误处理

- **vendors 函数失败**（网络、解析）：services 层 catch 后返回空字典/空列表 + 记日志，页面显示"数据获取失败，请稍后重试"，不抛 500。
- **LLM 调用失败**：AI 解读区显示"AI 服务暂不可用，原始数据已展示"，不影响其他功能。
- **API key 未配置**：AI 相关按钮置灰，提示去 `.env` 配置；非 AI 功能正常用。
- **状态文件损坏**（sim_account.json）：启动时校验 schema，损坏则备份后重置为初始 1000 元。
- **行情请求节流**：realtime 加内存缓存（TTL=30s），避免被新浪封 IP。

---

## 9. 测试策略

- **datasources 层**：mock vendors 函数，验证 FreeSource 正确转调 + 缓存生效。
- **services 层**：mock DataSource + AIClient，验证包装逻辑（盈亏计算、prompt 拼装、归档）。
- **routes 层**：FastAPI TestClient，验证 8 个页面的 GET/POST 返回 200 + 关键字段。
- **vendors 层不写测试**（是别人的代码，只验集成点）。
- AI 调用全部 mock，不实际打 LLM。

---

## 10. 实施顺序（给 writing-plans 用）

分 4 个里程碑，每个里程碑是一个可独立验证的切片：

1. **M1 骨架**：项目脚手架 + vendors 复制 + DataSource/FreeSource + config + 一个能跑的首页。验收：`uv run python -m app.main` 起服务，首页能显示空表格。
2. **M2 行情页**：自选股 + 个股分析（无 AI）。验收：能加自选股、看实时行情、看 K线。
3. **M3 AI 接入**：AI 客户端 + 个股 AI 解读 + 每日复盘。验收：点 AI 解读出文字、复盘报告归档。
4. **M4 完整功能**：账户 + 政策 + 研报 + 回测 + 风控。验收：8 个页面全部可用。

---

## 11. 待定项（实现时再决）

- K线图库最终选 lightweight-charts 还是 echarts（M2 时定）
- fund-manager 是否纳入（依赖 akshare 较重，默认不启用，M4 视情况）
- 桌面通知用 win10toast 还是浏览器 Notification（M4 时定）
