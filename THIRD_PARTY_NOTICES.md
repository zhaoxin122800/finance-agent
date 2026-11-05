# 代码来源与第三方授权

核实日期为 2026 年 11 月 5 日。项目自身代码采用 Apache-2.0，第三方组件保留各自授权。根目录 LICENSE 为项目许可证，NOTICE 汇总归属声明，LICENSES 保存第三方许可文本。

## 随仓库分发的外部材料

| 文件 | 来源与作者 | 许可证及处理 |
| --- | --- | --- |
| vendors/a_stock_data.py | [simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data)，Simon Lin | Apache-2.0。保留作者声明及上游许可全文。提取自 SKILL.md 的代码经过可选依赖和项目适配，属于修改版本 |
| vendors/analyze.py、vendors/portfolio.py | [ClawHub a-stock-analysis 1.0.0](https://clawhub.ai/cnyezi/skills/a-stock-analysis)，CNyezi | MIT-0。除新增归属注释外，规范化换行后的原始文件 SHA-256 与官方版本清单一致 |
| vendors/backtest_methodology.md | [TraderMonty Backtest Expert](https://github.com/tradermonty/claude-trading-skills/tree/main/skills/backtest-expert)，TraderMonty | MIT。保留本项目使用的早期文档内容，随附上游 MIT 许可与版权声明 |

a-stock-analysis 的官方页面标注 MIT-0，[ClawHub 官方格式文档](https://github.com/openclaw/clawhub/blob/main/docs/skill-format.md)也说明平台发布技能采用 MIT-0。用于核对的 1.0.0 文件清单可从[官方版本接口](https://clawhub.ai/api/v1/skills/a-stock-analysis/versions/1.0.0)取得。

该版本 scripts/analyze.py 的 SHA-256 为 9558ecf2d3fa806b290aebc811b47a864a6ff0e3c8c64ae1cc80ee6550b5d33d，scripts/portfolio.py 为 46c3606bd479c8283662e3e0e2a92105877ec4885abf5e76043ed3d02a19170d。上述哈希对应本次添加归属注释前的文件。

## 本地创建材料

| 文件 | 来源记录 | 授权范围 |
| --- | --- | --- |
| vendors/data.py | 2026 年 6 月 22 日本地 AI 辅助创建 a-shares-data 的开发记录，基于已有新浪行情能力进行封装 | 项目新增部分采用 Apache-2.0，来自 a-stock-analysis 的部分保留 MIT-0 |
| vendors/monitor.py | 同日本地 AI 辅助创建 policy-monitor 的记录及后续适配 | 项目维护部分采用 Apache-2.0 |
| vendors/extract.py | 同日本地 AI 辅助创建 report-extractor 的记录及后续适配 | 项目维护部分采用 Apache-2.0 |
| vendors/quant_kb/ | 同日本地 AI 辅助编写知识文件的记录 | 项目维护部分采用 Apache-2.0 |
| vendors/sim_trade.py | 同日本地 AI 辅助创建及修改模拟账户脚本的记录 | 项目新增部分采用 Apache-2.0，调用的 a-stock-analysis 模块保留 MIT-0 |

本地创建过程依据开发会话中的任务、写文件和修改记录核实。原始会话保留在维护者本地。AI 辅助生成记录用于说明来源，无法单独证明内容的法律独创性。

## 页面加载的组件

| 组件 | 来源 | 许可与声明 |
| --- | --- | --- |
| Lightweight Charts 4.2.0 | [TradingView](https://github.com/tradingview/lightweight-charts/tree/v4.2.0) | Apache-2.0，包含 tslib 的 BSD-0-Clause 部分。随附 NOTICE 和 tslib 许可，页面展示 TradingView 归属及链接 |
| Marked | [markedjs/marked](https://github.com/markedjs/marked) | 随附上游 LICENSE，含 MIT 及其附带声明 |
| DOMPurify | [cure53/DOMPurify](https://github.com/cure53/DOMPurify) | 上游提供 Apache-2.0 或 MPL-2.0，本项目按 Apache-2.0 使用并保留完整上游许可文本 |
| JetBrains Mono | [JetBrains/JetBrainsMono](https://github.com/JetBrains/JetBrainsMono) | SIL Open Font License 1.1，保留上游许可文本 |

Python 安装依赖的许可证保留在各自发行包中。行情接口、网页和研报内容的访问及使用另受提供方条款约束，项目代码许可证仅覆盖相应软件与文档。
