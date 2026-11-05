"""interpret service 测试 —— mock AIClient + DataSource。"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.services import interpret


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    from app.services import state
    monkeypatch.setattr(state, "DATA_DIR", tmp_path)
    yield tmp_path


@pytest.fixture
def fake_analyst_data():
    return {
        "code": "600789",
        "realtime": {"name": "鲁信创投", "price": 10.5, "change_pct": 1.2, "pe_ttm": 25.0, "pb": 3.0, "mcap_yi": 100.0, "turnover_pct": 5.0},
        "kline": [{"date": "2026-06-20", "close": 10.5, "ma5": 10.3, "ma10": 10.1, "ma20": 9.8, "volume": 1000}],
        "money_flow": {"main_net": 5000000, "super_large": 3000000, "large": 2000000},
        "minute_analysis": {"volume_profile": "放量"},
        "top_list_reason": "",
        "on_top_list": False,
        "company": {"name": "鲁信创投", "main_business": "创业投资", "industry": "金融"},
    }


def test_interpret_calls_4_dimensions_in_parallel(fake_analyst_data):
    """4 维度并行:ai.complete 应被调用 4 次(技术/资金/基本面/公司画像)。"""
    ai = MagicMock()
    ai.complete.side_effect = ["技术面报告", "资金面报告", "基本面报告", "公司画像报告"]
    md = interpret.interpret_stock("600789", fake_analyst_data, ai)
    assert ai.complete.call_count == 4
    assert "技术面报告" in md
    assert "资金面报告" in md
    assert "基本面报告" in md
    assert "公司画像报告" in md


def test_interpret_archives_merged_report(fake_analyst_data):
    """合并报告归档到 data/analyses/。"""
    ai = MagicMock()
    ai.complete.side_effect = ["技术", "资金", "基本面", "公司画像"]
    md = interpret.interpret_stock("600789", fake_analyst_data, ai)
    today = date.today().isoformat()
    archived = interpret.load_archived("600789", today)
    assert archived == md


def test_interpret_returns_archived_on_second_call(fake_analyst_data):
    """同一天重复解读返回已归档,不重复调 LLM。"""
    ai = MagicMock()
    ai.complete.side_effect = ["技术", "资金", "基本面", "公司画像"]
    interpret.interpret_stock("600789", fake_analyst_data, ai)
    ai.complete.reset_mock()
    again = interpret.interpret_stock("600789", fake_analyst_data, ai)
    assert again is not None
    ai.complete.assert_not_called()


def test_interpret_one_dimension_failure_doesnt_break_others(fake_analyst_data):
    """单个维度失败不影响其它,失败的维度显示错误,成功的正常。"""
    from app.ai.client import AIClientError
    ai = MagicMock()
    ai.complete.side_effect = ["技术面报告", AIClientError("资金面超时"), "基本面报告", "公司画像报告"]
    md = interpret.interpret_stock("600789", fake_analyst_data, ai)
    assert "技术面报告" in md
    assert "基本面报告" in md
    assert "资金面" in md and ("超时" in md or "失败" in md or "不可用" in md)


def test_interpret_all_dimensions_failure_returns_friendly(fake_analyst_data):
    """全部维度失败时返回统一降级提示(不归档空报告)。"""
    from app.ai.client import AIClientError
    ai = MagicMock()
    ai.complete.side_effect = AIClientError("服务不可用")
    md = interpret.interpret_stock("600789", fake_analyst_data, ai)
    assert "不可用" in md or "失败" in md


def test_interpret_without_ai_client_returns_disabled(fake_analyst_data):
    """ai=None 时返回降级提示,不调 LLM。"""
    result = interpret.interpret_stock("600789", fake_analyst_data, ai=None)
    assert "未启用" in result or "不可用" in result


def test_interpret_includes_rag_context(fake_analyst_data):
    """每个维度的 system prompt 都注入 quant-kb RAG 上下文。"""
    ai = MagicMock()
    ai.complete.side_effect = ["技术", "资金", "基本面", "公司画像"]
    with pytest.MonkeyPatch().context() as m:
        m.setattr(interpret, "build_rag_context", lambda code, data: "T+1 知识")
        interpret.interpret_stock("600789", fake_analyst_data, ai)
    for call in ai.complete.call_args_list:
        assert "T+1 知识" in call.kwargs.get("context", "")
