# Agent Platform — Deployment Guide

This guide covers three deployment modes, from simplest to most production-ready:

1. **Local dev** — run both services on your laptop
2. **Docker Compose** — single-host deployment with two containers
3. **systemd** — bare-metal Linux deployment (Ubuntu/Debian/RHEL)

For all modes, the architecture is identical:

```
┌──────────────┐  HTTP   ┌──────────────┐  HTTP   ┌──────────────┐
│  Web Browser │ ──────► │   Gateway    │ ──────► │  TaskAgent   │
│  (webui/)    │   8780  │  (FastAPI)   │   8770  │  (Starlette) │
└──────────────┘         └──────┬───────┘         └──────┬───────┘
                                │                       │
                          ~/.agent-platform       ~/.taskagent
                          ├ platform.db           ├ config/
                          ├ uploads/              ├ releases/
                          └ config/               └ platform.db
```

---

## Mode 1: Local Development (no Docker)

### Prerequisites
- Python 3.9+
- pip / virtualenv
- An LLM API key (e.g. deepseek, openai-compatible)

### Steps

```bash
# 1. Install all packages in editable mode
cd /path/to/agent
pip install -e ./seed -e ./seed-tools -e ./taskagent -e ./agent-platform

# 2. Set up a TaskAgent data root
mkdir -p ~/.taskagent/config
cat > ~/.taskagent/config/jobs.json <<'EOF'
{
  "jobs": {
    "data-analysis-report": {
      "enabled": true,
      "agent_id": "default",
      "instruction_bundle": "data-analysis-report@v1",
      "instruction_mode": "bootstrap",
      "concurrency": 2,
      "timeout_sec": 600,
      "message_template": "{{message}}"
    }
  }
}
EOF

# 3. Configure TaskAgent LLM (edit with your key/base_url/model)
cat > ~/.taskagent/config/seed.models.json <<'EOF'
[
  {
    "id": "default",
    "name": "deepseek",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-v4-flash",
    "api_key": "sk-YOUR_KEY_HERE",
    "auth_scheme": "Bearer",
    "provider": "deepseek"
  }
]
EOF

# 4. Publish the report-writer release
taskagent release-publish \
  agent-platform/gateway/seed_templates/data-analysis-report@v1.md \
  --name data-analysis-report --version v1

# 5. Start TaskAgent
export TASKAGENT_HOME=$HOME/.taskagent
export SEED_PROJECT_ROOT=$HOME/.taskagent
export TASKAGENT_SYNC_RUN_ENABLED=1
export TASKAGENT_WEBHOOK_SECRET=dev-secret
taskagent serve --port 8770 &

# 6. Start Gateway
export AGENT_PLATFORM_HOME=$HOME/.agent-platform
export AGENT_PLATFORM_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export AGENT_PLATFORM_TASKAGENT_URL=http://127.0.0.1:8770
export AGENT_PLATFORM_TASKAGENT_HMAC_SECRET=dev-secret
uvicorn gateway.app:app --host 0.0.0.0 --port 8780 &

# 7. Open webui
cd agent-platform/webui
python -m http.server 8080
# → http://localhost:8080/index.html
# (The webui defaults to api at hostname:8780. Override via
#  <meta name="api-base" content="http://localhost:8780"> in index.html
#  if hostname differs.)
```

---

## Mode 2: Docker Compose (single host)

### Layout

```
agent-platform-deploy/
├── docker-compose.yml
├── .env
├── gateway-config/
│   └── jobs.json     # unused (gateway has no jobs)
├── taskagent-config/
│   ├── jobs.json
│   └── seed.models.json
└── seed-templates/
    └── data-analysis-report@v1.md
```

### `docker-compose.yml`

```yaml
version: "3.9"

services:
  taskagent:
    image: python:3.11-slim
    container_name: ap-taskagent
    working_dir: /app
    volumes:
      - ../seed:/app/seed:ro
      - ../seed-tools:/app/seed-tools:ro
      - ../taskagent:/app/taskagent:ro
      - taskagent-data:/root/.taskagent
    environment:
      - TASKAGENT_HOME=/root/.taskagent
      - SEED_PROJECT_ROOT=/root/.taskagent
      - TASKAGENT_SYNC_RUN_ENABLED=1
      - TASKAGENT_WEBHOOK_SECRET=${TASKAGENT_HMAC_SECRET}
    command: >
      bash -c "
        pip install -e /app/seed -e /app/seed-tools -e /app/taskagent &&
        taskagent release-publish /seed-templates/data-analysis-report@v1.md \
          --name data-analysis-report --version v1 &&
        taskagent serve --host 0.0.0.0 --port 8770
      "
    volumes_extra:
      - ./seed-templates:/seed-templates:ro
    ports:
      - "127.0.0.1:8770:8770"
    restart: unless-stopped

  gateway:
    image: python:3.11-slim
    container_name: ap-gateway
    working_dir: /app
    depends_on:
      - taskagent
    volumes:
      - ../seed:/app/seed:ro
      - ../seed-tools:/app/seed-tools:ro
      - ../taskagent:/app/taskagent:ro
      - ../agent-platform:/app/gateway:ro
      - gateway-data:/root/.agent-platform
    environment:
      - AGENT_PLATFORM_HOME=/root/.agent-platform
      - AGENT_PLATFORM_JWT_SECRET=${AGENT_PLATFORM_JWT_SECRET}
      - AGENT_PLATFORM_TASKAGENT_URL=http://taskagent:8770
      - AGENT_PLATFORM_TASKAGENT_HMAC_SECRET=${TASKAGENT_HMAC_SECRET}
    command: >
      bash -c "
        pip install -e /app/seed -e /app/seed-tools -e /app/taskagent -e /app/gateway &&
        uvicorn gateway.app:app --host 0.0.0.0 --port 8780
      "
    ports:
      - "0.0.0.0:8780:8780"
    restart: unless-stopped

volumes:
  taskagent-data:
  gateway-data:
```

> **Note**: A production compose file should also include a reverse proxy
> (Caddy / Traefik / nginx) in front of the gateway for TLS, and a static
> file container serving `agent-platform/webui/`.

### `.env`

```bash
TASKAGENT_HMAC_SECRET=please-generate-with-secrets-token-urlsafe-32
AGENT_PLATFORM_JWT_SECRET=please-generate-another-one
```

```bash
docker compose up -d
docker compose logs -f
```

---

## Mode 3: systemd (bare-metal Linux)

### `/etc/systemd/system/taskagent.service`

```ini
[Unit]
Description=TaskAgent
After=network.target

[Service]
Type=simple
User=ap
Group=ap
WorkingDirectory=/opt/ap
Environment="TASKAGENT_HOME=/var/lib/ap/taskagent"
Environment="SEED_PROJECT_ROOT=/var/lib/ap/taskagent"
Environment="TASKAGENT_SYNC_RUN_ENABLED=1"
Environment="TASKAGENT_WEBHOOK_SECRET=__HMAC_SECRET__"
ExecStart=/opt/ap/venv/bin/taskagent serve --host 127.0.0.1 --port 8770
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### `/etc/systemd/system/agent-platform-gateway.service`

```ini
[Unit]
Description=Agent Platform Gateway
After=network.target taskagent.service

[Service]
Type=simple
User=ap
Group=ap
WorkingDirectory=/opt/ap
Environment="AGENT_PLATFORM_HOME=/var/lib/ap/gateway"
Environment="AGENT_PLATFORM_JWT_SECRET=__JWT_SECRET__"
Environment="AGENT_PLATFORM_TASKAGENT_URL=http://127.0.0.1:8770"
Environment="AGENT_PLATFORM_TASKAGENT_HMAC_SECRET=__HMAC_SECRET__"
ExecStart=/opt/ap/venv/bin/uvicorn gateway.app:app --host 0.0.0.0 --port 8780
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo useradd -r -s /bin/false ap
sudo install -d -o ap -g ap /var/lib/ap/taskagent /var/lib/ap/gateway
sudo install -d -o ap -g ap /opt/ap
# ... copy code, install deps, set up jobs.json / seed.models.json
sudo systemctl daemon-reload
sudo systemctl enable --now taskagent agent-platform-gateway
sudo systemctl status taskagent agent-platform-gateway
```

---

## Environment Variables Reference

### Gateway (`AGENT_PLATFORM_*`)

| Variable | Default | Required | Notes |
|----------|---------|----------|-------|
| `AGENT_PLATFORM_HOME` | `~/.agent-platform` | no | Data root: DB, uploads |
| `AGENT_PLATFORM_HOST` | `0.0.0.0` | no | Bind address |
| `AGENT_PLATFORM_PORT` | `8780` | no | HTTP port |
| `AGENT_PLATFORM_JWT_SECRET` | (auto-generated) | **YES in prod** | Token signing key |
| `AGENT_PLATFORM_JWT_EXPIRE_HOURS` | `168` (7d) | no | Token TTL |
| `AGENT_PLATFORM_TASKAGENT_URL` | `http://127.0.0.1:8770` | no | TaskAgent base URL |
| `AGENT_PLATFORM_TASKAGENT_HMAC_SECRET` | `dev-secret` | **YES in prod** | Webhook shared secret |
| `AGENT_PLATFORM_TASKAGENT_TIMEOUT_SEC` | `180` | no | Sync `/tasks/run` timeout |
| `AGENT_PLATFORM_MAX_UPLOAD_MB` | `10` | no | Upload size limit |
| `AGENT_PLATFORM_LOG_LEVEL` | `INFO` | no | |

### TaskAgent (`TASKAGENT_*`)

| Variable | Default | Required | Notes |
|----------|---------|----------|-------|
| `TASKAGENT_HOME` | `~/.taskagent` | no | Data root |
| `TASKAGENT_PORT` | `8770` | no | |
| `TASKAGENT_WEBHOOK_SECRET` | (none) | **YES in prod** | Inbound HMAC |
| `TASKAGENT_SYNC_RUN_ENABLED` | `0` | **YES for this app** | Enable `/tasks/run` |
| `TASKAGENT_QUEUE_BACKEND` | `memory` | no | `memory` or `redis` (B+ tier) |
| `TASKAGENT_MAX_CONCURRENT` | `8` | no | |
| `TASKAGENT_DLQ_ENABLED` | `0` | no | B+ tier |

### LLM (consumed by TaskAgent via `seed.models.json`)

Either configure `~/.taskagent/config/seed.models.json` or set env vars:
`SEED_LLM_BASEURL`, `SEED_LLM_MODEL`, `SEED_LLM_API_KEY`, `SEED_LLM_AUTH_SCHEME`.

---

## Secret Generation

```bash
# JWT secret
python -c "import secrets; print(secrets.token_urlsafe(32))"

# HMAC secret (must match between gateway and taskagent)
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## First-Run Checklist

1. ✅ TaskAgent healthy: `curl http://localhost:8770/health` → `{"ok":true}`
2. ✅ Gateway healthy: `curl http://localhost:8780/health` → `{"ok":true}`
3. ✅ Job registered: `curl http://localhost:8770/jobs` → contains `data-analysis-report`
4. ✅ Agent template seeded: register a user, then `GET /api/agents` returns the template
5. ✅ End-to-end: upload a CSV, run the task, get a report

---

## Backup

```bash
# Gateway data
tar -czf backup-gateway-$(date +%F).tar.gz \
    ~/.agent-platform/platform.db \
    ~/.agent-platform/uploads \
    ~/.agent-platform/config

# TaskAgent data
tar -czf backup-taskagent-$(date +%F).tar.gz \
    ~/.taskagent/platform.db \
    ~/.taskagent/config \
    ~/.taskagent/releases
```

Uploads and reports can be large; consider incremental backups or offload
to S3-compatible storage for production.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `401` on every request | JWT secret changed / token expired | Re-login |
| `/api/agents` returns empty | DB not initialized | `init_db()` runs on startup; check logs |
| `/api/tasks/run` returns 502 | TaskAgent unreachable | Check `curl $TASKAGENT_URL/health` |
| `TaskAgent 403` | `TASKAGENT_SYNC_RUN_ENABLED` not set to `1` | Set env var, restart |
| `parse_error: JSON parse error` | Truncated JSON file | Re-export from source |
| `Report contains garbage` | Wrong LLM preset | Check `seed.models.json` |
