"""研报提炼 service —— 包装 vendors.extract + 历史归档。"""
from __future__ import annotations

import logging
import time

from app.services import state
from vendors import extract

log = logging.getLogger("finance-agent.report")

HISTORY_FILE = "report_history.json"


def extract_and_save(text: str | None = None, pdf_path: str | None = None, url: str | None = None) -> dict:
    """提炼研报并归档历史。三个来源互斥,优先级 pdf > url > text。"""
    try:
        if pdf_path:
            result = extract.extract_from_pdf(pdf_path)
        elif url:
            result = extract.extract_from_url(url)
        else:
            result = extract.extract_report(text or "")
    except Exception as e:
        log.warning("研报提炼失败: %s", e)
        result = {"error": str(e)}
    result["extracted_at"] = time.strftime("%Y-%m-%d %H:%M:%S") + f".{int(time.time()*1000)%1000:03d}"
    _append_history(result)
    return result


def _append_history(item: dict) -> None:
    hist = state.load_json(HISTORY_FILE, default=[])
    if not isinstance(hist, list):
        hist = []
    hist.append(item)
    state.save_json(HISTORY_FILE, hist)


def list_history() -> list[dict]:
    hist = state.load_json(HISTORY_FILE, default=[])
    if not isinstance(hist, list):
        return []
    return sorted(hist, key=lambda x: x.get("extracted_at", ""), reverse=True)
