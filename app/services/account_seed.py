"""启动时确保 sim_account.json 存在且有效。

设计 §8:启动时校验 schema,损坏则备份后重置为初始 1000 元。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from app.services.state import save_json, validate_sim_account

log = logging.getLogger("finance-agent.account_seed")

INITIAL_CAPITAL = 100000.0  # 10万:A股最低1手100股,1000元连最便宜的股都买不了


def _fresh_account() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "initial_capital": INITIAL_CAPITAL,
        "cash": INITIAL_CAPITAL,
        "positions": {},
        "history": [],
        "created_at": now,
        "updated_at": now,
    }


def ensure_sim_account(path: str | Path) -> None:
    """path 是 data/sim_account.json 的绝对路径。不存在或无效则(重)置。

    通过 state.save_json 写入:filename 取 path 的 name 部分,
    由 state.DATA_DIR 决定实际位置(便于测试 monkeypatch)。
    """
    p = Path(path)
    if p.exists() and validate_sim_account(p):
        return
    if p.exists():
        log.warning("sim_account.json 无效,重置为初始 %s 元", INITIAL_CAPITAL)
    save_json(p.name, _fresh_account())
