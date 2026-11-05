from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.services import report


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    from app.services import state
    monkeypatch.setattr(state, "DATA_DIR", tmp_path)
    return tmp_path


def test_extract_text_calls_vendors():
    with patch("app.services.report.extract") as mock_e:
        mock_e.extract_report.return_value = {"title": "x", "rating": "买入"}
        result = report.extract_and_save("研报正文...")
    mock_e.extract_report.assert_called_once_with("研报正文...")
    assert result["rating"] == "买入"


def test_extract_saves_history():
    with patch("app.services.report.extract") as mock_e:
        mock_e.extract_report.return_value = {"title": "t", "rating": "增持"}
        report.extract_and_save("text")
    hist = report.list_history()
    assert len(hist) == 1
    assert hist[0]["rating"] == "增持"


def test_extract_from_pdf_passes_path():
    with patch("app.services.report.extract") as mock_e:
        mock_e.extract_from_pdf.return_value = {"title": "pdf"}
        report.extract_and_save(pdf_path="fake.pdf")
    mock_e.extract_from_pdf.assert_called_once_with("fake.pdf")


def test_extract_from_url_passes_url():
    with patch("app.services.report.extract") as mock_e:
        mock_e.extract_from_url.return_value = {"title": "url"}
        report.extract_and_save(url="http://x")
    mock_e.extract_from_url.assert_called_once_with("http://x")


def test_list_history_sorted_desc():
    with patch("app.services.report.extract") as mock_e:
        mock_e.extract_report.return_value = {"title": "a"}
        report.extract_and_save("t1")
        time.sleep(0.01)
        mock_e.extract_report.return_value = {"title": "b"}
        report.extract_and_save("t2")
    hist = report.list_history()
    assert hist[0]["title"] == "b"  # 最新在前


def test_extract_failure_records_error():
    """extract 抛异常时,记录 error 并归档。"""
    with patch("app.services.report.extract") as mock_e:
        mock_e.extract_report.side_effect = RuntimeError("parse fail")
        result = report.extract_and_save("text")
    assert "error" in result
    hist = report.list_history()
    assert len(hist) == 1
