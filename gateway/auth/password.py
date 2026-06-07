"""Password hashing via passlib bcrypt.

Why passlib + bcrypt==4.0.1: passlib's bcrypt detection breaks on bcrypt>=4.1.
We pin bcrypt=4.0.1 in pyproject.toml for forward-compat.
"""

from __future__ import annotations

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception:
        return False
