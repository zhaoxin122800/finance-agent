"""8 个功能页的占位路由(M1 只渲染空壳,M2-M4 填充内容)。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT, get_settings

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))

PLACEHOLDER_PAGES: dict[str, str] = {}


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    from app.services.market import cls_telegraph, northbound_flow
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "ai_enabled": get_settings().ai_enabled,
            "northbound": northbound_flow(),
            "telegraphs": cls_telegraph(limit=10),
        },
    )


@router.get("/{page}", response_class=HTMLResponse)
def placeholder(page: str, request: Request):
    if page not in PLACEHOLDER_PAGES:
        raise HTTPException(status_code=404)
    title = PLACEHOLDER_PAGES[page]
    return templates.TemplateResponse(
        request,
        "_placeholder.html",
        {"title": title, "page": page},
    )
