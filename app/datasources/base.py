"""数据源抽象接口。

设计 6.1:预留付费源。默认实现 FreeSource 转调 vendors.data,
将来接 Tushare/同花顺只需新增 PaidSource 并在 config 切换。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DataSource(Protocol):
    def get_realtime(self, codes: list[str]) -> dict[str, dict]:
        """实时行情。返回 {code: {name, price, open, high, low, pre_close, volume, amount, bid, ask, change_pct}}。"""
        ...

    def get_kline(self, code: str, days: int = 30, scale: str = "240") -> list[dict]:
        """历史K线。scale: 5/15/30/60/240 分钟(240=日K)。返回 [{date, open, high, low, close, volume}]。"""
        ...

    def get_minute(self, code: str) -> list[dict]:
        """分时(1分钟)。返回 [{time, price, volume, avg_price}]。"""
        ...

    def get_sectors(self) -> list[dict]:
        """板块行情。返回 [{name, change_pct, leader_stock}]。"""
        ...

    def get_money_flow(self, code: str) -> dict:
        """资金流向。返回 {main_net, super_large, large, medium, small}。"""
        ...

    def get_top_list(self, date: str | None = None) -> list[dict]:
        """龙虎榜。返回 [{code, name, close, change_pct, net_buy, buy_amount, sell_amount, reason}]。"""
        ...
