"""SQLite repository: connection management, schema bootstrap, CRUD.

Why embedded schema: avoids runtime path resolution headaches when packaged.
Update db/schema.sql AND the SCHEMA_SQL constant here in lockstep (Phase 1.2
intentionally small — we will not yet auto-diff schemas).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from gateway import config

logger = logging.getLogger(__name__)

# Match db/schema.sql. Keep both files in sync.
SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    name            TEXT NOT NULL,
    created_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS uploads (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    filename        TEXT NOT NULL,
    content_type    TEXT,
    size_bytes      INTEGER NOT NULL,
    storage_path    TEXT NOT NULL,
    parsed_json     TEXT,
    parse_status    TEXT NOT NULL DEFAULT 'ok',
    parse_error     TEXT,
    created_at      INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_uploads_user ON uploads(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_tasks (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    upload_id           TEXT,
    agent_template_id   TEXT NOT NULL,
    agent_version       TEXT NOT NULL DEFAULT 'v1',
    taskagent_task_id   TEXT,
    status              TEXT NOT NULL DEFAULT 'queued',
    report_md           TEXT,
    error               TEXT,
    duration_ms         INTEGER,
    created_at          INTEGER NOT NULL,
    completed_at        INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON user_tasks(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_templates (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    description         TEXT,
    bundle              TEXT NOT NULL,
    job_id              TEXT NOT NULL,
    version             TEXT NOT NULL DEFAULT 'v1',
    input_schema_json   TEXT,
    enabled             INTEGER NOT NULL DEFAULT 1,
    created_at          INTEGER NOT NULL
);
"""

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def _connect() -> sqlite3.Connection:
    db_path = config.db_path_str()
    # check_same_thread=False + per-call lock: FastAPI sync handlers may run
    # on different threads. WAL mode handles concurrent readers + 1 writer.
    conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        with _lock:
            if _conn is None:
                _conn = _connect()
    return _conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Context manager for explicit transactions."""
    conn = get_conn()
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def init_db() -> None:
    """Create tables if not exist. Idempotent."""
    config.ensure_dirs()
    conn = get_conn()
    conn.executescript(SCHEMA_SQL)
    logger.info("DB schema applied at %s", config.db_path_str())
    # Seed built-in agent templates (idempotent — INSERT OR IGNORE)
    _seed_default_templates(conn)


def reset_db_for_tests() -> None:
    """Drop all tables; tests only."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
    p = Path(config.db_path_str())
    for suffix in ("", "-wal", "-shm"):
        f = Path(str(p) + suffix)
        if f.exists():
            f.unlink()


# ---------------------------------------------------------------------------
# ID generators — short, URL-safe, prefixed
# ---------------------------------------------------------------------------
def new_user_id() -> str:
    return f"usr_{uuid.uuid4().hex[:16]}"


def new_upload_id() -> str:
    return f"upl_{uuid.uuid4().hex[:16]}"


def new_user_task_id() -> str:
    return f"utk_{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def create_user(email: str, password_hash: str, name: str) -> dict[str, Any]:
    uid = new_user_id()
    now = int(time.time())
    with transaction() as conn:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, name, created_at) VALUES (?, ?, ?, ?, ?)",
            (uid, email.lower().strip(), password_hash, name.strip(), now),
        )
    return {"id": uid, "email": email.lower().strip(), "name": name.strip(), "created_at": now}


def get_user_by_email(email: str) -> Optional[dict[str, Any]]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[dict[str, Any]]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------
def create_upload(
    user_id: str,
    filename: str,
    content_type: Optional[str],
    size_bytes: int,
    storage_path: str,
    parsed_json: Optional[str],
    parse_status: str = "ok",
    parse_error: Optional[str] = None,
    upload_id: Optional[str] = None,
) -> dict[str, Any]:
    uid = upload_id or new_upload_id()
    now = int(time.time())
    with transaction() as conn:
        conn.execute(
            """INSERT INTO uploads
            (id, user_id, filename, content_type, size_bytes, storage_path,
             parsed_json, parse_status, parse_error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uid, user_id, filename, content_type, size_bytes, storage_path,
             parsed_json, parse_status, parse_error, now),
        )
    return {
        "id": uid, "user_id": user_id, "filename": filename,
        "content_type": content_type, "size_bytes": size_bytes,
        "parse_status": parse_status, "parse_error": parse_error,
        "created_at": now,
    }


def list_uploads(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM uploads WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_upload(user_id: str, upload_id: str) -> Optional[dict[str, Any]]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM uploads WHERE id = ? AND user_id = ?", (upload_id, user_id)
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# User Tasks
# ---------------------------------------------------------------------------
def create_user_task(
    user_id: str,
    agent_template_id: str,
    agent_version: str = "v1",
    upload_id: Optional[str] = None,
) -> str:
    task_id = new_user_task_id()
    now = int(time.time())
    with transaction() as conn:
        conn.execute(
            """INSERT INTO user_tasks
            (id, user_id, upload_id, agent_template_id, agent_version, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'queued', ?)""",
            (task_id, user_id, upload_id, agent_template_id, agent_version, now),
        )
    return task_id


def update_user_task(
    task_id: str,
    *,
    status: Optional[str] = None,
    taskagent_task_id: Optional[str] = None,
    report_md: Optional[str] = None,
    error: Optional[str] = None,
    duration_ms: Optional[int] = None,
    completed: bool = False,
) -> None:
    sets: list[str] = []
    args: list[Any] = []
    if status is not None:
        sets.append("status = ?"); args.append(status)
    if taskagent_task_id is not None:
        sets.append("taskagent_task_id = ?"); args.append(taskagent_task_id)
    if report_md is not None:
        sets.append("report_md = ?"); args.append(report_md)
    if error is not None:
        sets.append("error = ?"); args.append(error)
    if duration_ms is not None:
        sets.append("duration_ms = ?"); args.append(duration_ms)
    if completed:
        sets.append("completed_at = ?"); args.append(int(time.time()))
    if not sets:
        return
    args.append(task_id)
    with transaction() as conn:
        conn.execute(f"UPDATE user_tasks SET {', '.join(sets)} WHERE id = ?", args)


def get_user_task(user_id: str, task_id: str) -> Optional[dict[str, Any]]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM user_tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
    ).fetchone()
    return dict(row) if row else None


def list_user_tasks(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM user_tasks WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Agent Templates
# ---------------------------------------------------------------------------
def upsert_agent_template(
    template_id: str,
    name: str,
    bundle: str,
    job_id: str,
    description: Optional[str] = None,
    version: str = "v1",
    input_schema_json: Optional[str] = None,
    enabled: bool = True,
) -> None:
    now = int(time.time())
    with transaction() as conn:
        conn.execute(
            """INSERT INTO agent_templates
            (id, name, description, bundle, job_id, version, input_schema_json, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, description=excluded.description,
                bundle=excluded.bundle, job_id=excluded.job_id,
                version=excluded.version, input_schema_json=excluded.input_schema_json,
                enabled=excluded.enabled""",
            (template_id, name, description, bundle, job_id, version,
             input_schema_json, 1 if enabled else 0, now),
        )


def get_agent_template(template_id: str) -> Optional[dict[str, Any]]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM agent_templates WHERE id = ?", (template_id,)
    ).fetchone()
    return dict(row) if row else None


def list_agent_templates(enabled_only: bool = True) -> list[dict[str, Any]]:
    conn = get_conn()
    if enabled_only:
        rows = conn.execute(
            "SELECT * FROM agent_templates WHERE enabled = 1 ORDER BY id"
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM agent_templates ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def _seed_default_templates(conn: sqlite3.Connection) -> None:
    """Insert built-in agent templates. No-op if already present."""
    defaults = [
        {
            "id": "data-analysis-report",
            "name": "数据分析报告",
            "description": "基于统计分析结果或原始数据，生成专业的数据分析报告（摘要+关键指标+维度分析+异常+建议）。",
            "bundle": "data-analysis-report",
            "job_id": "data-analysis-report",
            "version": "v1",
            "input_schema_json": None,
            "enabled": True,
        },
    ]
    now = int(time.time())
    for t in defaults:
        conn.execute(
            """INSERT OR IGNORE INTO agent_templates
            (id, name, description, bundle, job_id, version, input_schema_json, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (t["id"], t["name"], t["description"], t["bundle"], t["job_id"],
             t["version"], t["input_schema_json"], 1 if t["enabled"] else 0, now),
        )
    logger.info("Default agent templates seeded: %s", [t["id"] for t in defaults])
