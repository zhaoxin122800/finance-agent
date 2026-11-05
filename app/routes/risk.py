"""风险预警路由。

GET /risk  扫描自选股规则触发,显示预警看板
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT
from app.datasources import get_datasource
from app.services.risk import scan

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@router.get("/risk", response_class=HTMLResponse)
def page(request: Request):
    alerts = scan(get_datasource())
    return templates.TemplateResponse(request, "risk.html", {"alerts": alerts})
