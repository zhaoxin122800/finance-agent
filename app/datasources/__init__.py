"""datasources 包 —— 根据配置选择数据源实现。

设计 6.3:DATA_SOURCE=free 用 FreeSource,paid 预留(M4 视情况)。
"""
from __future__ import annotations

from app.config import get_settings
from app.datasources.base import DataSource
from app.datasources.free_source import FreeSource

__all__ = ["DataSource", "FreeSource", "get_datasource"]


def get_datasource() -> DataSource:
    """根据 config.data_source 返回数据源实例。"""
    settings = get_settings()
    if settings.data_source == "paid":
        raise NotImplementedError("付费源尚未实现(见设计 §6.1,计划 M4 视情况)")
    return FreeSource(cache_ttl_realtime=settings.cache_ttl_realtime)
