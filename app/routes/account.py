"""虚拟账户路由。

GET  /account              账户页(视图+持仓+历史)
POST /account/api/buy      买入
POST /account/api/sell     卖出
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT
from app.datasources import get_datasource
from app.services.account import build_account_view, buy, history, sell

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


def _ctx(request: Request) -> dict:
    return {
        "view": build_account_view(get_datasource()),
        "history": history(),
    }


@router.get("/account", response_class=HTMLResponse)
def page(request: Request):
    return templates.TemplateResponse(request, "account.html", _ctx(request))


@router.post("/account/api/buy")
def api_buy(code: str = Form(...), qty: str = Form(""), amount: str = Form("")):
    """买入。qty/amount 接收字符串(空串→None),避免空表单字段触发 422。"""
    buy(code.strip(), qty=_parse_optional_int(qty), amount=_parse_optional_float(amount))
    return RedirectResponse(url="/account", status_code=303)


@router.post("/account/api/sell")
def api_sell(code: str = Form(...), qty: str = Form(""), all: bool = Form(False)):
    """卖出。qty 空串→None(配合 all 清仓);非空转 int。"""
    sell(code.strip(), qty=_parse_optional_int(qty), all_=all)
    return RedirectResponse(url="/account", status_code=303)


def _parse_optional_int(v: str) -> int | None:
    """空串/非法值 → None,否则转 int。"""
    if not v or not v.strip():
        return None
    try:
        return int(v.strip())
    except (ValueError, TypeError):
        return None


def _parse_optional_float(v: str) -> float | None:
    """空串/非法值 → None,否则转 float。"""
    if not v or not v.strip():
        return None
    try:
        return float(v.strip())
    except (ValueError, TypeError):
        return None
