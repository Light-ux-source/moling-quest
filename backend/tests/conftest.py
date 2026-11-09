"""pytest 公共夹具：每个测试独立 SQLite、独立 LLM/Search 单例、清空限流桶。"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("ENABLE_WEB_SEARCH", "true")
os.environ.setdefault("RATE_LIMIT_PER_HOUR", "500")
# 必须在导入 app 之前指定一个干净的数据库，避免命中开发库
os.environ.setdefault(
    "SQLITE_PATH", os.path.join(tempfile.mkdtemp(prefix="lwa-conftest-"), "test.db")
)

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app import db, llm, search  # noqa: E402
from app.api import routes  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "test.db"))
    get_settings.cache_clear()
    db._initialized = False
    llm._llm = None
    search._search = None
    routes._rate.clear()
    db.init_db()
    yield
    get_settings.cache_clear()
    db._initialized = False
    llm._llm = None
    search._search = None
    routes._rate.clear()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c