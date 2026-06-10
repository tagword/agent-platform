# Agent Platform — HTTP API Reference

> Version: 0.1.0
> Base URL: `http://{host}:{port}` (default port 8780)
> Content-Type: `application/json` unless noted

All authenticated endpoints expect `Authorization: Bearer <jwt>`.
Tokens are issued by `/api/auth/register` or `/api/auth/login` and expire in 7 days by default.

---

## 1. Health

### `GET /health`

Liveness check. No auth.

**Response 200**
```json
{"ok": true, "service": "agent-platform", "version": "0.1.0"}
```

---

## 2. Authentication

### `POST /api/auth/register`

Create a new user. Returns a JWT for immediate use.

**Request**
```json
{
  "email": "alice@example.com",
  "password": "secret123",
  "name": "Alice"
}
```

| Field | Required | Constraints |
|-------|----------|-------------|
| `email` | yes | valid email format, max 200 chars |
| `password` | yes | min 6 chars, max 200 |
| `name` | yes | 1-100 chars |

**Response 201**
```json
{
  "token": "eyJhbGci...",
  "user": {
    "id": "usr_abc123",
    "email": "alice@example.com",
    "name": "Alice",
    "created_at": 1780875186
  },
  "expires_in_hours": 168
}
```

**Errors**
- `400` — invalid email format
- `409` — email already registered
- `422` — missing/invalid field

### `POST /api/auth/login`

Exchange email+password for a JWT.

**Request**
```json
{"email": "alice@example.com", "password": "secret123"}
```

**Response 200** — same as register.
**Errors**
- `400` — invalid email format
- `401` — invalid email or password (deliberately vague)

### `GET /api/auth/me`

Return the current user.

**Response 200**
```json
{"id": "usr_abc123", "email": "alice@example.com", "name": "Alice", "created_at": 1780875186}
```

**Errors**
- `401` — missing / expired / invalid token

---

## 3. Agent Templates

### `GET /api/agents`

List enabled agent templates available to run.

**Response 200**
```json
{
  "agents": [
    {
      "id": "data-analysis-report",
      "name": "数据分析报告",
      "description": "基于统计分析结果或原始数据，生成专业的数据分析报告（摘要+关键指标+维度分析+异常+建议）。",
      "version": "v1",
      "bundle": "data-analysis-report",
      "job_id": "data-analysis-report"
    }
  ]
}
```

### `GET /api/agents/{agent_id}`

Get a single agent template.

**Response 200** — same shape as above entry.
**Errors**
- `404` — agent not found or disabled

---

## 4. Uploads

### `POST /api/uploads`

Upload a file (CSV / XLSX / XLS / JSON). The file is parsed server-side.

**Request**: `multipart/form-data` with field `file`.

| Field | Required | Notes |
|-------|----------|-------|
| `file` | yes | `.csv` `.xlsx` `.xls` `.json`, ≤ 10 MB |

**Response 201**
```json
{
  "id": "upl_82a581bd2c1345d4",
  "filename": "q2-dau.csv",
  "size_bytes": 360,
  "content_type": "text/csv",
  "parse_status": "ok",
  "parse_error": null,
  "summary": {
    "row_count": 10,
    "columns": ["date", "channel", "new_users", "retained_d7", "revenue"]
  },
  "created_at": 1780875215
}
```

`parse_status` is one of:
- `ok` — parsed successfully
- `failed` — see `parse_error`; the file is still stored, but `parse_error` is non-null

**Errors**
- `400` — unsupported extension
- `413` — file exceeds `AGENT_PLATFORM_MAX_UPLOAD_MB` (default 10 MB)
- `422` — multipart parse error

### `GET /api/uploads`

List the current user's uploads (most recent first).

**Query params**
- `limit` — default 50, max 200

**Response 200**
```json
{
  "uploads": [
    {
      "id": "upl_82a581bd2c1345d4",
      "filename": "q2-dau.csv",
      "size_bytes": 360,
      "parse_status": "ok",
      "parse_error": null,
      "created_at": 1780875215
    }
  ]
}
```

### `GET /api/uploads/{upload_id}`

Get a single upload **including the parsed payload**.

**Response 200**
```json
{
  "id": "upl_82a581bd2c1345d4",
  "filename": "q2-dau.csv",
  "size_bytes": 360,
  "content_type": "text/csv",
  "parse_status": "ok",
  "parse_error": null,
  "summary": {"row_count": 10, "columns": [...]},
  "rows": [{"date": "2026-04-01", "channel": "organic", ...}],
  "created_at": 1780875215
}
```

For JSON uploads that are objects (not arrays), `rows` is null and `data` contains the object.

**Errors**
- `404` — upload not found (or owned by another user)

---

## 5. Tasks

### `POST /api/tasks/run`

Trigger a task **synchronously**. Blocks until TaskAgent returns the report
or `AGENT_PLATFORM_TASKAGENT_TIMEOUT_SEC` elapses (default 180s).

**Request**
```json
{
  "upload_id": "upl_82a581bd2c1345d4",
  "agent_id": "data-analysis-report",
  "user_instructions": "重点关注付费渠道的留存率异常",
  "dataset_name": "Q2 用户增长数据"
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `upload_id` | yes | Must belong to current user, must have `parse_status=ok` |
| `agent_id` | yes | Must be an enabled template |
| `user_instructions` | no | Free text, max 2000 chars, passed as context to the agent |
| `dataset_name` | no | Defaults to the upload's filename |

**Response 200**
```json
{
  "task_id": "utk_a1020cbd76514d3e",
  "status": "ok",
  "report": "# Q2 DAU 数据分析报告\n\n...",
  "error": null,
  "duration_ms": 16021,
  "usage": {
    "prompt_tokens": 9817,
    "completion_tokens": 2278,
    "total_tokens": 12095
  }
}
```

`status` is one of: `ok`, `failed`, `timeout`, `cancelled`.

**Errors**
- `400` — `parse_error` on the upload / no parsed data
- `404` — agent not found / upload not found
- `502` — TaskAgent unreachable, timed out, or returned an error

The task row is always persisted in the database, regardless of outcome —
DB-side `status` reflects the actual result, HTTP status reflects whether
the call was well-formed.

### `GET /api/tasks`

List the current user's tasks (most recent first).

**Query params**
- `limit` — default 50, max 200

**Response 200**
```json
{
  "tasks": [
    {
      "id": "utk_a1020cbd76514d3e",
      "upload_id": "upl_82a581bd2c1345d4",
      "agent_template_id": "data-analysis-report",
      "agent_version": "v1",
      "status": "ok",
      "error": null,
      "duration_ms": 16021,
      "created_at": 1780875300,
      "completed_at": 1780875316
    }
  ]
}
```

### `GET /api/tasks/{task_id}`

Get a single task, including the full Markdown report.

**Response 200**
```json
{
  "id": "utk_a1020cbd76514d3e",
  "upload_id": "upl_82a581bd2c1345d4",
  "agent_template_id": "data-analysis-report",
  "agent_version": "v1",
  "taskagent_task_id": "tsk_fake_id_1234",
  "status": "ok",
  "report": "# Q2 DAU 数据分析报告\n\n...",
  "error": null,
  "duration_ms": 16021,
  "created_at": 1780875300,
  "completed_at": 1780875316
}

---

## 7. Available Tools

### `GET /api/available-tools`

List all tools available in the Seed Tools registry. Used when creating a custom Agent to let users pick which tools the Agent can use.

**Response 200**
```json
{
  "tools": [
    {"name": "bash_tool", "description": "Execute shell commands"},
    {"name": "file_read", "description": "Read file contents"},
    {"name": "file_write", "description": "Write content to file"}
  ]
}
```

---

## 8. User Agents (Custom Agent CRUD)

All endpoints require `Authorization: Bearer <jwt>`.

### `GET /api/user-agents`

List the current user's custom Agents.

**Response 200**
```json
{
  "agents": [
    {
      "id": "ag_custom_abc123",
      "name": "My Code Reviewer",
      "description": "Reviews Python code",
      "tools": ["bash_tool", "file_read", "grep_tool"],
      "persona": "You are a senior Python code reviewer...",
      "config": {},
      "created_at": 1780875300
    }
  ]
}
```

### `POST /api/user-agents`

Create a new custom Agent. Writes `tools.json` and persona for the Agent.

**Request**
```json
{
  "name": "My Code Reviewer",
  "description": "Reviews Python code",
  "tools": ["bash_tool", "file_read", "grep_tool"],
  "persona": "You are a senior Python code reviewer..."
}
```

**Response 201**
```json
{
  "id": "ag_custom_abc123",
  "name": "My Code Reviewer",
  "created_at": 1780875300
}
```

### `GET /api/user-agents/{agent_id}`

Get a single custom Agent.

### `PUT /api/user-agents/{agent_id}`

Update a custom Agent. Same request body as POST. Full replace.

### `DELETE /api/user-agents/{agent_id}`

Delete a custom Agent.

**Response 200**
```json
{"ok": true}
```

---

## 9. Teams (Team + Workflow)

All endpoints require `Authorization: Bearer <jwt>`.

### `GET /api/teams`

List the current user's teams.

**Response 200**
```json
{
  "teams": [
    {
      "id": "team_abc123",
      "name": "Data Pipeline",
      "description": "Automated data analysis pipeline",
      "workflow_mode": "sequential",
      "agent_ids": ["ag_custom_abc123", "ag_custom_def456"],
      "created_at": 1780875300
    }
  ]
}
```

### `POST /api/teams`

Create a new team with selected Agents and workflow mode.

**Request**
```json
{
  "name": "Data Pipeline",
  "description": "Automated data analysis pipeline",
  "workflow_mode": "sequential",
  "agent_ids": ["ag_custom_abc123", "ag_custom_def456"]
}
```

`workflow_mode` options:
- `sequential` — Agent A → B → C sequential pipeline
- `manager` — PM mode: one agent acts as PM, decomposes tasks and dispatches

**Response 201**
```json
{
  "id": "team_abc123",
  "name": "Data Pipeline",
  "created_at": 1780875300
}
```

### `GET /api/teams/{team_id}`

Get a single team with member details.

### `PUT /api/teams/{team_id}`

Update a team. Full replace of agent_ids and workflow_mode.

### `DELETE /api/teams/{team_id}`

Delete a team and its members.

**Response 200**
```json
{"ok": true}
```

### `POST /api/teams/{team_id}/run`

Run a team workflow. The engine executes based on `workflow_mode`:
- **sequential**: executes agents in order A→B→C, passing context automatically
- **manager**: a PM Agent decomposes the task, dispatches to sub-agents, then merges results

**Request**
```json
{
  "input": "Analyze this CSV data and generate a report..."
}
```

**Response 202**
```json
{
  "run_id": "wr_abc123",
  "status": "running"
}
```

### `GET /api/teams/{team_id}/runs`

List runs for a team (most recent first).

**Response 200**
```json
{
  "runs": [
    {
      "id": "wr_abc123",
      "status": "completed",
      "mode": "sequential",
      "created_at": 1780875300
    }
  ]
}
```

### `GET /api/teams/runs/{run_id}`

Get a single workflow run with all step details.

**Response 200**
```json
{
  "id": "wr_abc123",
  "team_id": "team_abc123",
  "mode": "sequential",
  "status": "completed",
  "input_data": "Analyze this CSV...",
  "result": "# Final Report\n\n...",
  "error": null,
  "steps": [
    {
      "step_index": 0,
      "agent_label": "Data Parser",
      "status": "completed",
      "input_data": "Analyze this CSV...",
      "output_data": "Parsed data summary...",
      "error": null
    },
    {
      "step_index": 1,
      "agent_label": "Report Writer",
      "status": "completed",
      "input_data": "Parsed data summary...",
      "output_data": "# Final Report\n\n...",
      "error": null
    }
  ],
  "created_at": 1780875300,
  "updated_at": 1780875350
}
```

**Status values**: `running`, `completed`, `failed`, `cancelled`
```

**Errors**
- `404` — task not found (or owned by another user)

---

## 6. Error Format

All non-2xx responses use the same shape:

```json
{"detail": "human-readable error message"}
```

`detail` is **safe to display to end users** — it does not leak stack traces, internal paths, or implementation details.

---

## 7. Rate Limits / Quotas (v1)

**None.** A production deployment should add:
- Per-user daily task quota (e.g. 50 / day)
- Per-IP upload throttle
- LLM cost tracking against per-user budget

These are deliberately out of v1 scope per the [plan](../../.plans/agent-as-service-plan.md).

---

## 8. CORS

The gateway accepts cross-origin requests from any origin (`*`) with credentials
allowed. Tighten this in production by setting `allow_origins` in
`gateway/app.py`.
