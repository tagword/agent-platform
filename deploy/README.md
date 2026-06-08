# Agent Platform — Docker Deployment

## Quick start

```bash
cd agent-platform/deploy
cp .env.example .env
# Edit .env to set real secrets:
#   - TASKAGENT_HMAC_SECRET
#   - AGENT_PLATFORM_JWT_SECRET

docker compose up -d
docker compose ps
docker compose logs -f

# Verify
curl http://localhost:8780/health
curl http://localhost:8770/health    # only on docker host; not exposed externally
```

## Stop / reset

```bash
docker compose down              # keep volumes
docker compose down -v           # also delete uploaded files and task history
```

## LLM configuration

The compose file does **not** include an LLM. You must mount an LLM config
into TaskAgent before it can do real work:

```bash
# On the host, prepare your models config
mkdir -p ./taskagent-config
cat > ./taskagent-config/seed.models.json <<'EOF'
[
  {
    "id": "default",
    "name": "deepseek",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-v4-flash",
    "api_key": "sk-YOUR_KEY",
    "auth_scheme": "Bearer",
    "provider": "deepseek"
  }
]
EOF
```

Then add a volume mount to the `taskagent` service in `docker-compose.yml`:

```yaml
volumes:
  - ./taskagent-config/seed.models.json:/root/.taskagent/config/seed.models.json:ro
```

…and restart: `docker compose up -d taskagent`.

## Serving the WebUI

The compose file does not serve `webui/` — that's static files, best
handled by a reverse proxy in front of the gateway. For development:

```bash
cd ../webui
python -m http.server 8080
# → http://localhost:8080/index.html
# Edit <meta name="api-base" content="http://localhost:8780"> in index.html
```

## Production checklist

- [ ] Reverse proxy (Caddy / Traefik / nginx) with TLS in front of gateway:8780
- [ ] Real secrets in `.env` (never commit real `.env`)
- [ ] Real LLM config mounted into taskagent
- [ ] Backup of `gateway-data` and `taskagent-data` volumes
- [ ] Health monitoring (compose `healthcheck` is a starting point)
