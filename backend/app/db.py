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
  client_id       TEXT NOT NULL DEFAULT 'anonymous',
  chapter_id      TEXT,
  parent_chapter_id TEXT,
  topic           TEXT NOT NULL,
  level           TEXT NOT NULL DEFAULT 'basic',
  requested_types TEXT NOT NULL DEFAULT '[]',
  question_count  INTEGER NOT NULL DEFAULT 5,
  kind            TEXT NOT NULL DEFAULT 'standard',
  status          TEXT NOT NULL,
  stage           TEXT,
  progress        INTEGER NOT NULL DEFAULT 0,
  current_seq     INTEGER NOT NULL DEFAULT 1,
  stars           INTEGER NOT NULL DEFAULT 0,
  exp             INTEGER NOT NULL DEFAULT 0,
  accuracy        REAL NOT NULL DEFAULT 0,
  combo           INTEGER NOT NULL DEFAULT 0,
  error           TEXT,
  knowledge_brief TEXT,
  sources         TEXT,
  model           TEXT,
  tokens_in       INTEGER NOT NULL DEFAULT 0,
  tokens_out      INTEGER NOT NULL DEFAULT 0,
  cost_cny        REAL NOT NULL DEFAULT 0,
  submitted_at    TEXT,
  completed_at    TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chapters (
  id                TEXT PRIMARY KEY,
  client_id         TEXT NOT NULL DEFAULT 'anonymous',
  session_id        TEXT NOT NULL UNIQUE,
  title             TEXT NOT NULL,
  topic             TEXT NOT NULL,
  level             TEXT NOT NULL DEFAULT 'basic',
  question_count    INTEGER NOT NULL DEFAULT 5,
  kind              TEXT NOT NULL DEFAULT 'standard',
  parent_chapter_id TEXT,
  stars             INTEGER NOT NULL DEFAULT 0,
  accuracy          REAL NOT NULL DEFAULT 0,
  exp               INTEGER NOT NULL DEFAULT 0,
  created_at        TEXT NOT NULL,
  completed_at      TEXT,
  updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chapters_client ON chapters(client_id, created_at);
CREATE TABLE IF NOT EXISTS questions (
  id             TEXT PRIMARY KEY,
  session_id     TEXT NOT NULL,
  seq            INTEGER NOT NULL,
  type           TEXT NOT NULL,
  title          TEXT NOT NULL DEFAULT '',
  knowledge_point TEXT NOT NULL DEFAULT '',
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


def _columns(conn: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _migrate(conn: sqlite3.Connection) -> None:
    """对已有 SQLite 文件做向后兼容的轻量迁移（只加列，不删列）。"""
    # sessions
    _ensure_column(conn, "sessions", "client_id", "TEXT NOT NULL DEFAULT 'anonymous'")
    _ensure_column(conn, "sessions", "chapter_id", "TEXT")
    _ensure_column(conn, "sessions", "parent_chapter_id", "TEXT")
    _ensure_column(conn, "sessions", "kind", "TEXT NOT NULL DEFAULT 'standard'")
    _ensure_column(conn, "sessions", "current_seq", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "sessions", "stars", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "sessions", "exp", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "sessions", "accuracy", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "sessions", "combo", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "sessions", "completed_at", "TEXT")
    # questions
    _ensure_column(conn, "questions", "title", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "questions", "knowledge_point", "TEXT NOT NULL DEFAULT ''")
    # 旧库补索引
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_client ON sessions(client_id, created_at)")


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
            _migrate(conn)
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
               (id, client_id, chapter_id, parent_chapter_id, topic, level, requested_types, question_count, kind,
                status, stage, progress, current_seq, stars, exp, accuracy, combo,
                error, knowledge_brief, sources, model, tokens_in, tokens_out, cost_cny,
                submitted_at, completed_at, created_at, updated_at)
               VALUES (:id, :client_id, :chapter_id, :parent_chapter_id, :topic, :level, :requested_types, :question_count,
                       :kind, :status, :stage, :progress, :current_seq, 0, 0, 0, 0,
                       NULL, NULL, NULL, :model, 0, 0, 0, NULL, NULL, :created_at, :updated_at)""",
            {
                "id": row["id"],
                "client_id": row.get("client_id", "anonymous") or "anonymous",
                "chapter_id": row.get("chapter_id"),
                "parent_chapter_id": row.get("parent_chapter_id"),
                "topic": row["topic"],
                "level": row.get("level", "basic"),
                "requested_types": json.dumps(row.get("requested_types", []), ensure_ascii=False),
                "question_count": row.get("question_count", 5),
                "kind": row.get("kind", "standard"),
                "status": row.get("status", "queued"),
                "stage": row.get("stage", "queued"),
                "progress": row.get("progress", 0),
                "current_seq": row.get("current_seq", 1),
                "model": row.get("model"),
                "created_at": ts,
                "updated_at": ts,
            },
        )


def update_session(session_id: str, **fields: Any) -> None:
    allowed = {
        "status", "stage", "progress", "current_seq", "error", "knowledge_brief", "sources",
        "model", "tokens_in", "tokens_out", "cost_cny", "submitted_at", "completed_at",
        "client_id", "chapter_id", "parent_chapter_id", "kind", "stars", "exp", "accuracy", "combo",
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


def list_recent_sessions(limit: int = 20, client_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with connect() as conn:
        if client_id:
            rows = conn.execute(
                """SELECT id, chapter_id, topic, level, kind, status, progress, current_seq,
                          question_count, stars, exp, accuracy, completed_at, created_at
                   FROM sessions WHERE client_id = ? ORDER BY created_at DESC LIMIT ?""",
                (client_id, max(1, min(limit, 100))),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, chapter_id, topic, level, kind, status, progress, current_seq,
                          question_count, stars, exp, accuracy, completed_at, created_at
                   FROM sessions ORDER BY created_at DESC LIMIT ?""",
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
               (id, session_id, seq, type, title, knowledge_point, stem, options, correct_answer,
                explanation, difficulty, rubric, source_refs)
               VALUES (:id, :session_id, :seq, :type, :title, :knowledge_point, :stem, :options,
                       :correct_answer, :explanation, :difficulty, :rubric, :source_refs)""",
            [
                {
                    "id": q["id"],
                    "session_id": session_id,
                    "seq": q["seq"],
                    "type": q["type"],
                    "title": q.get("title", "") or "",
                    "knowledge_point": q.get("knowledge_point", "") or "",
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

# --------------------------------------------------------------------------- #
# chapters
# --------------------------------------------------------------------------- #
def create_chapter(row: Dict[str, Any]) -> None:
    ts = now_iso()
    with connect() as conn:
        conn.execute(
            """INSERT INTO chapters
               (id, client_id, session_id, title, topic, level, question_count, kind,
                parent_chapter_id, stars, accuracy, exp, created_at, completed_at, updated_at)
               VALUES (:id, :client_id, :session_id, :title, :topic, :level, :question_count, :kind,
                       :parent_chapter_id, 0, 0, 0, :created_at, NULL, :updated_at)""",
            {
                "id": row["id"],
                "client_id": row.get("client_id", "anonymous") or "anonymous",
                "session_id": row["session_id"],
                "title": row.get("title") or row.get("topic", "")[:40],
                "topic": row.get("topic", ""),
                "level": row.get("level", "basic"),
                "question_count": row.get("question_count", 5),
                "kind": row.get("kind", "standard"),
                "parent_chapter_id": row.get("parent_chapter_id"),
                "created_at": ts,
                "updated_at": ts,
            },
        )


def update_chapter(chapter_id: str, **fields: Any) -> None:
    allowed = {"stars", "accuracy", "exp", "completed_at", "title", "question_count"}
    payload = {k: v for k, v in fields.items() if k in allowed}
    if not payload:
        return
    payload["updated_at"] = now_iso()
    assignments = ", ".join(f"{k} = :{k}" for k in payload)
    payload["id"] = chapter_id
    with connect() as conn:
        conn.execute(f"UPDATE chapters SET {assignments} WHERE id = :id", payload)


def _chapter_select() -> str:
    return """SELECT c.*, s.status AS session_status, s.progress AS session_progress,
                     s.current_seq AS current_seq, s.error AS session_error,
                     s.updated_at AS session_updated_at, s.completed_at AS session_completed_at
              FROM chapters c JOIN sessions s ON s.id = c.session_id"""


def get_chapter(chapter_id: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(f"{_chapter_select()} WHERE c.id = ?", (chapter_id,)).fetchone()
    return dict(row) if row else None


def get_chapter_by_session(session_id: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(f"{_chapter_select()} WHERE c.session_id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def list_chapters(client_id: str = "anonymous", limit: int = 10) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            f"{_chapter_select()} WHERE c.client_id = ? ORDER BY c.created_at DESC LIMIT ?",
            (client_id, max(1, min(limit, 50))),
        ).fetchall()
    return [dict(r) for r in rows]


def list_completed_sessions(client_id: str = "anonymous") -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, chapter_id, topic, level, kind, stars, exp, accuracy, combo,
                      question_count, completed_at, created_at
               FROM sessions
               WHERE client_id = ? AND status = 'completed'
               ORDER BY completed_at ASC, created_at ASC""",
            (client_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_sessions_since(client_id: str, since_iso: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE client_id = ? AND created_at >= ?",
            (client_id, since_iso),
        ).fetchone()
    return int(row["n"] or 0) if row else 0


def get_comprehensive_chapter(parent_chapter_id: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(
            f"{_chapter_select()} WHERE c.parent_chapter_id = ? AND c.kind = 'comprehensive' "
            "ORDER BY c.created_at DESC LIMIT 1",
            (parent_chapter_id,),
        ).fetchone()
    return dict(row) if row else None


def delete_session_artifacts(session_id: str) -> None:
    """重试前清理半成品：题目、答案、报告。"""
    with connect() as conn:
        conn.execute("DELETE FROM questions WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM answers WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM reports WHERE session_id = ?", (session_id,))
