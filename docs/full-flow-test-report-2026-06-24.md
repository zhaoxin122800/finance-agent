# Finance Agent 完整流程测试报告

> 测试日期:2026-06-24 ｜ 环境本地实例 http://127.0.0.1:8000(PID 9336) ｜ LLM: DeepSeek (真实 key)
> 测试方式:真实 HTTP 请求 + service 层直调,数据真打网络、LLM 真调用,**未用任何 mock**。

---

## 一、完整业务流程(数据流)

```
选股入口                自选股监控                个股分析              模拟交易
┌─────────────┐      ┌──────────────┐      ┌────────────────┐     ┌──────────┐
│龙虎榜(东财) │──┐   │              │      │ realtime腾讯   │     │ 买入/卖出 │
│板块(新浪)   │  ├──>│ watchlist    │──┐   │ kline 百度→新浪│     │ sim_trade│
└─────────────┘  │   │ .json        │  │   │ 资金流 东财    │     │ 手续费   │
                 │   └──────────────┘  │   │ 分时量能       │     │ 印花税   │
  (选股发现)     │       增/删/阈值    │   └───────┬────────┘     └────┬─────┘
                 │                     │           │                   │
                 │                     │           ▼                   │
                 │                     │   ┌────────────────┐          │
                 │                     │   │ AI 三维度解读  │          │
                 │                     │   │ (DeepSeek 并行)│          │
                 │                     │   │ 量价/资金/基本面│          │
                 │                     │   └───────┬────────┘          │
                 │                     │           │                   │
                 │                     │           ▼                   ▼
                 │                     │   ┌────────────────────────────────┐
                 │                     │   │       每日复盘 (DeepSeek)        │
                 │                     │   │ 账户汇总+持仓异动+板块 → LLM     │
                 │                     │   └────────────────────────────────┘
                 │                     │
                 │   风控扫描 <─────────┘ (基于自选股 + 阈值规则)
                 │
                 └─> 回测引擎 / 政策新闻 / 研报提炼 (独立模块)
```

**核心数据来源:** `data/sim_account.json`(账户真实来源)、`data/watchlist.json`(自选股)、`data/analyses/`(解读归档)、`data/reviews/`(复盘归档)、`data/alerts/`(预警归档)。

---

## 二、逐功能真实测试结果

### Step 1 — 自选股监控 `/watchlist`
| 操作 | 请求 | 结果 | 落库 |
|------|------|------|------|
| 查 | `GET /watchlist/api/quotes` | HTTP 200,3 只股带实时行情 | — |
| 增 | `POST /watchlist/api/add code=601318` | HTTP 303(重定向) | `watchlist.json` +1 |
| 阈值 | `POST /watchlist/api/threshold code=600519 up=3 down=-1` | HTTP 303 | 持久化 |
| 删 | `POST /watchlist/api/remove code=002446` | HTTP 303 | `watchlist.json` -1 |

**真实数据样例**(`GET /watchlist/api/quotes`):
```
600519 贵州茅台 price=1228.6 change_pct=0.5 pe_ttm=18.57 mcap_yi=15358.5
600789 鲁抗医药  price=7.48   change_pct=1.08 pe_ttm=89.9  mcap_yi=67.22
```
腾讯富字段(PE/PB/市值/换手)正常带出。

### Step 2 — 个股分析 `/analyst/{code}`
`GET /analyst/600519` → HTTP 200,12.5KB 页面。service 装配数据:
```
realtime:  腾讯源,PE=18.52 PB=5.72 市值=15319亿  ✅
kline:     60条历史(百度→新浪降级链)            ✅
minute:    分时量能 distribution/signals          ✅
money_flow: 东财被风控 → 全0(降级口径正确)       ⚠️
on_top_list: 龙虎榜判定正常                       ✅
```

### Step 3 — 模拟交易 `/account`
> ⚠️ **发现 Bug**:初始资金 1000 元,sim_trade 要求最低 1 手(100股),连最便宜股都买不了。
> 测试时手动调 `initial_capital=100000` 解锁流程。

| 操作 | 结果 | 账户变化 |
|------|------|---------|
| 买入 600789 @7.44 ×600 | ✅ | cash -4469,持仓 +600 |
| 买入 601318 @49.89 ×100 | ✅ | cash -4994,持仓 +100 |
| 超额买入(钱不够) | 被拒(返回 ❌ 提示) | 不变 |
| 部分卖 600789 ×200 | ✅ | cash +1489,持仓 600→400 |
| 全部卖 601318 | ✅ | cash +4979,清仓 |
| 卖超(超持仓) | 被拒 | 不变 |

**最终账户**:cash=96991.38,持仓 600789×400@7.44,4 笔历史。

> 🔴 **Bug 记录**:`app/services/account.py` 的 `buy/sell` 吞错误 —— sim_trade 内部打印 `❌` 但函数返回 `None`,service 没 catch 异常就返回 `{"ok": True}`,**失败交易上报成功**。需改:判断 sim_trade 返回值或捕获其抛出的异常。

### Step 4 — AI 三维度解读 `/analyst/{code}/interpret`
`POST /analyst/600519/interpret` → 真实调 DeepSeek,**3 维度并行**(ThreadPoolExecutor),耗时 **45 秒**。
- 量价技术面 / 资金面游资 / 基本面估值 各独立 prompt + 必采清单
- 任一维度失败不影响其它
- 归档:`data/analyses/600789-2026-06-24.md`(4008 字)
- **去重生效**:同一天第二次调用返回归档,不重复打 LLM(跨日才重新生成)

**真实输出片段**(600789 技术面):
> MA5(7.21)MA10(7.18)MA20(7.73)...今日成交量 2555万股,较前日放大 85%...支撑位 7.09-7.12,压力位 7.73-7.80...

### Step 5 — 每日复盘 `/review/generate`
`POST /review/generate` → DeepSeek 单次调用,25 秒,归档 `data/reviews/2026-06-24.md`(2233 字)。
**真实输出片段**(准确引用账户数据):
> 总资产 99955.38,当日盈亏 -44.62...4 笔交易产生费用 26.62 元(5.04+5.05+6.50+10.03)...[数据缺失:板块数据]

诚实标注了板块数据缺失,没瞎编。

### Step 6 — 回测/风控/政策/研报
| 功能 | 端点 | 结果 |
|------|------|------|
| 风控扫描 | `GET /risk` | ✅ 3 条预警(检测 volume_spike/ma_break 规则) |
| 回测 | `POST /backtest/run` | ✅ 600789 ma_cross 触发 2 笔交易,总收益 -2.89% |
| 政策新闻 | `GET /policy` | 🔴 财联社接口 404 失效(外部源问题) |
| 研报提炼 | `POST /report/api/extract` | ✅ DeepSeek 准确提取评级「买入」目标价 310 |

---

## 三、发现的问题清单

| # | 严重度 | 位置 | 问题 |
|---|--------|------|------|
| 1 | 🔴 高 | `app/services/account.py` buy/sell | 吞错误:交易失败仍返回 `{ok:True}`,需 catch sim_trade 异常或判断返回值 |
| 2 | 🟡 中 | `account_seed.py` | 初始资金 1000 元无法买 1 手任何股,建议调到 100000 |
| 3 | 🟡 中 | `app/services/policy.py` | 财联社 `cls.cn` 接口 404,政策新闻功能失效,需换源 |
| 4 | 🟡 中 | `free_source.py` `_fetch_realtime_with_fallback` | 百度 K线偶发 `'list' object has no attribute 'get'`(降级新浪兜底成功,但日志报错) |
| 5 | 🟡 中 | `free_source.py` `get_money_flow` | 东财 push2 被风控频繁断连(10053),资金流长期全 0 |
| 6 | 🟢 低 | `screener.py` `hot_stocks` | 龙虎榜东财 reportapi 当日返回 0 条(非交易日/接口延迟) |

---

## 四、产出的数据文件(全部真实)

```
data/watchlist.json          3 只自选(600789/600519/601318)
data/sim_account.json        cash=96991,1 持仓,4 笔历史
data/report_history.json     1 条研报提炼记录
data/analyses/               4 份 AI 解读(2 股 × 2 天)
data/reviews/2026-06-24.md   1 份每日复盘
data/alerts/                 10 条风控预警记录
```

---

## 五、结论

**主流程(自选→分析→交易→AI解读→复盘)全部真实跑通**,LLM 真调用、数据真落库、降级链真实生效。
**6 个问题已记录**,其中 #1(交易吞错误)和 #3(政策源失效)需优先修复。
