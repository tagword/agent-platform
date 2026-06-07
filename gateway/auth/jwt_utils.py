"""JWT minting and verification."""

from __future__ import annotations

import time
from typing import Any, Optional

import jwt

from gateway import config


def create_token(user_id: str, *, extra_claims: Optional[dict[str, Any]] = None) -> str:
    """Mint a JWT for the given user_id. Default lifetime from config."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": now + config.JWT_EXPIRE_HOURS * 3600,
    }
    if extra_claims:
        payload.update(extra_claims)
    secret = config.get_or_create_jwt_secret()
    return jwt.encode(payload, secret, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT. Raises jwt.PyJWTError on any failure."""
    secret = config.get_or_create_jwt_secret()
    return jwt.decode(token, secret, algorithms=[config.JWT_ALGORITHM])
