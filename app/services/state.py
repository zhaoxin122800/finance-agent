"""data/ 运行时 JSON 状态读写 + schema 校验。

设计 §8:状态文件损坏时备份后重置为安全默认值,不崩。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

log = logging.getLogger("finance-agent.state")


def load_json(filename: str, default: Any = None) -> Any:
    """读 data/<filename>。损坏则备份后返回 default。"""
    path = DATA_DIR / filename
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("状态文件损坏 %s: %s —— 备份后返回默认值", path, e)
        backup = path.with_suffix(path.suffix + f".corrupt.{int(time.time())}")
        try:
            path.rename(backup)
        except OSError:
            pass
        return default


def save_json(filename: str, payload: Any) -> None:
    """写 data/<filename>,自动建父目录。"""
    path = DATA_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)  # 原子替换


def validate_sim_account(path: Path) -> bool:
    """校验 sim_account.json 的最小 schema。"""
    required = {"initial_capital", "cash", "positions", "history"}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    return required.issubset(data.keys()) and isinstance(data["positions"], dict) and isinstance(data["history"], list)
