"""政策监控路由。

GET /policy  政策日报 + 新闻列表(含板块关联)
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT
from app.services import policy

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@router.get("/policy", response_class=HTMLResponse)
def page(request: Request):
    news = policy.search_news(enrich=True)
    brief = policy.daily_brief()
    return templates.TemplateResponse(request, "policy.html", {"news": news, "brief": brief})
