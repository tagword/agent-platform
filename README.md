# Agent Platform

User-facing gateway on top of [TaskAgent](../taskagent/).

## What it does

- Multi-user auth (JWT)
- File upload + parsing (CSV / Excel / JSON)
- Trigger Agent tasks (currently: data analysis report)
- View task history and reports

## Quick start

```bash
cd agent-platform
pip install -e ../taskagent -e .

export AGENT_PLATFORM_HOME=~/.agent-platform
export AGENT_PLATFORM_JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
export AGENT_PLATFORM_TASKAGENT_URL=http://127.0.0.1:8770
export AGENT_PLATFORM_TASKAGENT_HMAC_SECRET=dev-secret  # same as TaskAgent's TASKAGENT_WEBHOOK_SECRET

python -m gateway.app
# → http://127.0.0.1:8780
```

Open `webui/index.html` in a browser (or `python -m http.server` from `webui/`).

See [plan](../.plans/agent-as-service-plan.md) for design details.
