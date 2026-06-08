"""SQLite repository: connection management, schema bootstrap, CRUD.

Why embedded schema: avoids runtime path resolution headaches when packaged.
Update db/schema.sql AND the SCHEMA_SQL constant here in lockstep (Phase 1.2
intentionally small — we will not yet auto-diff schemas).
"""

from __future__ import annotations

import json
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

CREATE TABLE IF NOT EXISTS user_agents (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    name                TEXT NOT NULL,
    description         TEXT DEFAULT '',
    system_prompt       TEXT DEFAULT '',
    tools_json          TEXT DEFAULT '[]',
    model               TEXT DEFAULT '',
    created_at          INTEGER NOT NULL,
    updated_at          INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_user_agents_user ON user_agents(user_id, created_at DESC);
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


def new_agent_id() -> str:
    return f"ag_{uuid.uuid4().hex[:16]}"


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
# User Agents (custom agents created via UI)
# ---------------------------------------------------------------------------
def create_user_agent(
    user_id: str,
    name: str,
    description: str = "",
    system_prompt: str = "",
    tools: Optional[list[str]] = None,
    model: str = "",
) -> dict[str, Any]:
    aid = new_agent_id()
    now = int(time.time())
    tools_str = json.dumps(tools or [])
    with transaction() as conn:
        conn.execute(
            """INSERT INTO user_agents
            (id, user_id, name, description, system_prompt, tools_json, model, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (aid, user_id, name.strip(), description.strip(), system_prompt.strip(),
             tools_str, model.strip(), now, now),
        )
    return {
        "id": aid, "user_id": user_id, "name": name.strip(),
        "description": description.strip(), "system_prompt": system_prompt.strip(),
        "tools": tools or [], "model": model.strip(),
        "created_at": now, "updated_at": now,
    }


def list_user_agents(user_id: str) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM user_agents WHERE user_id = ? ORDER BY created_at DESC, id DESC",
        (user_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tools"] = json.loads(d.get("tools_json") or "[]")
        d.pop("tools_json", None)
        out.append(d)
    return out


def get_user_agent(user_id: str, agent_id: str) -> Optional[dict[str, Any]]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM user_agents WHERE id = ? AND user_id = ?", (agent_id, user_id)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["tools"] = json.loads(d.get("tools_json") or "[]")
    d.pop("tools_json", None)
    return d


def update_user_agent(
    user_id: str,
    agent_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    system_prompt: Optional[str] = None,
    tools: Optional[list[str]] = None,
    model: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    sets: list[str] = []
    args: list[Any] = []
    if name is not None:
        sets.append("name = ?"); args.append(name.strip())
    if description is not None:
        sets.append("description = ?"); args.append(description.strip())
    if system_prompt is not None:
        sets.append("system_prompt = ?"); args.append(system_prompt.strip())
    if tools is not None:
        sets.append("tools_json = ?"); args.append(json.dumps(tools))
    if model is not None:
        sets.append("model = ?"); args.append(model.strip())
    if not sets:
        return get_user_agent(user_id, agent_id)
    now = int(time.time())
    sets.append("updated_at = ?")
    args.append(now)
    args.extend([agent_id, user_id])
    with transaction() as conn:
        conn.execute(
            f"UPDATE user_agents SET {', '.join(sets)} WHERE id = ? AND user_id = ?",
            args,
        )
    return get_user_agent(user_id, agent_id)


def delete_user_agent(user_id: str, agent_id: str) -> bool:
    with transaction() as conn:
        cur = conn.execute(
            "DELETE FROM user_agents WHERE id = ? AND user_id = ?",
            (agent_id, user_id),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Agent Templates (built-in)
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
        {
            "id": "code-review",
            "name": "代码审查",
            "description": "对上传的代码文件进行结构化审查（正确性/可读性/性能/安全/可维护性），输出按严重度分级的问题清单和改进建议。",
            "bundle": "code-review",
            "job_id": "code-review",
            "version": "v1",
            "input_schema_json": None,
            "enabled": True,
        },
        {
            "id": "doc-summary",
            "name": "文档摘要",
            "description": "对长文档（技术文档/报告/文章/会议纪要）生成结构化摘要，含核心要点、关键数据、术语表、行动建议。",
            "bundle": "doc-summary",
            "job_id": "doc-summary",
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
