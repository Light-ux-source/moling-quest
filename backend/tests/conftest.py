"""pytest 公共夹具：独立 MySQL 测试库、独立 LLM/Search 单例、清空限流桶。"""

from __future__ import annotations

import os

os.environ.setdefault("ENV", "test")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("ENABLE_WEB_SEARCH", "true")
os.environ.setdefault("RATE_LIMIT_PER_HOUR", "1000")
os.environ.setdefault("GUEST_TRIAL_LIMIT", "1000")
os.environ.setdefault("QUOTA_ENFORCED", "false")
os.environ.setdefault("DAILY_QUOTA_USER", "1000")
os.environ.setdefault("DEV_LOGIN_ENABLED", "true")
os.environ.setdefault("WECHAT_APP_ID", "test_appid")
os.environ.setdefault("WECHAT_APP_SECRET", "test_secret")

# MySQL 测试库：与开发库隔离；可用 MYSQL_* 环境变量覆盖。
os.environ.setdefault("MYSQL_HOST", "127.0.0.1")
os.environ.setdefault("MYSQL_PORT", "3307")
os.environ.setdefault("MYSQL_USER", "lwa")
os.environ.setdefault("MYSQL_PASSWORD", "lwa_dev_password")
os.environ.setdefault("MYSQL_DATABASE", "lwa_test")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app import db, llm, search  # noqa: E402
from app.api import routes  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    monkeypatch.setenv("MYSQL_DATABASE", os.environ["MYSQL_DATABASE"])
    monkeypatch.setenv("GUEST_TRIAL_LIMIT", os.environ["GUEST_TRIAL_LIMIT"])
    monkeypatch.setenv("QUOTA_ENFORCED", os.environ.get("QUOTA_ENFORCED", "false"))
    monkeypatch.setenv("DAILY_QUOTA_USER", os.environ["DAILY_QUOTA_USER"])
    get_settings.cache_clear()
    db._initialized = False
    llm._llm = None
    search._search = None
    routes._rate.clear()
    if hasattr(routes, "_login_rate"):
        routes._login_rate.clear()
    db.init_db()
    db.truncate_all()
    yield
    db.truncate_all()
    get_settings.cache_clear()
    db._initialized = False
    llm._llm = None
    search._search = None
    routes._rate.clear()
    if hasattr(routes, "_login_rate"):
        routes._login_rate.clear()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c