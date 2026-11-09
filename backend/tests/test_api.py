import os
import tempfile

os.environ["LLM_PROVIDER"] = "mock"
os.environ["ENABLE_WEB_SEARCH"] = "true"
os.environ["RATE_LIMIT_PER_HOUR"] = "500"
os.environ["SQLITE_PATH"] = os.path.join(tempfile.mkdtemp(prefix="lwa-test-"), "test.db")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    db.init_db()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health(client):
    res = await client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["mode"] == "mock"


@pytest.mark.asyncio
async def test_core_flow(client):
    created = await client.post(
        "/api/v1/sessions",
        json={"topic": "React Hooks 的 useEffect 依赖数组", "level": "basic", "question_count": 5},
    )
    assert created.status_code == 202, created.text
    session = created.json()
    session_id = session["id"]
    assert session["status"] in {"queued", "searching", "digesting", "generating", "ready"}

    res = await client.get(f"/api/v1/sessions/{session_id}")
    assert res.status_code == 200
    detail = res.json()
    assert detail["status"] == "ready", detail
    assert len(detail["questions"]) == 5
    assert len(detail["sources"]) >= 1
    # 答案不能提前下发
    assert "correct_answer" not in detail["questions"][0]
    assert "explanation" not in detail["questions"][0]

    question_ids = [q["id"] for q in detail["questions"]]
    answers = []
    for i, q in enumerate(detail["questions"]):
        if q["type"] == "multiple_choice":
            answer = ["A", "B", "D"]
        elif q["type"] == "short_answer":
            answer = "核心定义是……，机制分为三步，典型场景是……"
        else:
            answer = "A"
        answers.append({"question_id": q["id"], "answer": answer})

    submitted = await client.post(
        f"/api/v1/sessions/{session_id}/answers", json={"answers": answers}
    )
    assert submitted.status_code == 202, submitted.text

    report_res = await client.get(f"/api/v1/sessions/{session_id}/report")
    assert report_res.status_code == 200, report_res.text
    report = report_res.json()
    assert report["total"] == 5
    assert len(report["items"]) == 5
    assert 0 <= report["score"] <= 100
    assert report["summary"]
    assert report["next_steps"]
    assert [i["question_id"] for i in report["items"]] == question_ids
    assert report["usage"]["tokens_in"] >= 0

    # 重复提交被拒绝
    again = await client.post(f"/api/v1/sessions/{session_id}/answers", json={"answers": answers})
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_validation_errors(client):
    bad = await client.post("/api/v1/sessions", json={"topic": "a", "question_count": 5})
    assert bad.status_code == 422

    missing = await client.get("/api/v1/sessions/s_not_exist")
    assert missing.status_code == 404

    created = await client.post(
        "/api/v1/sessions",
        json={"topic": "细胞呼吸", "level": "advanced", "question_count": 3},
    )
    session_id = created.json()["id"]
    detail = (await client.get(f"/api/v1/sessions/{session_id}")).json()

    unknown = await client.post(
        f"/api/v1/sessions/{session_id}/answers",
        json={"answers": [{"question_id": "q_fake", "answer": "A"}]},
    )
    assert unknown.status_code == 400

    # 未作答也能出报告（按 0 分计）
    partial = await client.post(
        f"/api/v1/sessions/{session_id}/answers",
        json={"answers": [{"question_id": detail["questions"][0]["id"], "answer": ""}]},
    )
    assert partial.status_code == 202
    report = (await client.get(f"/api/v1/sessions/{session_id}/report")).json()
    assert report["total"] == 3
    assert report["correct"] <= 1