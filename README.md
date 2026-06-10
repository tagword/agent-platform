# Agent Platform

> **多用户 Agent-as-a-Service 网关** — 让不懂 Agent 的业务人员能用浏览器上传数据、拿到 AI 生成的报告。

在 [TaskAgent](../taskagent/)（无头任务调度）之上提供：

### 🧑‍💻 用户功能
- **用户系统**：JWT 注册/登录，每个用户独立数据
- **文件上传**：CSV / Excel / JSON，服务端自动解析
- **Agent 模板库**：可选多种 Skill（数据分析报告 / 代码审查 / 文档摘要）
- **任务触发**：同步 / 异步双模式，30s 内任务 sync，长任务 async + 轮询
- **自定义 Agent**：创建自定义 Agent，勾选可用工具，编写人设 prompt
- **团队协作**：创建团队，组合多个 Agent，选择工作流模式
- **工作流引擎**：顺序流水线（A→B→C 自动传上下文）或管家模式（PM 拆→派→合）
- **Web UI**：纯静态 SPA，零构建链，含 Agent 管理页 + 团队运行看板

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

Gateway 支持的全部环境变量见 [Project Dashboard](docs/project-dashboard.md#环境变量)。

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
| WebUI（纯静态 SPA）| `webui/` | ✅ 含 Agent 管理 + 团队看板 + 移动端 Tab |
| Gateway（用户面 API）| `gateway/` | ✅ FastAPI + JWT + SQLite + 文件解析 + 工作流引擎 |
| TaskAgent（任务引擎）| `../taskagent/` | ✅ 已就绪（外部依赖） |
| Seed（LLM 执行引擎）| `../seed/` | ✅ 已就绪（外部依赖） |
| Seed Tools（工具集）| `../seed-tools/` | ✅ 已就绪（外部依赖） |

### API 端点概览

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
| `GET` | `/api/available-tools` | 列出所有可用工具 |
| `GET` | `/api/user-agents` | 我的自定义 Agent 列表 |
| `POST` | `/api/user-agents` | 创建自定义 Agent |
| `PUT` | `/api/user-agents/{id}` | 更新自定义 Agent |
| `DELETE` | `/api/user-agents/{id}` | 删除自定义 Agent |
| `GET` | `/api/teams` | 我的团队列表 |
| `POST` | `/api/teams` | 创建团队 |
| `PUT` | `/api/teams/{id}` | 更新团队 |
| `DELETE` | `/api/teams/{id}` | 删除团队 |
| `POST` | `/api/teams/{id}/run` | 运行团队（工作流）|
| `GET` | `/api/teams/{id}/runs` | 团队运行历史 |
| `GET` | `/api/teams/runs/{run_id}` | 单次运行详情（含步骤）|

完整 API 文档：[docs/API.md](docs/API.md)
部署文档：[docs/DEPLOY.md](docs/DEPLOY.md)
Docker Compose：[deploy/docker-compose.yml](deploy/docker-compose.yml)
项目全景：[docs/project-dashboard.md](docs/project-dashboard.md)

## 已内置的 Agent 模板

| ID | 名称 | 输入 | 用途 |
|----|------|------|------|
| `data-analysis-report` | 数据分析报告 | CSV/Excel/JSON | 业务分析、报表生成 |
| `code-review` | 代码审查 | 代码文件 | PR 辅助、代码质量评估 |
| `doc-summary` | 文档摘要 | 长文档 | 快速理解、要点提取 |

## 工作流模式

团队支持两种工作流模式：

| 模式 | 说明 |
|------|------|
| **顺序流水线** | Agent A → B → C 依次执行，上一步的输出自动作为下一步的输入 |
| **管家模式** | PM Agent 拆解任务 → 派发给各 Agent → 汇总合并最终结果 |

## 测试

```bash
# 后端 (40 tests, ~17s)
cd agent-platform && pytest

# 端到端浏览器 (需 playwright + 三个服务在跑)
python3 .scripts/e2e-webui.py
```

## 已知边界（v1 显式不做）

- ❌ 计费 / 订阅 / 限额
- ❌ 任务取消（当前只支持轮询）
- ❌ Agent / Team 性能统计
- ❌ 对象存储 / 邮件通知
- ❌ 国际化（先中文）
- ❌ 流式输出（SSE / WebSocket 推送）

详见 [plan](../../.plans/agent-as-service-plan.md)。

## 部署

- [本地](docs/DEPLOY.md#mode-1-local-development-no-docker)
- [Docker Compose](deploy/README.md)
- [systemd](docs/DEPLOY.md#mode-3-systemd-bare-metal-linux)
