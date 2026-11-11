"""测试辅助：登录、创建会话、作答。"""

from __future__ import annotations

from typing import Optional, Tuple

from app import db

BASE = "/api/v1"


def headers(client_id: str, token: Optional[str] = None) -> dict:
    data = {"X-Client-Id": client_id}
    if token:
        data["Authorization"] = f"Bearer {token}"
    return data


async def dev_login(client, client_id: str, nickname: Optional[str] = None) -> Tuple[str, dict]:
    res = await client.post(
        f"{BASE}/auth/dev",
        json={"nickname": nickname} if nickname else {},
        headers=headers(client_id),
    )
    assert res.status_code == 200, res.text
    data = res.json()
    return data["token"], data["user"]


async def create_ready(
    client,
    client_id: str,
    token: Optional[str] = None,
    topic: str = "HTTP 缓存机制",
    count: int = 5,
    kind: str = "standard",
):
    res = await client.post(
        f"{BASE}/sessions",
        json={"topic": topic, "level": "basic", "question_count": count, "kind": kind},
        headers=headers(client_id, token),
    )
    assert res.status_code == 202, res.text
    created = res.json()
    detail = (
        await client.get(f"{BASE}/sessions/{created['id']}", headers=headers(client_id, token))
    ).json()
    assert detail["status"] == "ready", detail
    return created, detail


async def submit_correct(client, client_id: str, session_id: str, token: Optional[str] = None):
    questions = db.list_questions(session_id)
    answers = []
    for q in questions:
        answer = q["correct_answer"]
        if q["type"] == "short_answer":
            answer = "；".join(q.get("rubric") or q["correct_answer"])
        answers.append({"question_id": q["id"], "answer": answer})
    res = await client.post(
        f"{BASE}/sessions/{session_id}/answers",
        json={"answers": answers},
        headers=headers(client_id, token),
    )
    assert res.status_code == 202, res.text
    return answers