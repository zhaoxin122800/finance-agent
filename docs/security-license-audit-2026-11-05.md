# 授权与密钥检查记录

检查日期为 2026 年 11 月 5 日，检查对象为 Finance Agent 本地项目及 GitHub 仓库 zhaoxin122800/finance-agent。

## 授权处理

维护者已确认项目自身代码采用 Apache-2.0。本次加入 LICENSE、NOTICE 和 LICENSES，区分项目代码与外部材料。

- a-stock-data 采用 Apache-2.0，保留作者及完整许可，标明本地适配。
- a-stock-analysis 1.0.0 的官方页面标注 MIT-0。添加归属注释前的 analyze.py 和 portfolio.py，规范化换行后的 SHA-256 与官方清单一致。
- 回测方法文档来源于 TraderMonty 的 Backtest Expert，保留 MIT 许可与版权声明。
- 本地开发会话记录包含 data、monitor、extract、quant_kb、sim_trade 的 AI 辅助创建及修改过程。据此补充本地创建来源，继承自 a-stock-analysis 的部分保留 MIT-0。
- 补充页面组件的来源及许可文本，页面展示 TradingView 归属声明和链接。

原始开发会话保留在维护者本地。生成记录可辅助核实来源，无法单独证明内容的法律独创性。具体文件范围与上游链接见根目录 THIRD_PARTY_NOTICES.md。

## 密钥检查范围与结果

采用 Gitleaks v8.30.1 默认规则检查本地 Git 全部可达历史、工作目录以及已发布 GitHub main 分支历史。官方发布二进制的 SHA-256 已与同一发布中的校验清单核对。

| 检查 | 结果 |
| --- | --- |
| 本地 Git 全部分支历史 | Gitleaks 未发现密钥 |
| GitHub main 已发布历史 | Gitleaks 未发现密钥 |
| 当前本地工作目录 | 仅在已忽略的 .env 中检出本地模型密钥 |
| 当前配置密钥与历史内容精确比对 | 1 个密钥值，对 216 个唯一 blob 逐一比对，无匹配 |
| 历史覆盖 | 本地分支及 reflog 合计 67 个可达提交 |
| .env 跟踪状态 | 未被 Git 跟踪，已被忽略规则排除 |

报告、命令输出和公开文件均不包含实际密钥值。当前未在所检查的版本内容中发现密钥泄露。扫描器和当前密钥精确比对可能漏检其他格式的凭据，此结论限于已检查范围。

## 本次补充的保护

.gitignore 增加 .env.* 忽略规则并保留 .env.example，同时忽略常见私钥及证书容器扩展名。仓库继续以 .env.example 提供可公开的配置示例。

可在项目根目录运行以下命令复查。

```bash
gitleaks git . --log-opts="--all" --redact=100
gitleaks dir . --redact=100
```

目录扫描会报告本地 .env 中的实际配置，应结合 Git 跟踪状态判断是否已进入公开版本。任何后续发现已公开的真实凭据，应先在服务商撤销或轮换，再处理仓库中的残留内容。
