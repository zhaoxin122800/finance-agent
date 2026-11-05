"""策略回测路由。

GET  /backtest       表单页(选策略/区间)
POST /backtest/run   运行回测,显示结果 + 收益曲线
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT
from app.datasources import get_datasource
from app.services.backtest import list_strategies, run

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@router.get("/backtest", response_class=HTMLResponse)
def page(request: Request):
    return templates.TemplateResponse(request, "backtest.html", {
        "strategies": list_strategies(), "result": None,
    })


@router.post("/backtest/run", response_class=HTMLResponse)
def run_backtest(
    request: Request,
    code: str = Form(...),
    strategy: str = Form(...),
    start: str = Form(...),
    end: str = Form(...),
):
    result = run(get_datasource(), code=code, strategy=strategy, start=start, end=end)
    return templates.TemplateResponse(request, "backtest.html", {
        "strategies": list_strategies(), "result": result,
        "code": code, "strategy": strategy, "start": start, "end": end,
    })
