"""SQLite 持久层。

MVP 用 SQLite 单文件（零运维、可随代码备份），通过仓储函数隔离 SQL，
后续切换 PostgreSQL 只需替换本文件实现，业务层不感知。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .config import get_settings

_lock = threading.Lock()
_initialized = False

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS sessions (
  id              TEXT PRIMARY KEY,
  topic           TEXT NOT NULL,
  level           TEXT NOT NULL DEFAULT 'basic',
  requested_types TEXT NOT NULL DEFAULT '[]',
  question_count  INTEGER NOT NULL DEFAULT 5,
  status          TEXT NOT NULL,
  stage           TEXT,
  progress        INTEGER NOT NULL DEFAULT 0,
  error           TEXT,
  knowledge_brief TEXT,
  sources         TEXT,
  model           TEXT,
  tokens_in       INTEGER NOT NULL DEFAULT 0,
  tokens_out      INTEGER NOT NULL DEFAULT 0,
  cost_cny        REAL NOT NULL DEFAULT 0,
  submitted_at    TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
  id             TEXT PRIMARY KEY,
  session_id     TEXT NOT NULL,
  seq            INTEGER NOT NULL,
  type           TEXT NOT NULL,
  stem           TEXT NOT NULL,
  options        TEXT NOT NULL DEFAULT '[]',
  correct_answer TEXT NOT NULL DEFAULT '""',
  explanation    TEXT NOT NULL DEFAULT '',
  difficulty     TEXT NOT NULL DEFAULT 'medium',
  rubric         TEXT NOT NULL DEFAULT '[]',
  source_refs    TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_questions_session ON questions(session_id, seq);
CREATE TABLE IF NOT EXISTS answers (
  id          TEXT PRIMARY KEY,
  session_id  TEXT NOT NULL,
  question_id TEXT NOT NULL,
  seq         INTEGER NOT NULL,
  user_answer TEXT NOT NULL DEFAULT '""',
  is_correct  INTEGER NOT NULL DEFAULT 0,
  score       REAL NOT NULL DEFAULT 0,
  feedback    TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL,
  UNIQUE(session_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_answers_session ON answers(session_id, seq);
CREATE TABLE IF NOT EXISTS reports (
  id         TEXT PRIMARY KEY,
  session_id TEXT NOT NULL UNIQUE,
  payload    TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _db_path() -> str:
    path = get_settings().sqlite_path
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


def init_db() -> None:
    global _initialized
    with _lock:
        if _initialized:
            return
        with sqlite3.connect(_db_path(), timeout=15) as conn:
            conn.executescript(SCHEMA)
        _initialized = True


@contextmanager
def connect():
    init_db()
    conn = sqlite3.connect(_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=15000")
        yield conn
        conn.commit()
    finally:
        conn.close()


def _loads(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# sessions
# --------------------------------------------------------------------------- #
def create_session(row: Dict[str, Any]) -> None:
    ts = now_iso()
    with connect() as conn:
        conn.execute(
            """INSERT INTO sessions
               (id, topic, level, requested_types, question_count, status, stage, progress,
                error, knowledge_brief, sources, model, tokens_in, tokens_out, cost_cny,
                submitted_at, created_at, updated_at)
               VALUES (:id, :topic, :level, :requested_types, :question_count, :status, :stage,
                       :progress, :error, :knowledge_brief, :sources, :model, 0, 0, 0, NULL, :created_at, :updated_at)""",
            {
                "id": row["id"],
                "topic": row["topic"],
                "level": row.get("level", "basic"),
                "requested_types": json.dumps(row.get("requested_types", []), ensure_ascii=False),
                "question_count": row.get("question_count", 5),
                "status": row.get("status", "queued"),
                "stage": row.get("stage", "queued"),
                "progress": row.get("progress", 0),
                "error": None,
                "knowledge_brief": None,
                "sources": None,
                "model": row.get("model"),
                "created_at": ts,
                "updated_at": ts,
            },
        )


def update_session(session_id: str, **fields: Any) -> None:
    allowed = {
        "status", "stage", "progress", "error", "knowledge_brief", "sources",
        "model", "tokens_in", "tokens_out", "cost_cny", "submitted_at",
    }
    payload = {k: v for k, v in fields.items() if k in allowed}
    if "knowledge_brief" in payload and not isinstance(payload["knowledge_brief"], str):
        payload["knowledge_brief"] = json.dumps(payload["knowledge_brief"], ensure_ascii=False)
    if "sources" in payload and not isinstance(payload["sources"], str):
        payload["sources"] = json.dumps(payload["sources"], ensure_ascii=False)
    payload["updated_at"] = now_iso()
    assignments = ", ".join(f"{k} = :{k}" for k in payload)
    payload["id"] = session_id
    with connect() as conn:
        conn.execute(f"UPDATE sessions SET {assignments} WHERE id = :id", payload)


def add_usage(session_id: str, tokens_in: int, tokens_out: int, cost_cny: float) -> None:
    with connect() as conn:
        conn.execute(
            """UPDATE sessions SET tokens_in = tokens_in + ?, tokens_out = tokens_out + ?,
               cost_cny = cost_cny + ?, updated_at = ? WHERE id = ?""",
            (tokens_in, tokens_out, round(cost_cny, 6), now_iso(), session_id),
        )


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["requested_types"] = _loads(data.get("requested_types"), [])
    data["sources"] = _loads(data.get("sources"), [])
    return data


def list_recent_sessions(limit: int = 20) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, topic, level, status, question_count, created_at FROM sessions ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# questions
# --------------------------------------------------------------------------- #
def insert_questions(session_id: str, questions: Iterable[Dict[str, Any]]) -> None:
    with connect() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO questions
               (id, session_id, seq, type, stem, options, correct_answer, explanation,
                difficulty, rubric, source_refs)
               VALUES (:id, :session_id, :seq, :type, :stem, :options, :correct_answer,
                       :explanation, :difficulty, :rubric, :source_refs)""",
            [
                {
                    "id": q["id"],
                    "session_id": session_id,
                    "seq": q["seq"],
                    "type": q["type"],
                    "stem": q["stem"],
                    "options": json.dumps(q.get("options", []), ensure_ascii=False),
                    "correct_answer": json.dumps(q.get("correct_answer"), ensure_ascii=False),
                    "explanation": q.get("explanation", ""),
                    "difficulty": q.get("difficulty", "medium"),
                    "rubric": json.dumps(q.get("rubric", []), ensure_ascii=False),
                    "source_refs": json.dumps(q.get("source_refs", []), ensure_ascii=False),
                }
                for q in questions
            ],
        )


def list_questions(session_id: str) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM questions WHERE session_id = ? ORDER BY seq ASC", (session_id,)
        ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["options"] = _loads(item.get("options"), [])
        item["correct_answer"] = _loads(item.get("correct_answer"), "")
        item["rubric"] = _loads(item.get("rubric"), [])
        item["source_refs"] = _loads(item.get("source_refs"), [])
        out.append(item)
    return out


# --------------------------------------------------------------------------- #
# answers
# --------------------------------------------------------------------------- #
def upsert_answers(session_id: str, answers: Iterable[Dict[str, Any]]) -> None:
    ts = now_iso()
    with connect() as conn:
        conn.executemany(
            """INSERT INTO answers
               (id, session_id, question_id, seq, user_answer, is_correct, score, feedback, created_at)
               VALUES (:id, :session_id, :question_id, :seq, :user_answer, :is_correct, :score,
                       :feedback, :created_at)
               ON CONFLICT(session_id, question_id) DO UPDATE SET
                 user_answer = excluded.user_answer,
                 is_correct  = excluded.is_correct,
                 score       = excluded.score,
                 feedback    = excluded.feedback""",
            [
                {
                    "id": a["id"],
                    "session_id": session_id,
                    "question_id": a["question_id"],
                    "seq": a["seq"],
                    "user_answer": json.dumps(a.get("user_answer"), ensure_ascii=False),
                    "is_correct": 1 if a.get("is_correct") else 0,
                    "score": float(a.get("score", 0)),
                    "feedback": a.get("feedback", ""),
                    "created_at": ts,
                }
                for a in answers
            ],
        )


def list_answers(session_id: str) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM answers WHERE session_id = ? ORDER BY seq ASC", (session_id,)
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["user_answer"] = _loads(item.get("user_answer"), "")
        out.append(item)
    return out


# --------------------------------------------------------------------------- #
# reports
# --------------------------------------------------------------------------- #
def save_report(session_id: str, payload: Dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO reports (id, session_id, payload, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET payload = excluded.payload""",
            (
                f"rep_{session_id}",
                session_id,
                json.dumps(payload, ensure_ascii=False),
                now_iso(),
            ),
        )


def get_report(session_id: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT payload FROM reports WHERE session_id = ?", (session_id,)).fetchone()
    if not row:
        return None
    return _loads(row["payload"], None)