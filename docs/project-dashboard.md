# Agent Platform — Project Dashboard

> 项目全景视图。最后更新：2026-06-10

---

## 技术栈

| 层 | 技术 | 版本 |
|----|------|------|
| WebUI | 纯静态 HTML/CSS/JS + marked.js | — |
| API Gateway | FastAPI + uvicorn | 0.1.0 |
| 鉴权 | JWT（自签 HMAC-SHA256） | 7天过期 |
| 数据库 | SQLite（WAL 模式） | — |
| 文件存储 | 本地文件系统 | ~/.agent-platform/uploads/ |
| 任务引擎 | TaskAgent（外部） | — |
| LLM 引擎 | Seed（外部） | — |

## 目录结构

```
agent-platform/
├── gateway/                    # FastAPI 应用
│   ├── app.py                  # 装配入口
│   ├── config.py               # 环境变量配置
│   ├── db/
│   │   ├── repo.py             # SQLite 数据访问层
│   │   └── schema.sql          # 建表 DDL
│   ├── auth/
│   │   ├── deps.py             # FastAPI Depends（get_current_user）
│   │   ├── jwt_utils.py        # JWT 签发/验证
│   │   └── password.py         # bcrypt 密码
│   ├── routes/
│   │   ├── auth.py             # register / login / me
│   │   ├── uploads.py          # 文件上传/查询
│   │   ├── agents.py           # Agent 模板列表
│   │   ├── tasks.py            # 同步/异步任务
│   │   ├── tools.py            # GET /api/available-tools
│   │   ├── user_agents.py      # Agent CRUD（用户自定义）
│   │   └── teams.py            # Team CRUD + 运行
│   ├── parsers/                # CSV/Excel/JSON 解析器
│   ├── taskagent_client.py     # TaskAgent HTTP 客户端
│   ├── async_runner.py         # 异步任务后台线程
│   └── seed_templates/         # Skill markdown 文件
├── webui/                      # 静态 SPA
│   ├── index.html              # 入口
│   ├── style.css               # 样式
│   └── app.js                  # 逻辑
├── deploy/                     # Docker 部署
├── docs/
│   ├── API.md                  # API 文档
│   ├── DEPLOY.md               # 部署文档
│   └── project-dashboard.md    # 本文件
├── tests/                      # pytest 测试
└── scripts/                    # 工具脚本
```

## 功能模块清单

### ✅ 已完成

| 模块 | 状态 | 关键文件 |
|------|------|---------|
| 用户注册/登录/鉴权 | ✅ | `routes/auth.py` |
| JWT 签发与验证 | ✅ | `auth/jwt_utils.py` |
| 文件上传（CSV/Excel/JSON） | ✅ | `routes/uploads.py`, `parsers/` |
| Agent 模板列表 | ✅ | `routes/agents.py` |
| 任务触发（同步/异步） | ✅ | `routes/tasks.py` |
| 任务状态轮询 | ✅ | `routes/tasks.py`, `async_runner.py` |
| Agent CRUD（用户自定义） | ✅ | `routes/user_agents.py` |
| 可用工具列表 | ✅ | `routes/tools.py` |
| Team CRUD | ✅ | `routes/teams.py` |
| 工作流引擎（顺序流水线） | ✅ | `routes/teams.py` `run_workflow` |
| 工作流引擎（管家模式） | ✅ | `routes/teams.py` `run_manager_mode` |
| Team Run + 状态轮询 | ✅ | `routes/teams.py` |
| WebUI 基础页（首页/任务/上传） | ✅ | `webui/` |
| WebUI Agent 管理页 | ✅ | `webui/` |
| WebUI Team 看板 | ✅ | `webui/` |
| 移动端底部 Tab 导航 | ✅ | `webui/style.css` |
| Markdown 报告渲染 | ✅ | `webui/app.js` (marked.js) |
| Docker Compose 部署 | ✅ | `deploy/` |
| 生产部署文档 | ✅ | `docs/DEPLOY.md` |
| 端到端测试 | ✅ | `.scripts/e2e-webui.py` |

### 📋 Todo / 后续

| 事项 | 优先级 | 备注 |
|------|--------|------|
| 任务取消 API | P2 | 当前只有轮询，无取消 |
| Agent 性能统计 | P2 | 调用次数/成功率/耗时 |
| 工作流预设模板 | P3 | 常用工作流一键创建 |
| 导出报告为 PDF | P3 | 需引入 wkhtmltopdf |
| 行级权限（RBAC） | P3 | 当前 user_id 过滤已够用 |

## 数据模型

```
users (id, email, name, password_hash, created_at)
uploads (id, user_id, filename, content_type, size, parsed_json, created_at)
tasks (id, user_id, agent_id, agent_params, status, result, error, created_at, updated_at)
user_agents (id, user_id, name, description, tools_json, persona, config, created_at, updated_at)
teams (id, name, description, workflow_mode, agent_ids, created_at, updated_at)
team_members (id, team_id, agent_id, role, created_at)
workflow_runs (id, team_id, mode, status, input_data, result, error, created_at, updated_at)
workflow_steps (id, run_id, agent_id, agent_label, step_index, input_data, output_data, status, error, created_at, updated_at)
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AGENT_PLATFORM_HOME` | `~/.agent-platform` | 数据目录 |
| `AGENT_PLATFORM_JWT_SECRET` | — | **必填** JWT 签名密钥 |
| `AGENT_PLATFORM_JWT_EXPIRY_DAYS` | `7` | Token 有效期 |
| `AGENT_PLATFORM_TASKAGENT_URL` | `http://127.0.0.1:8770` | TaskAgent 地址 |
| `AGENT_PLATFORM_TASKAGENT_HMAC_SECRET` | `dev-secret` | Webhook HMAC 密钥 |
| `AGENT_PLATFORM_MAX_UPLOAD_MB` | `10` | 单文件上限 |
