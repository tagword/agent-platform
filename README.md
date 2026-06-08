# Agent Platform

> **多用户 Agent-as-a-Service 网关** — 让不懂 Agent 的业务人员能用浏览器上传数据、拿到 AI 生成的报告。

在 [TaskAgent](../taskagent/)（无头任务调度）之上提供：
- **用户系统**：JWT 注册/登录，每个用户独立数据
- **文件上传**：CSV / Excel / JSON，服务端自动解析
- **Agent 模板库**：可选多种 Skill（数据分析报告 / 代码审查 / 文档摘要）
- **Web UI**：纯静态单页应用，零构建链
- **同步 / 异步双模式**：30s 内任务用 sync；长任务用 async + 轮询

```
┌──────────────┐  HTTP   ┌──────────────┐  HTTP   ┌──────────────┐
│  Browser     │ ──────► │   Gateway    │ ──────► │  TaskAgent   │
│  (webui/)    │   8780  │  (FastAPI)   │   8770  │  (Starlette) │
└──────────────┘         └──────┬───────┘         └──────┬───────┘
                                │                       │
                          ~/.agent-platform       ~/.taskagent
```

## 快速开始

### 1. 安装依赖

```bash
cd /path/to/agent
pip install -e ./seed -e ./seed-tools -e ./taskagent -e ./agent-platform
```

### 2. 配置并启动 TaskAgent

```bash
mkdir -p ~/.taskagent/config

# jobs.json — 至少一个 job
cat > ~/.taskagent/config/jobs.json <<'EOF'
{
  "jobs": {
    "data-analysis-report": {
      "enabled": true,
      "instruction_bundle": "data-analysis-report@v1",
      "instruction_mode": "bootstrap",
      "concurrency": 2,
      "timeout_sec": 600,
      "message_template": "{{message}}"
    }
  }
}
EOF

# seed.models.json — 你的 LLM preset
cat > ~/.taskagent/config/seed.models.json <<'EOF'
[{"id": "default", "base_url": "https://api.deepseek.com/v1",
  "model": "deepseek-v4-flash", "api_key": "sk-...",
  "auth_scheme": "Bearer", "provider": "deepseek"}]
EOF

# 发布 skill 到 TaskAgent
taskagent release-publish \
  agent-platform/gateway/seed_templates/data-analysis-report@v1.md \
  --name data-analysis-report --version v1

# 启动
export TASKAGENT_HOME=$HOME/.taskagent
export SEED_PROJECT_ROOT=$HOME/.taskagent
export TASKAGENT_SYNC_RUN_ENABLED=1
export TASKAGENT_WEBHOOK_SECRET=dev-secret
taskagent serve --port 8770 &
```

### 3. 启动 Gateway

```bash
export AGENT_PLATFORM_HOME=$HOME/.agent-platform
export AGENT_PLATFORM_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export AGENT_PLATFORM_TASKAGENT_URL=http://127.0.0.1:8770
export AGENT_PLATFORM_TASKAGENT_HMAC_SECRET=dev-secret
uvicorn gateway.app:app --host 0.0.0.0 --port 8780 &
```

### 4. 打开 WebUI

```bash
cd agent-platform/webui
python -m http.server 8080
# → http://localhost:8080/index.html
# (Webui 默认连 hostname:8780；改地址编辑 <meta name="api-base">)
```

## 架构

| 层 | 包 | 状态 |
|---|---|---|
| WebUI（纯静态 SPA）| `webui/` | ✅ 4 视图 + 移动端底部 Tab + Markdown 渲染 |
| Gateway（用户面 API）| `gateway/` | ✅ FastAPI + JWT + SQLite + 文件解析 |
| TaskAgent（任务引擎）| `../taskagent/` | ✅ 已就绪（外部依赖） |
| Seed（LLM 执行引擎）| `../seed/` | ✅ 已就绪（外部依赖） |
| Seed Tools（工具集）| `../seed-tools/` | ✅ 已就绪（外部依赖） |

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/api/auth/register` | 注册 |
| `POST` | `/api/auth/login` | 登录 |
| `GET` | `/api/auth/me` | 当前用户 |
| `GET` | `/api/agents` | 可用 Agent 模板 |
| `GET` | `/api/agents/{id}` | 单个模板详情 |
| `POST` | `/api/uploads` | 上传文件（multipart）|
| `GET` | `/api/uploads` | 列出我的上传 |
| `GET` | `/api/uploads/{id}` | 上传详情（含解析结果）|
| `POST` | `/api/tasks` | **异步**入队，202 + task_id |
| `POST` | `/api/tasks/run` | **同步**执行，等结果 |
| `GET` | `/api/tasks` | 我的任务列表 |
| `GET` | `/api/tasks/{id}` | 任务详情（含 Markdown 报告）|

完整 API 文档：[docs/API.md](docs/API.md)
部署文档：[docs/DEPLOY.md](docs/DEPLOY.md)
Docker Compose：[deploy/docker-compose.yml](deploy/docker-compose.yml)

## 已内置的 Agent 模板

| ID | 名称 | 输入 | 用途 |
|----|------|------|------|
| `data-analysis-report` | 数据分析报告 | CSV/Excel/JSON | 业务分析、报表生成 |
| `code-review` | 代码审查 | 代码文件 | PR 辅助、代码质量评估 |
| `doc-summary` | 文档摘要 | 长文档 | 快速理解、要点提取 |

新增模板：编辑 `gateway/seed_templates/<id>@<version>.md` + 在 `gateway/db/repo.py` 的 `_seed_default_templates` 注册。

## 测试

```bash
# 后端 (40 tests, ~17s)
pytest

# 端到端浏览器 (需 playwright + 三个服务在跑)
python3 .scripts/e2e-webui.py
```

## 已知边界（v1 显式不做）

- ❌ 计费 / 订阅 / 限额
- ❌ Agent prompt 编辑器（用户不能改 skill）
- ❌ 团队协作 / 报告分享
- ❌ 对象存储 / 邮件通知
- ❌ 国际化（先中文）
- ❌ 流式输出（SSE / WebSocket 推送）

详见 [plan](../../.plans/agent-as-service-plan.md)。

## 部署

- [本地](docs/DEPLOY.md#mode-1-local-development-no-docker)
- [Docker Compose](deploy/README.md)
- [systemd](docs/DEPLOY.md#mode-3-systemd-bare-metal-linux)
