"""MySQL 持久层（PyMySQL）。

所有 SQL 收敛在本文件，业务层不感知数据库。连接使用短连接 + 显式事务，
足以支撑当前单机/低并发场景；后续可平滑替换连接池或其它数据库。
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pymysql
from pymysql.cursors import DictCursor

from .config import get_settings

_lock = threading.Lock()
_initialized = False

TABLES = [
    "auth_tokens",
    "user_settings",
    "guest_trials",
    "reports",
    "answers",
    "questions",
    "chapters",
    "sessions",
    "users",
]

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS users (
      id            VARCHAR(64) PRIMARY KEY,
      openid        VARCHAR(128) NULL,
      unionid       VARCHAR(128) NULL,
      dev_key       VARCHAR(128) NULL,
      nickname      VARCHAR(64) NOT NULL DEFAULT '旅人',
      avatar_url    VARCHAR(512) NULL,
      status        VARCHAR(20) NOT NULL DEFAULT 'active',
      created_at    VARCHAR(40) NOT NULL,
      updated_at    VARCHAR(40) NOT NULL,
      last_login_at VARCHAR(40) NULL,
      deleted_at    VARCHAR(40) NULL,
      UNIQUE KEY uniq_users_openid (openid),
      UNIQUE KEY uniq_users_dev_key (dev_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_tokens (
      id           VARCHAR(64) PRIMARY KEY,
      user_id      VARCHAR(64) NOT NULL,
      token_hash   CHAR(64) NOT NULL,
      created_at   VARCHAR(40) NOT NULL,
      expires_at   VARCHAR(40) NOT NULL,
      revoked_at   VARCHAR(40) NULL,
      last_used_at VARCHAR(40) NULL,
      UNIQUE KEY uniq_auth_token_hash (token_hash),
      KEY idx_auth_tokens_user (user_id, expires_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS user_settings (
      user_id           VARCHAR(64) PRIMARY KEY,
      reminder_enabled  TINYINT NOT NULL DEFAULT 0,
      created_at        VARCHAR(40) NOT NULL,
      updated_at        VARCHAR(40) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
      id                VARCHAR(64) PRIMARY KEY,
      user_id           VARCHAR(64) NULL,
      client_id         VARCHAR(64) NOT NULL DEFAULT 'anonymous',
      chapter_id        VARCHAR(64) NULL,
      parent_chapter_id VARCHAR(64) NULL,
      topic             VARCHAR(255) NOT NULL,
      level             VARCHAR(20) NOT NULL DEFAULT 'basic',
      requested_types   TEXT NOT NULL,
      question_count    INT NOT NULL DEFAULT 5,
      kind              VARCHAR(20) NOT NULL DEFAULT 'standard',
      status            VARCHAR(20) NOT NULL,
      stage             VARCHAR(20) NULL,
      progress          INT NOT NULL DEFAULT 0,
      current_seq       INT NOT NULL DEFAULT 1,
      stars             INT NOT NULL DEFAULT 0,
      exp               INT NOT NULL DEFAULT 0,
      accuracy          DOUBLE NOT NULL DEFAULT 0,
      combo             INT NOT NULL DEFAULT 0,
      guest_trial       TINYINT NOT NULL DEFAULT 0,
      quota_refunded    TINYINT NOT NULL DEFAULT 0,
      error             TEXT NULL,
      knowledge_brief   LONGTEXT NULL,
      sources           LONGTEXT NULL,
      model             VARCHAR(100) NULL,
      tokens_in         INT NOT NULL DEFAULT 0,
      tokens_out        INT NOT NULL DEFAULT 0,
      cost_cny          DOUBLE NOT NULL DEFAULT 0,
      submitted_at      VARCHAR(40) NULL,
      completed_at      VARCHAR(40) NULL,
      created_at        VARCHAR(40) NOT NULL,
      updated_at        VARCHAR(40) NOT NULL,
      KEY idx_sessions_client (client_id, created_at),
      KEY idx_sessions_user (user_id, created_at),
      KEY idx_sessions_quota (user_id, created_at, quota_refunded)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS chapters (
      id                VARCHAR(64) PRIMARY KEY,
      user_id           VARCHAR(64) NULL,
      client_id         VARCHAR(64) NOT NULL DEFAULT 'anonymous',
      session_id        VARCHAR(64) NOT NULL,
      title             VARCHAR(255) NOT NULL,
      topic             VARCHAR(255) NOT NULL,
      level             VARCHAR(20) NOT NULL DEFAULT 'basic',
      question_count    INT NOT NULL DEFAULT 5,
      kind              VARCHAR(20) NOT NULL DEFAULT 'standard',
      parent_chapter_id VARCHAR(64) NULL,
      stars             INT NOT NULL DEFAULT 0,
      accuracy          DOUBLE NOT NULL DEFAULT 0,
      exp               INT NOT NULL DEFAULT 0,
      created_at        VARCHAR(40) NOT NULL,
      completed_at      VARCHAR(40) NULL,
      updated_at        VARCHAR(40) NOT NULL,
      UNIQUE KEY uniq_chapters_session (session_id),
      KEY idx_chapters_client (client_id, created_at),
      KEY idx_chapters_user (user_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS questions (
      id                VARCHAR(64) PRIMARY KEY,
      session_id        VARCHAR(64) NOT NULL,
      seq               INT NOT NULL,
      type              VARCHAR(32) NOT NULL,
      title             VARCHAR(255) NOT NULL,
      knowledge_point   VARCHAR(255) NOT NULL DEFAULT '',
      stem              TEXT NOT NULL,
      options           LONGTEXT NULL,
      correct_answer    LONGTEXT NULL,
      explanation       LONGTEXT NULL,
      difficulty        VARCHAR(20) NOT NULL DEFAULT 'medium',
      rubric            LONGTEXT NULL,
      source_refs       LONGTEXT NULL,
      origin_question_id VARCHAR(64) NULL,
      KEY idx_questions_session (session_id, seq)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS answers (
      id          VARCHAR(64) PRIMARY KEY,
      session_id  VARCHAR(64) NOT NULL,
      question_id VARCHAR(64) NOT NULL,
      seq         INT NOT NULL,
      user_answer LONGTEXT NULL,
      is_correct  TINYINT NOT NULL DEFAULT 0,
      score       DOUBLE NOT NULL DEFAULT 0,
      feedback    TEXT NULL,
      created_at  VARCHAR(40) NOT NULL,
      UNIQUE KEY uniq_answers_session_question (session_id, question_id),
      KEY idx_answers_session (session_id, seq)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS reports (
      id         VARCHAR(64) PRIMARY KEY,
      session_id VARCHAR(64) NOT NULL,
      payload    LONGTEXT NOT NULL,
      created_at VARCHAR(40) NOT NULL,
      UNIQUE KEY uniq_reports_session (session_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS guest_trials (
      client_id  VARCHAR(64) PRIMARY KEY,
      session_id VARCHAR(64) NULL,
      ip_hash    VARCHAR(64) NULL,
      used_at    VARCHAR(40) NOT NULL,
      claimed_user_id VARCHAR(64) NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(use_database: bool = True) -> pymysql.connections.Connection:
    settings = get_settings()
    kwargs: Dict[str, Any] = {
        "host": settings.mysql_host,
        "port": settings.mysql_port,
        "user": settings.mysql_user,
        "password": settings.mysql_password,
        "charset": settings.mysql_charset,
        "connect_timeout": settings.mysql_connect_timeout,
        "cursorclass": DictCursor,
        "autocommit": False,
    }
    if use_database:
        kwargs["database"] = settings.mysql_database
    return pymysql.connect(**kwargs)


def _columns(conn: pymysql.connections.Connection, table: str) -> set:
    with conn.cursor() as cur:
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        return {row["Field"] for row in cur.fetchall()}


def _ensure_column(conn: pymysql.connections.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _columns(conn, table):
        with conn.cursor() as cur:
            cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl}")
        conn.commit()


def _ensure_index(
    conn: pymysql.connections.Connection, table: str, index: str, columns: str
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) AS n FROM information_schema.statistics
               WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s""",
            (table, index),
        )
        row = cur.fetchone()
        if row and int(row["n"]) > 0:
            return
        cur.execute(f"CREATE INDEX `{index}` ON `{table}` ({columns})")
    conn.commit()


def _migrate(conn: pymysql.connections.Connection) -> None:
    """向后兼容迁移：只加列/索引，不删列。"""
    _ensure_column(conn, "sessions", "user_id", "VARCHAR(64) NULL")
    _ensure_column(conn, "sessions", "guest_trial", "TINYINT NOT NULL DEFAULT 0")
    _ensure_column(conn, "sessions", "quota_refunded", "TINYINT NOT NULL DEFAULT 0")
    _ensure_column(conn, "chapters", "user_id", "VARCHAR(64) NULL")
    _ensure_column(conn, "questions", "origin_question_id", "VARCHAR(64) NULL")
    _ensure_index(conn, "sessions", "idx_sessions_user", "user_id, created_at")
    _ensure_index(conn, "sessions", "idx_sessions_quota", "user_id, created_at, quota_refunded")
    _ensure_index(conn, "chapters", "idx_chapters_user", "user_id, created_at")


def init_db() -> None:
    global _initialized
    with _lock:
        if _initialized:
            return
        try:
            conn = _connect()
        except pymysql.err.OperationalError as exc:
            settings = get_settings()
            raise RuntimeError(
                f"无法连接 MySQL（{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}）："
                f"{exc}。本地开发请先在 backend/ 下运行 ./scripts/start_mysql_dev.sh 启动 3307 实例；"
                "生产环境请确认已创建数据库并配置 MYSQL_* 环境变量。"
            ) from exc
        try:
            with conn.cursor() as cur:
                for statement in SCHEMA:
                    cur.execute(statement)
            conn.commit()
            _migrate(conn)
        finally:
            conn.close()
        _initialized = True


@contextmanager
def connect():
    init_db()
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def truncate_all() -> None:
    """测试夹具：清空所有业务表。"""
    with connect() as conn:
        with conn.cursor() as cur:
            for table in TABLES:
                cur.execute(f"TRUNCATE TABLE `{table}`")


def _loads(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# users / auth
# --------------------------------------------------------------------------- #
def create_user(row: Dict[str, Any]) -> None:
    ts = now_iso()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users
                   (id, openid, unionid, dev_key, nickname, avatar_url, status,
                    created_at, updated_at, last_login_at, deleted_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)""",
                (
                    row["id"],
                    row.get("openid"),
                    row.get("unionid"),
                    row.get("dev_key"),
                    row.get("nickname") or "旅人",
                    row.get("avatar_url"),
                    row.get("status") or "active",
                    ts,
                    ts,
                    row.get("last_login_at") or ts,
                ),
            )


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def get_user_by_openid(openid: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE openid = %s", (openid,))
            row = cur.fetchone()
    return dict(row) if row else None


def get_user_by_dev_key(dev_key: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE dev_key = %s", (dev_key,))
            row = cur.fetchone()
    return dict(row) if row else None


def update_user(user_id: str, **fields: Any) -> None:
    allowed = {"nickname", "avatar_url", "last_login_at", "status", "openid", "unionid", "dev_key", "deleted_at"}
    payload = {k: v for k, v in fields.items() if k in allowed}
    if not payload:
        return
    payload["updated_at"] = now_iso()
    assignments = ", ".join(f"`{k}` = %s" for k in payload)
    values = list(payload.values()) + [user_id]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE users SET {assignments} WHERE id = %s", values)


def touch_user_login(user_id: str) -> None:
    ts = now_iso()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET last_login_at = %s, updated_at = %s WHERE id = %s AND status = 'active'",
                (ts, ts, user_id),
            )


def soft_delete_user(user_id: str) -> None:
    ts = now_iso()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE users SET status = 'deleted', openid = NULL, unionid = NULL,
                   dev_key = NULL, nickname = '已注销旅人', avatar_url = NULL,
                   deleted_at = %s, updated_at = %s WHERE id = %s""",
                (ts, ts, user_id),
            )


def anonymize_user_data(user_id: str) -> None:
    """注销后保留学习记录的统计价值，但解除与个人身份的关联。"""
    deleted_client = f"deleted_{user_id}"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET user_id = NULL, client_id = %s WHERE user_id = %s",
                (deleted_client, user_id),
            )
            cur.execute(
                "UPDATE chapters SET user_id = NULL, client_id = %s WHERE user_id = %s",
                (deleted_client, user_id),
            )
            cur.execute("DELETE FROM user_settings WHERE user_id = %s", (user_id,))
            cur.execute(
                "UPDATE auth_tokens SET revoked_at = %s WHERE user_id = %s AND revoked_at IS NULL",
                (now_iso(), user_id),
            )
            cur.execute(
                "UPDATE guest_trials SET claimed_user_id = NULL WHERE claimed_user_id = %s",
                (user_id,),
            )


def create_auth_token(row: Dict[str, Any]) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO auth_tokens
                   (id, user_id, token_hash, created_at, expires_at, revoked_at, last_used_at)
                   VALUES (%s, %s, %s, %s, %s, NULL, NULL)""",
                (row["id"], row["user_id"], row["token_hash"], row["created_at"], row["expires_at"]),
            )


def get_user_by_token_hash(token_hash: str, now: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT u.* FROM auth_tokens t JOIN users u ON u.id = t.user_id
                   WHERE t.token_hash = %s AND t.revoked_at IS NULL AND t.expires_at > %s
                     AND u.status = 'active'""",
                (token_hash, now),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE auth_tokens SET last_used_at = %s WHERE token_hash = %s",
                    (now, token_hash),
                )
    return dict(row) if row else None


def revoke_auth_token(token_hash: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE auth_tokens SET revoked_at = %s WHERE token_hash = %s AND revoked_at IS NULL",
                (now_iso(), token_hash),
            )


def revoke_user_tokens(user_id: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE auth_tokens SET revoked_at = %s WHERE user_id = %s AND revoked_at IS NULL",
                (now_iso(), user_id),
            )


# --------------------------------------------------------------------------- #
# user settings
# --------------------------------------------------------------------------- #
def get_user_settings(user_id: str) -> Dict[str, Any]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM user_settings WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
    if not row:
        return {"user_id": user_id, "reminder_enabled": False}
    data = dict(row)
    data["reminder_enabled"] = bool(data.get("reminder_enabled"))
    return data


def upsert_user_settings(user_id: str, **fields: Any) -> Dict[str, Any]:
    allowed = {"reminder_enabled"}
    payload = {k: v for k, v in fields.items() if k in allowed}
    if not payload:
        return get_user_settings(user_id)
    ts = now_iso()
    values = {
        "user_id": user_id,
        "reminder_enabled": 1 if payload.get("reminder_enabled") else 0,
        "created_at": ts,
        "updated_at": ts,
    }
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO user_settings (user_id, reminder_enabled, created_at, updated_at)
                   VALUES (%s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE reminder_enabled = VALUES(reminder_enabled),
                                           updated_at = VALUES(updated_at)""",
                (values["user_id"], values["reminder_enabled"], values["created_at"], values["updated_at"]),
            )
    return get_user_settings(user_id)


# --------------------------------------------------------------------------- #
# sessions
# --------------------------------------------------------------------------- #
def create_session(row: Dict[str, Any]) -> None:
    ts = now_iso()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO sessions
                   (id, user_id, client_id, chapter_id, parent_chapter_id, topic, level,
                    requested_types, question_count, kind, status, stage, progress, current_seq,
                    stars, exp, accuracy, combo, guest_trial, quota_refunded,
                    error, knowledge_brief, sources, model, tokens_in, tokens_out, cost_cny,
                    submitted_at, completed_at, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          0, 0, 0, 0, %s, 0, NULL, NULL, NULL, %s, 0, 0, 0, NULL, NULL, %s, %s)""",
                (
                    row["id"],
                    row.get("user_id"),
                    row.get("client_id", "anonymous") or "anonymous",
                    row.get("chapter_id"),
                    row.get("parent_chapter_id"),
                    row["topic"],
                    row.get("level", "basic"),
                    json.dumps(row.get("requested_types", []), ensure_ascii=False),
                    row.get("question_count", 5),
                    row.get("kind", "standard"),
                    row.get("status", "queued"),
                    row.get("stage", "queued"),
                    row.get("progress", 0),
                    row.get("current_seq", 1),
                    1 if row.get("guest_trial") else 0,
                    row.get("model"),
                    ts,
                    ts,
                ),
            )


def update_session(session_id: str, **fields: Any) -> None:
    allowed = {
        "status", "stage", "progress", "current_seq", "error", "knowledge_brief", "sources",
        "model", "tokens_in", "tokens_out", "cost_cny", "submitted_at", "completed_at",
        "user_id", "client_id", "chapter_id", "parent_chapter_id", "kind", "stars", "exp",
        "accuracy", "combo", "guest_trial", "quota_refunded",
    }
    payload = {k: v for k, v in fields.items() if k in allowed}
    if not payload:
        return
    if "knowledge_brief" in payload:
        value = payload["knowledge_brief"]
        if value is not None and not isinstance(value, str):
            payload["knowledge_brief"] = json.dumps(value, ensure_ascii=False)
    if "sources" in payload:
        value = payload["sources"]
        if value is not None and not isinstance(value, str):
            payload["sources"] = json.dumps(value, ensure_ascii=False)
    for key in ("guest_trial", "quota_refunded"):
        if key in payload:
            payload[key] = 1 if payload[key] else 0
    payload["updated_at"] = now_iso()
    assignments = ", ".join(f"`{k}` = %s" for k in payload)
    values = list(payload.values()) + [session_id]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE sessions SET {assignments} WHERE id = %s", values)


def add_usage(session_id: str, tokens_in: int, tokens_out: int, cost_cny: float) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE sessions SET tokens_in = tokens_in + %s, tokens_out = tokens_out + %s,
                   cost_cny = cost_cny + %s, updated_at = %s WHERE id = %s""",
                (int(tokens_in), int(tokens_out), round(float(cost_cny), 6), now_iso(), session_id),
            )


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM sessions WHERE id = %s", (session_id,))
            row = cur.fetchone()
    if not row:
        return None
    data = dict(row)
    data["requested_types"] = _loads(data.get("requested_types"), [])
    data["sources"] = _loads(data.get("sources"), [])
    return data


def _session_select_fields() -> str:
    return """id, user_id, client_id, chapter_id, parent_chapter_id, topic, level, kind,
              status, progress, current_seq, question_count, stars, exp, accuracy,
              completed_at, created_at, guest_trial, quota_refunded"""


def list_recent_sessions(
    limit: int = 20, client_id: Optional[str] = None, user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 100))
    query = f"SELECT {_session_select_fields()} FROM sessions"
    params: List[Any] = []
    if user_id:
        query += " WHERE user_id = %s"
        params.append(user_id)
    elif client_id:
        query += " WHERE client_id = %s AND user_id IS NULL"
        params.append(client_id)
    query += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def list_records(
    user_id: Optional[str],
    client_id: Optional[str],
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    where = ""
    params: List[Any] = []
    if user_id:
        where = " WHERE user_id = %s"
        params.append(user_id)
    elif client_id:
        where = " WHERE client_id = %s AND user_id IS NULL"
        params.append(client_id)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM sessions{where}", params)
            total = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute(
                f"""SELECT {_session_select_fields()} FROM sessions{where}
                    ORDER BY created_at DESC LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows], total


def count_sessions_for_quota(
    user_id: Optional[str], client_id: Optional[str], since_iso: str
) -> int:
    """统计会消耗额度的会话：排除错题重练、游客试用、已返还额度的失败会话。"""
    query = """SELECT COUNT(*) AS n FROM sessions
               WHERE kind IN ('standard', 'daily', 'comprehensive')
                 AND guest_trial = 0 AND quota_refunded = 0 AND created_at >= %s"""
    params: List[Any] = [since_iso]
    if user_id:
        query += " AND user_id = %s"
        params.append(user_id)
    elif client_id:
        query += " AND client_id = %s AND user_id IS NULL"
        params.append(client_id)
    else:
        return 0
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
    return int((row or {}).get("n") or 0)


def set_quota_refunded(session_id: str, refunded: bool = True) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET quota_refunded = %s, updated_at = %s WHERE id = %s",
                (1 if refunded else 0, now_iso(), session_id),
            )


def claim_guest_data(client_id: str, user_id: str) -> Dict[str, int]:
    """把本机游客数据绑定到新登录账号；幂等。"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET user_id = %s WHERE client_id = %s AND user_id IS NULL",
                (user_id, client_id),
            )
            sessions = cur.rowcount
            cur.execute(
                "UPDATE chapters SET user_id = %s WHERE client_id = %s AND user_id IS NULL",
                (user_id, client_id),
            )
            chapters = cur.rowcount
            cur.execute(
                "UPDATE guest_trials SET claimed_user_id = %s WHERE client_id = %s",
                (user_id, client_id),
            )
    return {"sessions": max(0, sessions), "chapters": max(0, chapters)}


# --------------------------------------------------------------------------- #
# guest trial
# --------------------------------------------------------------------------- #
def guest_trial_used(client_id: str) -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT client_id FROM guest_trials WHERE client_id = %s", (client_id,))
            row = cur.fetchone()
    return bool(row)


def consume_guest_trial(client_id: str, session_id: str, ip_hash: Optional[str]) -> bool:
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO guest_trials (client_id, session_id, ip_hash, used_at, claimed_user_id)
                       VALUES (%s, %s, %s, %s, NULL)""",
                    (client_id, session_id, ip_hash, now_iso()),
                )
        return True
    except pymysql.err.IntegrityError:
        return False


def refund_guest_trial(client_id: str, session_id: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM guest_trials WHERE client_id = %s AND session_id = %s",
                (client_id, session_id),
            )


# --------------------------------------------------------------------------- #
# questions
# --------------------------------------------------------------------------- #
def insert_questions(session_id: str, questions: Iterable[Dict[str, Any]]) -> None:
    rows = [
        (
            q["id"],
            session_id,
            q["seq"],
            q["type"],
            q.get("title", "") or "",
            q.get("knowledge_point", "") or "",
            q["stem"],
            json.dumps(q.get("options", []), ensure_ascii=False),
            json.dumps(q.get("correct_answer"), ensure_ascii=False),
            q.get("explanation", ""),
            q.get("difficulty", "medium"),
            json.dumps(q.get("rubric", []), ensure_ascii=False),
            json.dumps(q.get("source_refs", []), ensure_ascii=False),
            q.get("origin_question_id"),
        )
        for q in questions
    ]
    if not rows:
        return
    with connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO questions
                   (id, session_id, seq, type, title, knowledge_point, stem, options,
                    correct_answer, explanation, difficulty, rubric, source_refs, origin_question_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                     seq = VALUES(seq), type = VALUES(type), title = VALUES(title),
                     knowledge_point = VALUES(knowledge_point), stem = VALUES(stem),
                     options = VALUES(options), correct_answer = VALUES(correct_answer),
                     explanation = VALUES(explanation), difficulty = VALUES(difficulty),
                     rubric = VALUES(rubric), source_refs = VALUES(source_refs),
                     origin_question_id = VALUES(origin_question_id)""",
                rows,
            )


def list_questions(session_id: str) -> List[Dict[str, Any]]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM questions WHERE session_id = %s ORDER BY seq ASC", (session_id,)
            )
            rows = cur.fetchall()
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
    rows = [
        (
            a["id"],
            session_id,
            a["question_id"],
            a["seq"],
            json.dumps(a.get("user_answer"), ensure_ascii=False),
            1 if a.get("is_correct") else 0,
            float(a.get("score", 0)),
            a.get("feedback", ""),
            ts,
        )
        for a in answers
    ]
    if not rows:
        return
    with connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO answers
                   (id, session_id, question_id, seq, user_answer, is_correct, score, feedback, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                     user_answer = VALUES(user_answer), is_correct = VALUES(is_correct),
                     score = VALUES(score), feedback = VALUES(feedback)""",
                rows,
            )


def list_answers(session_id: str) -> List[Dict[str, Any]]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM answers WHERE session_id = %s ORDER BY seq ASC", (session_id,)
            )
            rows = cur.fetchall()
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
    data = json.dumps(payload, ensure_ascii=False)
    ts = now_iso()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO reports (id, session_id, payload, created_at)
                   VALUES (%s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE payload = VALUES(payload)""",
                (f"rep_{session_id}", session_id, data, ts),
            )


def get_report(session_id: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM reports WHERE session_id = %s", (session_id,))
            row = cur.fetchone()
    if not row:
        return None
    return _loads(row["payload"], None)


# --------------------------------------------------------------------------- #
# chapters
# --------------------------------------------------------------------------- #
def create_chapter(row: Dict[str, Any]) -> None:
    ts = now_iso()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO chapters
                   (id, user_id, client_id, session_id, title, topic, level, question_count,
                    kind, parent_chapter_id, stars, accuracy, exp, created_at, completed_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 0, 0, %s, NULL, %s)""",
                (
                    row["id"],
                    row.get("user_id"),
                    row.get("client_id", "anonymous") or "anonymous",
                    row["session_id"],
                    row.get("title") or row.get("topic", "")[:40],
                    row.get("topic", ""),
                    row.get("level", "basic"),
                    row.get("question_count", 5),
                    row.get("kind", "standard"),
                    row.get("parent_chapter_id"),
                    ts,
                    ts,
                ),
            )


def update_chapter(chapter_id: str, **fields: Any) -> None:
    allowed = {"stars", "accuracy", "exp", "completed_at", "title", "question_count", "user_id"}
    payload = {k: v for k, v in fields.items() if k in allowed}
    if not payload:
        return
    payload["updated_at"] = now_iso()
    assignments = ", ".join(f"`{k}` = %s" for k in payload)
    values = list(payload.values()) + [chapter_id]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE chapters SET {assignments} WHERE id = %s", values)


def _chapter_select() -> str:
    return """SELECT c.*, s.status AS session_status, s.progress AS session_progress,
                     s.current_seq AS current_seq, s.error AS session_error,
                     s.updated_at AS session_updated_at, s.completed_at AS session_completed_at
              FROM chapters c JOIN sessions s ON s.id = c.session_id"""


def get_chapter(chapter_id: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"{_chapter_select()} WHERE c.id = %s", (chapter_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def get_chapter_by_session(session_id: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"{_chapter_select()} WHERE c.session_id = %s", (session_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def list_chapters(
    client_id: str = "anonymous", limit: int = 10, user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 50))
    if user_id:
        where = "WHERE c.user_id = %s"
        params: List[Any] = [user_id, limit]
    else:
        where = "WHERE c.client_id = %s AND c.user_id IS NULL"
        params = [client_id, limit]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"{_chapter_select()} {where} ORDER BY c.created_at DESC LIMIT %s",
                params,
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def list_completed_sessions(
    client_id: str = "anonymous", user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    if user_id:
        where = "WHERE user_id = %s AND status = 'completed'"
        params: List[Any] = [user_id]
    else:
        where = "WHERE client_id = %s AND user_id IS NULL AND status = 'completed'"
        params = [client_id]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT id, chapter_id, topic, level, kind, stars, exp, accuracy, combo,
                           question_count, completed_at, created_at
                    FROM sessions {where}
                    ORDER BY completed_at ASC, created_at ASC""",
                params,
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def count_sessions_since(
    client_id: str, since_iso: str, user_id: Optional[str] = None
) -> int:
    if user_id:
        where = "user_id = %s AND created_at >= %s"
        params: List[Any] = [user_id, since_iso]
    else:
        where = "client_id = %s AND user_id IS NULL AND created_at >= %s"
        params = [client_id, since_iso]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM sessions WHERE {where}", params)
            row = cur.fetchone()
    return int((row or {}).get("n") or 0)


def get_comprehensive_chapter(parent_chapter_id: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""{_chapter_select()} WHERE c.parent_chapter_id = %s AND c.kind = 'comprehensive'
                    ORDER BY c.created_at DESC LIMIT 1""",
                (parent_chapter_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def delete_session_artifacts(session_id: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM questions WHERE session_id = %s", (session_id,))
            cur.execute("DELETE FROM answers WHERE session_id = %s", (session_id,))
            cur.execute("DELETE FROM reports WHERE session_id = %s", (session_id,))