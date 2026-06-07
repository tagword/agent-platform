"""FastAPI dependency: extract current user from Authorization header."""

from __future__ import annotations

from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, status

from gateway.auth.jwt_utils import decode_token
from gateway.db import repo


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """FastAPI dependency: returns user dict (without password_hash).

    Use:    def my_route(user = Depends(get_current_user)): ...
    """
    if not authorization:
        raise _unauthorized("Missing Authorization header")
    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise _unauthorized("Authorization must be 'Bearer <token>'")
    token = parts[1]
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token expired")
    except jwt.PyJWTError:
        raise _unauthorized("Invalid token")
    user_id = payload.get("sub")
    if not user_id:
        raise _unauthorized("Token missing subject")
    user = repo.get_user_by_id(user_id)
    if not user:
        raise _unauthorized("User no longer exists")
    # Strip password_hash before returning
    user.pop("password_hash", None)
    return user
