"""FastAPI 入口：`uvicorn app.main:app --reload`。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .api.routes import router
from .config import get_settings
from .llm import close_llm
from .rag.embeddings import close_embeddings
from .rag.vector_store import close_vector_store
from .search import close_search
from .services.auth import clear_expired_deletions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db.init_db()
    clear_expired_deletions()
    Path(settings.avatar_upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.kb_upload_dir).mkdir(parents=True, exist_ok=True)
    logger.info(
        "服务启动 env=%s mode=%s model=%s search=%s provider=%s db=%s "
        "embedding=%s rag=%s wechat_login=%s dev_login=%s",
        settings.env,
        settings.mode,
        settings.deepseek_model,
        settings.web_search_available,
        settings.effective_search_provider,
        settings.mysql_dsn_safe,
        settings.effective_embedding_provider,
        settings.rag_available,
        settings.wechat_login_configured,
        settings.dev_login_allowed,
    )
    if settings.is_mock:
        logger.warning("当前为 Mock 模式（未配置 DEEPSEEK_API_KEY），AI 结果为演示数据")
    elif "v4.1-flash" not in settings.deepseek_model.lower():
        logger.warning(
            "当前真实模型 %s 不是产品要求的 v4.1-flash；请检查 DEEPSEEK_MODEL",
            settings.deepseek_model,
        )
    yield
    await close_llm()
    await close_search()
    await close_embeddings()
    await close_vector_store()


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
Path(settings.avatar_upload_dir).mkdir(parents=True, exist_ok=True)
app.mount("/media/avatars", StaticFiles(directory=settings.avatar_upload_dir), name="avatars")


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
