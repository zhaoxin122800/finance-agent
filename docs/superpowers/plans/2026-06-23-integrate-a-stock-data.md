# 集成 a-stock-data V3.2.3 实现计划(已执行)

> 本计划于 2026-06-23 执行完成。记录于 `m1-skeleton` 分支,7 个 commit。

## 目标
把 `simonlin1212/a-stock-data` 的 V3.2.3(27 端点 / 13 数据源)整体抽取进 `vendors/a_stock_data.py`,升级 FreeSource 的实时行情为「腾讯→新浪降级链」、K线为「百度(带MA)→新浪降级」,其余端点原样保留供 service 层按需调。

## 完成情况(实际执行 vs 计划)

| Task | 计划 | 实际 | 备注 |
|------|------|------|------|
| 1 | 抽取 a_stock_data.py | ✅ 1256 行,32 函数块 | 抽取脚本调试 3 轮(demo 残留、多行常量、括号跟踪) |
| 2 | 端点测试 + 降级 | ✅ 41 测试 | 补了 em_get 缺 requests 时的友好守卫(计划要求的) |
| 3 | get_realtime 降级链 | ✅ 9 测试 | 腾讯优先,空/异常降级新浪,缓存正常 |
| 4 | get_kline 百度降级 | ✅ 7 测试 | _parse_baidu_kline 解析器兼容 keys 为 list 或 str |
| 5 | pyproject data-premium | ✅ | 顺带去掉 httpx 重复声明 |
| 6 | money_flow 口径统一 | ✅ | 失败返回全0结构而非 {} |
| 7 | 文档归档 | ✅ 本文件 | 设计文档作为历史快照不改,README 标注 |

## 架构决策记录
1. **DataSource Protocol 不扩展**:27 端点里只有 realtime/kline 走抽象,其余由 service 层 `from vendors import a_stock_data` 直接调。
2. **降级链只在高频接口**:get_realtime(腾讯→新浪)、get_kline(百度→新浪)。get_minute/sectors/money_flow/top_list 暂走新浪,M2-M4 按需升级。
3. **字段尽力而为**:腾讯有 PE/PB/市值无 volume;新浪有 volume/bid/ask 无 PE。降级时字段不强行对齐,消费方 `.get()` 取,缺失显示「—」。
4. **依赖可选**:mootdx/requests/pandas 在 `[data-premium]`,代码 try-import。纯 stdlib 端点(腾讯行情、估值计算)始终可用。

## 测试覆盖
- `tests/test_a_stock_data.py`:41 测试(端点存在性 + tencent_quote 解析 + em_get 降级 + 纯stdlib函数)
- `tests/test_datasources.py`:19 测试(降级链 + 缓存 + 解析器 + money_flow 口径)
- 全套 79 passed(含 M1 原有 27)

## 不做的事(YAGNI)
- 不扩展 DataSource Protocol
- 不并行请求多源
- 不动 get_minute/sectors/top_list
- 不引入字段强统一层
