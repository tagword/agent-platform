"""Configuration: env vars + defaults. Single source of truth."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Optional


def _default_home() -> Path:
    return Path(os.path.expanduser("~")) / ".agent-platform"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_path(name: str, default: Path) -> Path:
    return Path(os.path.expanduser(os.environ.get(name, str(default))))


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ----- Paths -----
HOME: Path = _env_path("AGENT_PLATFORM_HOME", _default_home())
DB_PATH: Path = HOME / "platform.db"
UPLOADS_DIR: Path = HOME / "uploads"
CONFIG_DIR: Path = HOME / "config"

# ----- HTTP server -----
HOST: str = _env("AGENT_PLATFORM_HOST", "0.0.0.0")
PORT: int = _env_int("AGENT_PLATFORM_PORT", 8780)

# ----- Auth -----
# Secret is required for production. In dev, auto-generate a stable-per-process
# secret so restarts don't invalidate tokens (logged warning).
JWT_SECRET: str = _env("AGENT_PLATFORM_JWT_SECRET", "")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_HOURS: int = _env_int("AGENT_PLATFORM_JWT_EXPIRE_HOURS", 24 * 7)  # 7 days

# ----- TaskAgent integration -----
TASKAGENT_URL: str = _env("AGENT_PLATFORM_TASKAGENT_URL", "http://127.0.0.1:8770")
TASKAGENT_HMAC_SECRET: str = _env("AGENT_PLATFORM_TASKAGENT_HMAC_SECRET", "dev-secret")
# Max seconds to wait for a sync /tasks/run response
TASKAGENT_TIMEOUT_SEC: int = _env_int("AGENT_PLATFORM_TASKAGENT_TIMEOUT_SEC", 180)

# ----- Uploads -----
MAX_UPLOAD_MB: int = _env_int("AGENT_PLATFORM_MAX_UPLOAD_MB", 10)
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".csv", ".xlsx", ".xls", ".json"})

# ----- Logging -----
LOG_LEVEL: str = _env("AGENT_PLATFORM_LOG_LEVEL", "INFO")


def ensure_dirs() -> None:
    """Create required directories (idempotent)."""
    HOME.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def get_or_create_jwt_secret() -> str:
    """Return JWT secret; warn loudly if using ephemeral dev secret."""
    global JWT_SECRET
    if not JWT_SECRET:
        JWT_SECRET = secrets.token_urlsafe(32)
        import logging
        logging.getLogger(__name__).warning(
            "AGENT_PLATFORM_JWT_SECRET not set — generated ephemeral secret. "
            "Tokens will not survive restart. Set this env var for production."
        )
    return JWT_SECRET


def db_path_str() -> str:
    return str(DB_PATH)
