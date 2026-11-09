"""FastAPI 入口：`uvicorn app.main:app --reload`。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db
from .api.routes import router
from .config import get_settings
from .llm import close_llm
from .search import close_search

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db.init_db()
    logger.info(
        "服务启动 env=%s mode=%s model=%s search=%s",
        settings.env,
        settings.mode,
        settings.deepseek_model,
        settings.enable_web_search and not settings.is_mock,
    )
    if settings.is_mock:
        logger.warning("当前为 Mock 模式（未配置 DEEPSEEK_API_KEY），AI 结果为演示数据")
    yield
    await close_llm()
    await close_search()


settings = get_settings()
app = FastAPI(
    title="AI 出题学习助手 API",
    description="输入想学的内容 → AI 联网检索并出题 → 答题 → 生成学习分析报告",
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.cors_origins == "*" else [o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常 path=%s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务开小差了，请稍后重试"})


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "name": "learn-with-ai",
        "version": settings.app_version,
        "mode": settings.mode,
        "docs": "/docs",
        "health": "/api/v1/health",
    }
