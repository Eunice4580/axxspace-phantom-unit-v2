"""Minimal admin authentication using a signed, expiring token.

A single shared admin password (``settings.admin_password``) is exchanged for a signed
token via ``POST /api/auth/login``. Protected endpoints require that token in the
``Authorization: Bearer <token>`` header. Tokens are signed with ``settings.secret_key``
so they cannot be forged, and they expire after ``settings.token_max_age_seconds``.

Member authentication works the same way but signs ``member:<contributor_id>`` so each
member gets a personal, revocable token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from app.config import settings

_signer = TimestampSigner(settings.secret_key)
_ADMIN_SUBJECT = "axxspace-admin"
_MEMBER_PREFIX = "member:"

# auto_error=False so we can return a clean 401 instead of FastAPI's default.
_bearer = HTTPBearer(auto_error=False)

# Password hashing — PBKDF2-HMAC-SHA256 (stdlib, no extra deps)
_PBKDF2_ITERS = 260_000
_SALT_BYTES   = 32


def hash_password(plain: str) -> str:
    """Return a salted PBKDF2-SHA256 hash of *plain*, encoded as base64."""
    salt = os.urandom(_SALT_BYTES)
    key  = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, _PBKDF2_ITERS)
    return base64.b64encode(salt + key).decode()


def verify_member_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the stored PBKDF2 hash."""
    try:
        data = base64.b64decode(hashed.encode())
        salt, stored_key = data[:_SALT_BYTES], data[_SALT_BYTES:]
        check_key = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, _PBKDF2_ITERS)
        return hmac.compare_digest(check_key, stored_key)
    except Exception:
        return False


def create_admin_token() -> str:
    """Issue a fresh signed admin token."""
    return _signer.sign(_ADMIN_SUBJECT.encode()).decode()


def create_member_token(contributor_id: int) -> str:
    """Issue a fresh signed token for a specific member."""
    subject = f"{_MEMBER_PREFIX}{contributor_id}"
    return _signer.sign(subject.encode()).decode()


def verify_password(password: str) -> bool:
    return password == settings.admin_password


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """FastAPI dependency that rejects requests without a valid admin token."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        subject = _signer.unsign(
            credentials.credentials, max_age=settings.token_max_age_seconds
        ).decode()
    except SignatureExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired, please log in again.",
        ) from exc
    except BadSignature as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        ) from exc
    if subject != _ADMIN_SUBJECT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This token is not an admin token.",
        )
    return _ADMIN_SUBJECT


def require_member(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> int:
    """FastAPI dependency that returns the contributor_id from a valid member token."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Member authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = _signer.unsign(
            credentials.credentials, max_age=settings.token_max_age_seconds
        ).decode()
    except SignatureExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired, please log in again.",
        ) from exc
    except BadSignature as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        ) from exc

    if not payload.startswith(_MEMBER_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin token cannot be used for member endpoints.",
        )
    return int(payload[len(_MEMBER_PREFIX):])
