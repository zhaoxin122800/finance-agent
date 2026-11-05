"""state 服务测试 —— 验证 data/ 下 JSON 的读写 + 损坏恢复。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import state


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """把 DATA_DIR 重定向到临时目录,隔离测试。"""
    monkeypatch.setattr(state, "DATA_DIR", tmp_path)
    return tmp_path


def test_load_json_returns_default_when_missing(isolated_data_dir):
    """文件不存在时返回默认值,不抛异常。"""
    result = state.load_json("missing.json", default={"a": 1})
    assert result == {"a": 1}


def test_save_then_load_json_roundtrip(isolated_data_dir):
    """保存后能读回。"""
    payload = {"positions": {}, "cash": 1000.0}
    state.save_json("acct.json", payload)
    assert state.load_json("acct.json", default={}) == payload


def test_save_json_creates_parent_dirs(isolated_data_dir):
    """嵌套路径自动建目录(data/analyses/x.json)。"""
    state.save_json("analyses/600789.json", {"x": 1})
    assert (isolated_data_dir / "analyses" / "600789.json").exists()


def test_load_corrupt_json_backs_up_and_returns_default(isolated_data_dir):
    """损坏文件应备份后返回默认(设计 §8 状态文件损坏处理)。"""
    bad = isolated_data_dir / "corrupt.json"
    bad.write_text("{not valid json", encoding="utf-8")
    result = state.load_json("corrupt.json", default={"recovered": True})
    assert result == {"recovered": True}
    # 备份文件存在
    backups = list(isolated_data_dir.glob("corrupt.json.corrupt.*"))
    assert len(backups) == 1


def test_sim_account_schema_valid(isolated_data_dir):
    """sim_account.json 必须有 initial_capital/cash/positions/history。"""
    state.save_json("sim_account.json", {
        "initial_capital": 1000.0,
        "cash": 1000.0,
        "positions": {},
        "history": [],
    })
    assert state.validate_sim_account(isolated_data_dir / "sim_account.json") is True


def test_sim_account_schema_invalid_triggers_reset(isolated_data_dir):
    """schema 不合法应返回 False(调用方据此重置)。"""
    state.save_json("sim_account.json", {"broken": True})
    assert state.validate_sim_account(isolated_data_dir / "sim_account.json") is False


def test_ensure_sim_account_seeds_when_missing(isolated_data_dir):
    """首次启动若 sim_account.json 不存在,写入初始账户(10万)。"""
    from app.services import account_seed
    account_seed.ensure_sim_account(str(isolated_data_dir / "sim_account.json"))
    loaded = state.load_json("sim_account.json")
    assert loaded["initial_capital"] == account_seed.INITIAL_CAPITAL
    assert loaded["cash"] == account_seed.INITIAL_CAPITAL
    assert loaded["positions"] == {}


def test_ensure_sim_account_preserves_existing(isolated_data_dir):
    """已有有效账户时不覆盖。"""
    from app.services import account_seed
    existing = {"initial_capital": 1000.0, "cash": 800.0, "positions": {"600789": {"qty": 100}}, "history": []}
    state.save_json("sim_account.json", existing)
    account_seed.ensure_sim_account(str(isolated_data_dir / "sim_account.json"))
    loaded = state.load_json("sim_account.json")
    assert loaded["cash"] == 800.0


def test_ensure_sim_account_resets_when_invalid(isolated_data_dir):
    """已有但 schema 不合法时重置为初始资金。"""
    from app.services import account_seed
    state.save_json("sim_account.json", {"broken": True})
    account_seed.ensure_sim_account(str(isolated_data_dir / "sim_account.json"))
    loaded = state.load_json("sim_account.json")
    assert loaded["cash"] == account_seed.INITIAL_CAPITAL
