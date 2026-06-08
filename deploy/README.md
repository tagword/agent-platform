# Agent Platform — 生产部署

## 架构

```
用户 → Caddy (443/80) ──┬── /* → webui (静态文件 SPA)
                        └── /api/* → Gateway (FastAPI) → TaskAgent (Starlette) → LLM
```

所有服务通过 Docker Compose 管理，Caddy 提供：
- **自动 HTTPS**（Let's Encrypt，有域名时）
- **静态文件服务**（webui/ 目录）
- **API 反向代理**（/api/* → gateway:8780）

## 快速开始（3 分钟）

### 1. 准备环境

```bash
cd agent-platform/deploy

# 一键部署
./start.sh
```

首次运行会自动：
1. 生成 `.env` 并填入自动随机的 JWT/HMAC 密钥
2. 检查 LLM 配置

**如果看到 `exit 1` + 提示** → 按提示编辑 `config/seed.models.json`，填入你的 LLM API key：

```bash
# 编辑 LLM 配置
vim config/seed.models.json
# 把 "sk-YOUR_DEEPSEEK_API_KEY_HERE" 换成真实的 key
```

然后重新运行：

```bash
./start.sh
```

### 2. 验证

```bash
# 检查服务状态
docker compose ps

# 健康检查
curl http://localhost/health
# → {"ok":true,"service":"agent-platform","version":"0.1.0"}

# 注册新用户
curl -X POST http://localhost/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"admin123","name":"Admin"}'
```

### 3. 打开浏览器

```
http://localhost
```

## HTTPS（生产环境）

默认 Caddyfile 只监听 HTTP (`:80`)。要启用 HTTPS：

### 方案 1：修改 Caddyfile（推荐）

编辑 `Caddyfile`，将第一行 `:80` 替换为你的域名：

```caddyfile
your-domain.com {
    # ... 其余配置保持不变
}
```

Caddy 会自动申请 Let's Encrypt 证书并监听 443 端口。
访问 `https://your-domain.com` 即可。

### 方案 2：外部反向代理

在 Caddy 前面放 nginx / Cloudflare / 负载均衡器，由它们处理 TLS 终止。

## 日常运维

```bash
./start.sh logs      # 查看日志
./start.sh down      # 停止
./start.sh up        # 启动
./start.sh reset     # 停止 + 删除数据（不可恢复！）
```

或者直接使用 docker compose：

```bash
cd deploy
docker compose ps
docker compose logs -f gateway
docker compose restart taskagent
```

## 备份

```bash
# 备份数据库 + 上传文件
docker run --rm -v ap_gateway-data:/data -v $(pwd):/backup alpine \
  tar -czf /backup/gateway-$(date +%F).tar.gz -C /data .
docker run --rm -v ap_taskagent-data:/data -v $(pwd):/backup alpine \
  tar -czf /backup/taskagent-$(date +%F).tar.gz -C /data .
```

## 升级

```bash
cd agent-platform
git pull

cd deploy
docker compose down
docker compose build --no-cache
docker compose up -d
```

## 扩展（单机 → 多机）

当前架构是单机部署。如果要扩展：

| 场景 | 方案 |
|------|------|
| 高可用 | 加 MySQL/PostgreSQL 替换 SQLite，Redis 替换内存队列 |
| 静态文件分离 | 上传到 S3/MinIO |
| 多副本 | Gateway/TaskAgent 水平扩展，前面加负载均衡 |
| 监控 | Prometheus + Grafana（FastAPI 自带 /metrics 端点）|

## 安全注意事项

1. **.env 文件** — 包含 JWT 签名密钥 + HMAC 共享密钥。永远不要提交到 git。
2. **seed.models.json** — 包含 LLM API key。已在 `.gitignore` 中。
3. **端口暴露** — 默认只暴露 80/443。Gateway 和 TaskAgent 的管理端口只在内网。
4. **防火墙** — 建议在云服务器安全组中只开放 80/443。
