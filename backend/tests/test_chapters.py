"""章节地图、进度、结算与章末综合的 API 测试。"""

from __future__ import annotations

import pytest

from app import db

BASE = "/api/v1"


def headers(client_id: str) -> dict:
    return {"X-Client-Id": client_id}


async def create_ready(client, client_id: str, topic: str = "HTTP 缓存机制", count: int = 5):
    res = await client.post(
        f"{BASE}/sessions",
        json={"topic": topic, "level": "basic", "question_count": count},
        headers=headers(client_id),
    )
    assert res.status_code == 202, res.text
    created = res.json()
    detail = (await client.get(f"{BASE}/sessions/{created['id']}", headers=headers(client_id))).json()
    assert detail["status"] == "ready", detail
    return created, detail


async def submit_correct(client, client_id: str, session_id: str):
    questions = db.list_questions(session_id)
    answers = []
    for q in questions:
        answer = q["correct_answer"]
        if q["type"] == "short_answer":
            # 用 rubric 原文作答，保证 Mock 判分能命中全部要点
            answer = "；".join(q.get("rubric") or q["correct_answer"])
        answers.append({"question_id": q["id"], "answer": answer})
    res = await client.post(
        f"{BASE}/sessions/{session_id}/answers",
        json={"answers": answers},
        headers=headers(client_id),
    )
    assert res.status_code == 202, res.text
    return answers


@pytest.mark.asyncio
async def test_create_session_creates_chapter_with_six_nodes(client):
    created, detail = await create_ready(client, "c_chapter_1")
    assert created["chapter_id"].startswith("c_")
    assert detail["chapter_id"] == created["chapter_id"]
    assert detail["current_seq"] == 1
    assert len(detail["questions"]) == 5
    assert detail["questions"][0]["title"]

    res = await client.get(f"{BASE}/chapters/{created['chapter_id']}", headers=headers("c_chapter_1"))
    assert res.status_code == 200, res.text
    chapter = res.json()
    assert chapter["status"] == "ready"
    assert chapter["title"] == "HTTP 缓存机制"
    assert len(chapter["nodes"]) == 6
    assert chapter["nodes"][0]["status"] == "current"
    assert chapter["nodes"][1]["status"] == "locked"
    assert chapter["nodes"][-1]["kind"] == "comprehensive"
    assert chapter["nodes"][-1]["status"] == "locked"
    assert chapter["progress"] == {"done": 0, "total": 6}


@pytest.mark.asyncio
async def test_chapter_list_is_scoped_by_client(client):
    await create_ready(client, "c_scope_a", "主题 A")
    await create_ready(client, "c_scope_b", "主题 B")

    a = (await client.get(f"{BASE}/chapters", headers=headers("c_scope_a"))).json()["items"]
    b = (await client.get(f"{BASE}/chapters", headers=headers("c_scope_b"))).json()["items"]
    assert [c["topic"] for c in a] == ["主题 A"]
    assert [c["topic"] for c in b] == ["主题 B"]


@pytest.mark.asyncio
async def test_progress_patch_updates_map_and_session(client):
    created, _ = await create_ready(client, "c_progress")
    sid = created["id"]

    res = await client.patch(
        f"{BASE}/sessions/{sid}/progress",
        json={"current_seq": 3},
        headers=headers("c_progress"),
    )
    assert res.status_code == 200, res.text
    assert res.json()["current_seq"] == 3

    detail = (await client.get(f"{BASE}/sessions/{sid}", headers=headers("c_progress"))).json()
    assert detail["current_seq"] == 3

    chapter = (
        await client.get(f"{BASE}/chapters/{created['chapter_id']}", headers=headers("c_progress"))
    ).json()
    assert chapter["nodes"][0]["status"] == "done"
    assert chapter["nodes"][1]["status"] == "done"
    assert chapter["nodes"][2]["status"] == "current"
    assert chapter["nodes"][3]["status"] == "locked"
    assert chapter["progress"] == {"done": 2, "total": 6}

    bad = await client.patch(
        f"{BASE}/sessions/{sid}/progress",
        json={"current_seq": 99},
        headers=headers("c_progress"),
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_settlement_computes_stars_exp_and_report(client):
    created, _ = await create_ready(client, "c_settle")
    sid = created["id"]
    await submit_correct(client, "c_settle", sid)

    res = await client.get(f"{BASE}/sessions/{sid}/settlement", headers=headers("c_settle"))
    assert res.status_code == 200, res.text
    settlement = res.json()
    assert settlement["stars"] == 3
    assert settlement["accuracy"] == 1.0
    assert settlement["correct"] == 5
    assert settlement["total"] == 5
    assert settlement["exp"] == 160
    assert settlement["combo"] == 5
    assert settlement["wrong_count"] == 0
    assert settlement["level_up"] is True

    report = (await client.get(f"{BASE}/sessions/{sid}/report", headers=headers("c_settle"))).json()
    assert report["settlement"]["stars"] == 3
    assert report["settlement"]["exp"] == 160

    chapter = (
        await client.get(f"{BASE}/chapters/{created['chapter_id']}", headers=headers("c_settle"))
    ).json()
    assert chapter["status"] == "completed"
    assert chapter["stars"] == 3
    assert chapter["progress"] == {"done": 5, "total": 6}
    assert chapter["nodes"][0]["status"] == "done"
    assert chapter["nodes"][-1]["status"] == "unlocked"

    profile = (await client.get(f"{BASE}/profile", headers=headers("c_settle"))).json()
    assert profile["chapters_completed"] == 1
    assert profile["total_stars"] == 3
    assert profile["total_exp"] == 160
    assert profile["rank"]["key"] == "S2"


@pytest.mark.asyncio
async def test_settlement_409_before_completion(client):
    created, _ = await create_ready(client, "c_settle_409")
    res = await client.get(
        f"{BASE}/sessions/{created['id']}/settlement", headers=headers("c_settle_409")
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_comprehensive_locked_until_all_nodes_three_stars(client):
    created, _ = await create_ready(client, "c_comp_locked")
    sid = created["id"]
    questions = db.list_questions(sid)
    wrong_answers = []
    for q in questions:
        if q["type"] == "multiple_choice":
            answer = ["A"]
        elif q["type"] == "short_answer":
            answer = "不知道"
        else:
            answer = "Z"
        wrong_answers.append({"question_id": q["id"], "answer": answer})
    await client.post(
        f"{BASE}/sessions/{sid}/answers",
        json={"answers": wrong_answers},
        headers=headers("c_comp_locked"),
    )
    chapter = (
        await client.get(
            f"{BASE}/chapters/{created['chapter_id']}", headers=headers("c_comp_locked")
        )
    ).json()
    assert chapter["stars"] < 3
    assert chapter["nodes"][-1]["status"] == "locked"
    res = await client.post(
        f"{BASE}/chapters/{created['chapter_id']}/comprehensive",
        headers=headers("c_comp_locked"),
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_comprehensive_creates_three_question_session(client):
    created, _ = await create_ready(client, "c_comp_ok")
    sid = created["id"]
    await submit_correct(client, "c_comp_ok", sid)

    res = await client.post(
        f"{BASE}/chapters/{created['chapter_id']}/comprehensive",
        headers=headers("c_comp_ok"),
    )
    assert res.status_code == 202, res.text
    comp = res.json()
    assert comp["kind"] == "comprehensive"
    assert comp["parent_chapter_id"] == created["chapter_id"]
    detail = (await client.get(f"{BASE}/sessions/{comp['id']}", headers=headers("c_comp_ok"))).json()
    assert len(detail["questions"]) == 3

    chapter = (
        await client.get(f"{BASE}/chapters/{created['chapter_id']}", headers=headers("c_comp_ok"))
    ).json()
    assert chapter["nodes"][-1]["status"] == "current"


@pytest.mark.asyncio
async def test_retry_failed_session(client):
    created, _ = await create_ready(client, "c_retry")
    sid = created["id"]
    db.update_session(sid, status="failed", stage="failed", error="模拟失败")

    res = await client.post(f"{BASE}/sessions/{sid}/retry", headers=headers("c_retry"))
    assert res.status_code == 202, res.text
    detail = (await client.get(f"{BASE}/sessions/{sid}", headers=headers("c_retry"))).json()
    assert detail["status"] == "ready"

    again = await client.post(f"{BASE}/sessions/{sid}/retry", headers=headers("c_retry"))
    assert again.status_code == 409

@pytest.mark.asyncio
async def test_daily_challenge_has_bonus_and_no_comprehensive(client):
    res = await client.post(
        f"{BASE}/sessions",
        json={"topic": "雾林拾遗 · 常见常识", "level": "basic", "question_count": 5, "kind": "daily"},
        headers=headers("c_daily"),
    )
    assert res.status_code == 202, res.text
    created = res.json()
    assert created["kind"] == "daily"
    detail = (await client.get(f"{BASE}/sessions/{created['id']}", headers=headers("c_daily"))).json()
    assert len(detail["questions"]) == 3

    chapter = (
        await client.get(f"{BASE}/chapters/{created['chapter_id']}", headers=headers("c_daily"))
    ).json()
    assert chapter["kind"] == "daily"
    assert len(chapter["nodes"]) == 3
    assert chapter["comprehensive"] is None
    assert chapter["progress"] == {"done": 0, "total": 3}

    await submit_correct(client, "c_daily", created["id"])
    settlement = (
        await client.get(f"{BASE}/sessions/{created['id']}/settlement", headers=headers("c_daily"))
    ).json()
    assert settlement["stars"] == 3
    assert settlement["exp"] == 3 * 20 + 3 * 20 + 30


@pytest.mark.asyncio
async def test_profile_is_scoped_and_quota_is_displayed(client):
    created, _ = await create_ready(client, "c_profile_a", "主题 A")
    await submit_correct(client, "c_profile_a", created["id"])

    a = (await client.get(f"{BASE}/profile", headers=headers("c_profile_a"))).json()
    b = (await client.get(f"{BASE}/profile", headers=headers("c_profile_b"))).json()
    assert a["chapters_completed"] == 1
    assert a["streak_days"] >= 1
    assert a["quota"]["used"] >= 1
    assert a["quota"]["limit"] == 10
    assert b["chapters_completed"] == 0
    assert b["total_stars"] == 0


@pytest.mark.asyncio
async def test_chapter_404_and_progress_after_completion(client):
    missing = await client.get(f"{BASE}/chapters/c_not_exist")
    assert missing.status_code == 404

    created, _ = await create_ready(client, "c_progress_done")
    await submit_correct(client, "c_progress_done", created["id"])
    res = await client.patch(
        f"{BASE}/sessions/{created['id']}/progress",
        json={"current_seq": 2},
        headers=headers("c_progress_done"),
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_settlement_is_idempotent(client):
    created, _ = await create_ready(client, "c_idem")
    await submit_correct(client, "c_idem", created["id"])
    first = (await client.get(f"{BASE}/sessions/{created['id']}/settlement", headers=headers("c_idem"))).json()
    second = (await client.get(f"{BASE}/sessions/{created['id']}/settlement", headers=headers("c_idem"))).json()
    assert first["stars"] == second["stars"] == 3
    assert first["exp"] == second["exp"] == 160


class _BadLLM:
    async def run(self, *args, **kwargs):
        raise RuntimeError("模拟模型故障")


@pytest.mark.asyncio
async def test_generation_failure_marks_failed_then_retry(client, monkeypatch):
    import app.services.question_gen as question_gen
    from app.llm import get_llm as real_get_llm

    monkeypatch.setattr(question_gen, "get_llm", lambda: _BadLLM())
    res = await client.post(
        f"{BASE}/sessions",
        json={"topic": "会失败的生成", "level": "basic", "question_count": 3},
        headers=headers("c_fail"),
    )
    assert res.status_code == 202
    sid = res.json()["id"]
    detail = (await client.get(f"{BASE}/sessions/{sid}", headers=headers("c_fail"))).json()
    assert detail["status"] == "failed"
    assert detail["error"]

    monkeypatch.setattr(question_gen, "get_llm", real_get_llm)
    retry = await client.post(f"{BASE}/sessions/{sid}/retry", headers=headers("c_fail"))
    assert retry.status_code == 202, retry.text
    detail = (await client.get(f"{BASE}/sessions/{sid}", headers=headers("c_fail"))).json()
    assert detail["status"] == "ready"


@pytest.mark.asyncio
async def test_report_falls_back_when_report_llm_fails(client, monkeypatch):
    import app.services.reporting as reporting

    created, _ = await create_ready(client, "c_report_fallback")
    monkeypatch.setattr(reporting, "get_llm", lambda: _BadLLM())
    await submit_correct(client, "c_report_fallback", created["id"])
    res = await client.get(f"{BASE}/sessions/{created['id']}/report", headers=headers("c_report_fallback"))
    assert res.status_code == 200, res.text
    report = res.json()
    assert report["summary"]
    assert report["settlement"]["stars"] == 3
