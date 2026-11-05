"""FastAPI 入口.

运行：uv run python -m app.main
"""
from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import DATA_DIR, PROJECT_ROOT, get_settings
from app.routes.pages import router as pages_router
from app.services.account_seed import ensure_sim_account

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("finance-agent")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Finance Agent", version="0.1.0")

    app.mount(
        "/static",
        StaticFiles(directory=str(PROJECT_ROOT / "app" / "static")),
        name="static",
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 启动时确保账户种子存在
    ensure_sim_account(DATA_DIR / "sim_account.json")

    # 具体路由先注册(避免 pages 的 GET /{page} 兜底吞掉 /analyst /watchlist)
    from app.routes.watchlist import router as watchlist_router
    from app.routes.analyst import router as analyst_router
    from app.routes.review import router as review_router
    from app.routes.account import router as account_router
    from app.routes.policy import router as policy_router
    from app.routes.report import router as report_router
    from app.routes.backtest import router as backtest_router
    from app.routes.risk import router as risk_router
    app.include_router(watchlist_router)
    app.include_router(analyst_router)
    app.include_router(review_router)
    app.include_router(account_router)
    app.include_router(policy_router)
    app.include_router(report_router)
    app.include_router(backtest_router)
    app.include_router(risk_router)
    app.include_router(pages_router)
    return app


app = create_app()


def main():
    settings = get_settings()
    log.info("启动 Finance Agent → http://%s:%d", settings.host, settings.port)
    log.info("AI 解读: %s", "已启用" if settings.ai_enabled else "未启用（缺少 LLM_API_KEY）")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
