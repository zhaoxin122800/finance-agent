"""研报提炼路由。

GET  /report                  页面(历史 + 提炼表单)
POST /report/api/extract      文本提炼
POST /report/api/extract_url  URL 提炼
POST /report/api/extract_pdf  PDF 上传提炼
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT
from app.services.report import extract_and_save, list_history

router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@router.get("/report", response_class=HTMLResponse)
def page(request: Request):
    return templates.TemplateResponse(request, "report.html", {"result": None, "history": list_history()})


@router.post("/report/api/extract", response_class=HTMLResponse)
def extract_text(request: Request, text: str = Form("")):
    result = extract_and_save(text=text) if text and text.strip() else {"error": "请输入研报文本"}
    return templates.TemplateResponse(request, "report.html", {"result": result, "history": list_history()})


@router.post("/report/api/extract_url", response_class=HTMLResponse)
def extract_url(request: Request, url: str = Form(...)):
    result = extract_and_save(url=url)
    return templates.TemplateResponse(request, "report.html", {"result": result, "history": list_history()})


@router.post("/report/api/extract_pdf", response_class=HTMLResponse)
async def extract_pdf(request: Request, file: UploadFile = Form(...)):
    tmp = Path(tempfile.mkdtemp()) / (file.filename or "upload.pdf")
    tmp.write_bytes(await file.read())
    result = extract_and_save(pdf_path=str(tmp))
    return templates.TemplateResponse(request, "report.html", {"result": result, "history": list_history()})
