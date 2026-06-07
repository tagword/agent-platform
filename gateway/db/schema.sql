-- Agent Platform schema (SQLite)
-- All tables created with IF NOT EXISTS; safe to run on every boot.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,            -- usr_<16hex>
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    name            TEXT NOT NULL,
    created_at      INTEGER NOT NULL             -- unix seconds
);

CREATE TABLE IF NOT EXISTS uploads (
    id              TEXT PRIMARY KEY,            -- upl_<16hex>
    user_id         TEXT NOT NULL,
    filename        TEXT NOT NULL,
    content_type    TEXT,
    size_bytes      INTEGER NOT NULL,
    storage_path    TEXT NOT NULL,                -- absolute path on disk
    parsed_json     TEXT,                        -- parsed payload (JSON text) or NULL
    parse_status    TEXT NOT NULL DEFAULT 'ok',  -- ok | unsupported | failed
    parse_error     TEXT,
    created_at      INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_uploads_user ON uploads(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_tasks (
    id                  TEXT PRIMARY KEY,        -- utk_<16hex>
    user_id             TEXT NOT NULL,
    upload_id           TEXT,
    agent_template_id   TEXT NOT NULL,           -- e.g. 'data-analysis-report'
    agent_version       TEXT NOT NULL DEFAULT 'v1',
    taskagent_task_id   TEXT,                    -- nullable until TaskAgent acks
    status              TEXT NOT NULL DEFAULT 'queued',
    -- queued | running | ok | failed | timeout
    report_md           TEXT,
    error               TEXT,
    duration_ms         INTEGER,
    created_at          INTEGER NOT NULL,
    completed_at        INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON user_tasks(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_templates (
    id                  TEXT PRIMARY KEY,        -- e.g. 'data-analysis-report'
    name                TEXT NOT NULL,
    description         TEXT,
    bundle              TEXT NOT NULL,            -- e.g. 'data-analysis-report'
    job_id              TEXT NOT NULL,            -- e.g. 'data-analysis-report'
    version             TEXT NOT NULL DEFAULT 'v1',
    input_schema_json   TEXT,
    enabled             INTEGER NOT NULL DEFAULT 1,
    created_at          INTEGER NOT NULL
);
