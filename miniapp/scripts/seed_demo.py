"""为截图/E2E 准备一组可复现的演示数据（MySQL 版）。

前置：后端已启动；MySQL 已创建库并配置好 MYSQL_*。
用法：
  ../backend/.venv/bin/python scripts/seed_demo.py --reset
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pymysql
from pymysql.cursors import DictCursor

ROOT = Path(__file__).resolve().parent.parent
API = os.environ.get("API_BASE", "http://127.0.0.1:8000")
CLIENT = os.environ.get("DEMO_CLIENT", "demo_client")
OUT = ROOT / ".demo-seed.json"

MYSQL = {
    "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("MYSQL_PORT", "3307")),
    "user": os.environ.get("MYSQL_USER", "lwa"),
    "password": os.environ.get("MYSQL_PASSWORD", "lwa_dev_password"),
    "database": os.environ.get("MYSQL_DATABASE", "lwa_dev"),
    "charset": "utf8mb4",
    "cursorclass": DictCursor,
}

HEADERS: Dict[str, str] = {"X-Client-Id": CLIENT}
TOKEN = ""


def db():
    return pymysql.connect(**MYSQL)


def api_post(path: str, body: Any | None = None) -> Dict[str, Any]:
    res = httpx.post(API + path, json=body if body is not None else {}, headers=HEADERS, timeout=60)
    res.raise_for_status()
    return res.json()


def api_get(path: str):
    return httpx.get(API + path, headers=HEADERS, timeout=60)


def login() -> None:
    global TOKEN
    data = api_post("/api/v1/auth/dev", {})
    TOKEN = data["token"]
    HEADERS["Authorization"] = f"Bearer {TOKEN}"
    print(f"已登录体验账号：{data['user']['nickname']} ({data['user']['id']})")


def reset() -> None:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM sessions WHERE client_id = %s", (CLIENT,))
            ids = [row["id"] for row in cur.fetchall()]
            for sid in ids:
                cur.execute("DELETE FROM answers WHERE session_id = %s", (sid,))
                cur.execute("DELETE FROM reports WHERE session_id = %s", (sid,))
                cur.execute("DELETE FROM questions WHERE session_id = %s", (sid,))
            cur.execute("DELETE FROM chapters WHERE client_id = %s", (CLIENT,))
            cur.execute("DELETE FROM sessions WHERE client_id = %s", (CLIENT,))
            cur.execute("DELETE FROM guest_trials WHERE client_id = %s", (CLIENT,))
        conn.commit()


def wait_ready(session_id: str, timeout: float = 120.0) -> Dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = api_get(f"/api/v1/sessions/{session_id}")
        if res.status_code == 200:
            detail = res.json()
            if detail["status"] == "ready":
                return detail
            if detail["status"] == "failed":
                raise RuntimeError(detail.get("error") or "生成失败")
        time.sleep(0.4)
    raise TimeoutError("等待题目生成超时")


def wait_report(session_id: str, timeout: float = 150.0) -> Dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = api_get(f"/api/v1/sessions/{session_id}/report")
        if res.status_code == 200:
            return res.json()
        time.sleep(0.4)
    raise TimeoutError("等待报告超时")


def correct_answers(session_id: str) -> List[Dict[str, Any]]:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM questions WHERE session_id = %s ORDER BY seq", (session_id,)
            )
            rows = cur.fetchall()
    answers = []
    for row in rows:
        correct = json.loads(row["correct_answer"] or '""')
        if row["type"] == "short_answer":
            rubric = json.loads(row["rubric"] or "[]")
            answer = "；".join(rubric or correct)
        else:
            answer = correct
        answers.append({"question_id": row["id"], "answer": answer})
    return answers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="先删除该 demo client 的旧数据")
    args = parser.parse_args()

    if args.reset:
        reset()
        print(f"已清理 demo client={CLIENT} 的旧数据")
    login()

    completed = api_post(
        "/api/v1/sessions",
        {"topic": "HTTP 缓存机制：强缓存与协商缓存", "level": "advanced", "question_count": 5},
    )
    wait_ready(completed["id"])
    api_post(
        f"/api/v1/sessions/{completed['id']}/answers",
        {"answers": correct_answers(completed["id"])},
    )
    report = wait_report(completed["id"])

    ready = api_post(
        "/api/v1/sessions",
        {"topic": "React Hooks 的 useEffect 依赖数组", "level": "basic", "question_count": 5},
    )
    wait_ready(ready["id"])
    res = httpx.patch(
        API + f"/api/v1/sessions/{ready['id']}/progress",
        json={"current_seq": 3},
        headers=HEADERS,
        timeout=30,
    )
    res.raise_for_status()

    payload = {
        "client_id": CLIENT,
        "token": TOKEN,
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
