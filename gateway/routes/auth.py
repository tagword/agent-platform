"""Auth routes: /api/auth/register, /api/auth/login, /api/auth/me."""

from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from gateway.auth.deps import get_current_user
from gateway.auth.jwt_utils import create_token
from gateway.auth.password import hash_password, verify_password
from gateway.db import repo

router = APIRouter(prefix="/api/auth", tags=["auth"])


# --- Request/Response models ------------------------------------------------

class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=6, max_length=200)
    name: str = Field(..., min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: str
    password: str


class UserPublic(BaseModel):
    id: str
    email: str
    name: str
    created_at: int


class TokenResponse(BaseModel):
    token: str
    user: UserPublic
    expires_in_hours: int


# --- Validation helpers -----------------------------------------------------

# Simple email regex — strict RFC 5322 is overkill for an internal-ish service
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(email: str) -> str:
    e = (email or "").strip()
    if not _EMAIL_RE.match(e):
        raise HTTPException(status_code=400, detail="Invalid email format")
    return e


# --- Routes -----------------------------------------------------------------

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest) -> TokenResponse:
    email = _validate_email(body.email)
    if repo.get_user_by_email(email):
        raise HTTPException(status_code=409, detail="Email already registered")
    pw_hash = hash_password(body.password)
    user = repo.create_user(email=email, password_hash=pw_hash, name=body.name)
    from gateway import config  # avoid circular at import
    token = create_token(user["id"])
    return TokenResponse(
        token=token,
        user=UserPublic(**user),
        expires_in_hours=config.JWT_EXPIRE_HOURS,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    email = _validate_email(body.email)
    user = repo.get_user_by_email(email)
    # Constant-ish time: always run verify even if user not found
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    from gateway import config
    token = create_token(user["id"])
    user.pop("password_hash", None)
    return TokenResponse(
        token=token,
        user=UserPublic(**user),
        expires_in_hours=config.JWT_EXPIRE_HOURS,
    )


@router.get("/me", response_model=UserPublic)
async def me(user: dict = Depends(get_current_user)) -> UserPublic:
    return UserPublic(**user)
