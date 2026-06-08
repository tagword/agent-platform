#!/usr/bin/env bash
# ============================================================================
# Agent Platform — Production Quick Start
# ============================================================================
# Usage:
#   ./start.sh               # First-time setup + deploy
#   ./start.sh up            # Start (after initial setup)
#   ./start.sh down          # Stop
#   ./start.sh logs          # Tail logs
#   ./start.sh reset         # Stop + delete volumes (data loss!)
# ============================================================================
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

case "${1:-setup}" in
  up)
    exec docker compose up -d
    ;;
  down)
    exec docker compose down
    ;;
  logs)
    exec docker compose logs -f
    ;;
  reset)
    docker compose down -v
    echo "Volumes deleted. Run './start.sh' for fresh setup."
    ;;
  setup|*)
    echo "=== Agent Platform — First-time Setup ==="

    # 1. Check .env
    if [ ! -f .env ]; then
      cp .env.example .env
      echo "[!] Created .env from .env.example"
      echo "    >>> Edit .env and set REAL secrets before deploying <<<"
      echo ""
      # Generate random secrets
      JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
      HMAC_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
      if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|replace-with-a-random-64-char-hex-string|$JWT_SECRET|" .env
        sed -i '' "s|replace-with-another-random-64-char-hex-string|$HMAC_SECRET|" .env
      else
        sed -i "s|replace-with-a-random-64-char-hex-string|$JWT_SECRET|" .env
        sed -i "s|replace-with-another-random-64-char-hex-string|$HMAC_SECRET|" .env
      fi
      echo "[✓] Auto-generated JWT and HMAC secrets in .env"
    fi

    # 2. Check LLM config
    if [ ! -f config/seed.models.json ]; then
      cp config/seed.models.json.example config/seed.models.json
      echo "[!] Created config/seed.models.json from example"
      echo "    >>> Edit config/seed.models.json and set your LLM api_key <<<"
      exit 1
    fi

    # 3. Validate
    if grep -q "YOUR_DEEPSEEK_API_KEY" config/seed.models.json 2>/dev/null; then
      echo "[!] config/seed.models.json still has placeholder API key"
      echo "    >>> Edit it and set your real API key <<<"
      exit 1
    fi

    # 4. Start
    echo "[✓] All checks passed. Starting..."
    docker compose up -d
    echo ""
    echo "=== Services ==="
    docker compose ps
    echo ""
    echo "Open: http://localhost  (HTTP; see deploy/README.md for HTTPS setup)"
    echo ""
    echo "Tail logs:  docker compose logs -f"
    echo "Stop:       docker compose down"
    ;;
esac
