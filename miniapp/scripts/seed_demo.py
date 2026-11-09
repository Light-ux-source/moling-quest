"""为截图/E2E 准备一组可复现的演示数据。

前置：后端已启动（Mock 或真实 Key 均可），并知道其 SQLite 路径。
用法：
  SQLITE_PATH=../backend/data/app.db ../backend/.venv/bin/python scripts/seed_demo.py --reset
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
API = os.environ.get("API_BASE", "http://127.0.0.1:8000")
DB = os.environ.get("SQLITE_PATH", str(ROOT.parent / "backend" / "data" / "app.db"))
CLIENT = os.environ.get("DEMO_CLIENT", "demo_client")
HEADERS = {"X-Client-Id": CLIENT}
OUT = ROOT / ".demo-seed.json"


def api_post(path: str, body=None):
    res = httpx.post(API + path, json=body or {}, headers=HEADERS, timeout=30)
    res.raise_for_status()
    return res.json()


def api_get(path: str):
    return httpx.get(API + path, headers=HEADERS, timeout=30)


def reset(client_id: str) -> None:
    conn = sqlite3.connect(DB)
    try:
        ids = [row[0] for row in conn.execute("SELECT id FROM sessions WHERE client_id = ?", (client_id,))]
        for sid in ids:
            conn.execute("DELETE FROM answers WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM reports WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM questions WHERE session_id = ?", (sid,))
        conn.execute("DELETE FROM chapters WHERE client_id = ?", (client_id,))
        conn.execute("DELETE FROM sessions WHERE client_id = ?", (client_id,))
        conn.commit()
    finally:
        conn.close()


def wait_ready(session_id: str, timeout: float = 90.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = api_get(f"/api/v1/sessions/{session_id}")
        if res.status_code == 200:
            detail = res.json()
            if detail["status"] == "ready":
                return detail
            if detail["status"] == "failed":
                raise RuntimeError(detail.get("error") or "生成失败")
        time.sleep(0.3)
    raise TimeoutError("等待题目生成超时")


def wait_report(session_id: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = api_get(f"/api/v1/sessions/{session_id}/report")
        if res.status_code == 200:
            return res.json()
        time.sleep(0.3)
    raise TimeoutError("等待报告超时")


def correct_answers(session_id: str) -> list:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM questions WHERE session_id = ? ORDER BY seq", (session_id,)
        ).fetchall()
    finally:
        conn.close()
    answers = []
    for row in rows:
        correct = json.loads(row["correct_answer"])
        if row["type"] == "short_answer":
            rubric = json.loads(row["rubric"])
            answer = "；".join(rubric or correct)
        else:
            answer = correct
        answers.append({"question_id": row["id"], "answer": answer})
    return answers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="先删除该 demo client 的旧数据")
    args = parser.parse_args()

    if not Path(DB).exists():
        print(f"数据库不存在：{DB}", file=sys.stderr)
        return 1
    if args.reset:
        reset(CLIENT)
        print(f"已清理 demo client={CLIENT} 的旧数据")

    completed = api_post(
        "/api/v1/sessions",
        {"topic": "HTTP 缓存机制：强缓存与协商缓存", "level": "advanced", "question_count": 5},
    )
    wait_ready(completed["id"])
    api_post(f"/api/v1/sessions/{completed['id']}/answers", {"answers": correct_answers(completed["id"])})
    report = wait_report(completed["id"])

    ready = api_post(
        "/api/v1/sessions",
        {"topic": "React Hooks 的 useEffect 依赖数组", "level": "basic", "question_count": 5},
    )
    wait_ready(ready["id"])
    httpx.patch(
        API + f"/api/v1/sessions/{ready['id']}/progress",
        json={"current_seq": 3},
        headers=HEADERS,
        timeout=30,
    ).raise_for_status()

    payload = {
        "client_id": CLIENT,
        "completed_session": completed["id"],
        "completed_chapter": completed["chapter_id"],
        "ready_session": ready["id"],
        "ready_chapter": ready["chapter_id"],
        "score": report["score"],
        "stars": report["settlement"]["stars"],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    print(f"写入 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())