"""自选股路由。

GET  /watchlist              页面
GET  /watchlist/api/quotes   JSON 行情(前端 30s 轮询)
POST /watchlist/api/add      增加自选
POST /watchlist/api/remove   删除自选
POST /watchlist/api/threshold  设阈值
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT
from app.datasources import get_datasource
from app.services.screener import hot_stocks as get_hot_stocks
from app.services.screener import market_list as get_market_list
from app.services.screener import sector_ranking as get_sector_ranking
from app.services.watchlist import (
    add_stock,
    get_watchlist_with_quotes,
    remove_stock,
    set_thresholds,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@router.get("/watchlist", response_class=HTMLResponse)
def page(request: Request):
    rows = get_watchlist_with_quotes(get_datasource())
    return templates.TemplateResponse(request, "watchlist.html", {"rows": rows})


@router.get("/watchlist/api/quotes")
def api_quotes():
    rows = get_watchlist_with_quotes(get_datasource())
    return JSONResponse(rows)


@router.post("/watchlist/api/add")
def api_add(
    code: str = Form(...),
    name: str = Form(""),
    up_alert_pct: str = Form(""),
    down_alert_pct: str = Form(""),
):
    """添加自选。阈值字段接收字符串(空串/非法值 → None),避免空表单字段触发 422。"""
    add_stock(code.strip(), name.strip(), _parse_optional_float(up_alert_pct), _parse_optional_float(down_alert_pct))
    return RedirectResponse(url="/watchlist", status_code=303)


@router.post("/watchlist/api/remove")
def api_remove(code: str = Form(...)):
    remove_stock(code.strip())
    return RedirectResponse(url="/watchlist", status_code=303)


@router.post("/watchlist/api/threshold")
def api_threshold(
    code: str = Form(...),
    up_alert_pct: str = Form(""),
    down_alert_pct: str = Form(""),
):
    set_thresholds(code.strip(), _parse_optional_float(up_alert_pct), _parse_optional_float(down_alert_pct))
    return RedirectResponse(url="/watchlist", status_code=303)


def _parse_optional_float(v: str) -> float | None:
    """空串/None/非法值 → None,否则转 float。容忍表单空字段。"""
    if not v or not v.strip():
        return None
    try:
        return float(v.strip())
    except (ValueError, TypeError):
        return None


@router.get("/watchlist/api/hot_stocks")
def api_hot_stocks():
    """当日龙虎榜热门股(选股入口)。"""
    return JSONResponse(get_hot_stocks(limit=30))


@router.get("/watchlist/api/sectors")
def api_sectors():
    """板块涨跌排名(选股入口)。"""
    return JSONResponse(get_sector_ranking(get_datasource()))


@router.get("/watchlist/api/market")
def api_market(page: int = 1, num: int = 50, sort: str = "changepercent", asc: bool = False, query: str = ""):
    """全市场选股器(沪深 A 股实时行情,支持排序/搜索/分页)。"""
    return JSONResponse(get_market_list(page=page, num=num, sort=sort, asc=asc, query=query))
