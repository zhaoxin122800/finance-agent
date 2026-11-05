"""每日复盘路由。

GET  /review           查看今日复盘(账户汇总 + 已归档复盘)
POST /review/generate  生成/刷新今日 AI 复盘
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.ai import get_ai_client
from app.config import PROJECT_ROOT
from app.datasources import get_datasource
from app.services.review import generate_review, load_archived, summarize_account
from app.services.state import load_json

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))

ACCOUNT_FILE = "sim_account.json"
_DEFAULT_ACCOUNT = {"initial_capital": 100000.0, "cash": 100000.0, "positions": {}, "history": []}


def _context(request: Request) -> dict:
    account = load_json(ACCOUNT_FILE, default=_DEFAULT_ACCOUNT)
    summary = summarize_account(account, get_datasource())
    archived = load_archived(date.today().isoformat())
    return {"summary": summary, "archived": archived, "ai_enabled": get_ai_client() is not None}


@router.get("/review", response_class=HTMLResponse)
def page(request: Request):
    return templates.TemplateResponse(request, "review.html", _context(request))


@router.post("/review/generate", response_class=HTMLResponse)
def generate(request: Request):
    account = load_json(ACCOUNT_FILE, default=_DEFAULT_ACCOUNT)
    markdown = generate_review(account, get_datasource(), get_ai_client())
    ctx = _context(request)
    ctx["archived"] = markdown
    return templates.TemplateResponse(request, "review.html", ctx)
