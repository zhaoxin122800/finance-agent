"""个股分析路由。

GET  /analyst                输入框页(无 code)
GET  /analyst/{code}         分析结果页(K线 + 量能 + 资金流)
POST /analyst/{code}/interpret  生成 AI 多维度解读(M3)
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.ai import get_ai_client
from app.config import PROJECT_ROOT
from app.datasources import get_datasource
from app.services.analyst import assemble
from app.services.interpret import generate_action_advice, interpret_stock
from app.services.review import summarize_account
from app.services.state import load_json

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@router.get("/analyst", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "analyst_index.html", {})


@router.get("/analyst/{code}", response_class=HTMLResponse)
def analyze_page(request: Request, code: str, scale: str = "240"):
    data = assemble(code, get_datasource(), kline_scale=scale)
    return templates.TemplateResponse(request, "analyst.html", {"d": data, "scale": scale})


@router.post("/analyst/{code}/interpret", response_class=HTMLResponse)
def interpret_page(request: Request, code: str, scale: str = "240"):
    data = assemble(code, get_datasource(), kline_scale=scale)
    markdown = interpret_stock(code, data, get_ai_client())
    return templates.TemplateResponse(request, "analyst.html", {"d": data, "scale": scale, "interpretation": markdown})


@router.post("/analyst/{code}/advice", response_class=HTMLResponse)
def advice_page(request: Request, code: str, scale: str = "240"):
    """AI 加购建议(结合整个账户 + 该股分析)。"""
    ds = get_datasource()
    data = assemble(code, ds, kline_scale=scale)
    account = load_json("sim_account.json", default={"initial_capital": 100000, "cash": 100000, "positions": {}, "history": []})
    account_summary = summarize_account(account, ds)
    advice = generate_action_advice(code, data, account_summary, get_ai_client())
    return templates.TemplateResponse(request, "analyst.html", {"d": data, "scale": scale, "advice": advice})


@router.get("/api/announcement/{art_code}")
def announcement_detail_api(art_code: str):
    """公告正文详情(JSON,供前端点击展开)。"""
    from fastapi.responses import JSONResponse
    from app.services.market import announcement_detail
    detail = announcement_detail(art_code)
    if not detail:
        return JSONResponse({"error": "获取公告详情失败"}, status_code=502)
    return detail
