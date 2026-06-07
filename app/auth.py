"""Minimal admin authentication using a signed, expiring token.

A single shared admin password (``settings.admin_password``) is exchanged for a signed
token via ``POST /api/auth/login``. Protected endpoints require that token in the
``Authorization: Bearer <token>`` header. Tokens are signed with ``settings.secret_key``
so they cannot be forged, and they expire after ``settings.token_max_age_seconds``.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from app.config import settings

_signer = TimestampSigner(settings.secret_key)
_ADMIN_SUBJECT = "axxspace-admin"

# auto_error=False so we can return a clean 401 instead of FastAPI's default.
_bearer = HTTPBearer(auto_error=False)


def create_admin_token() -> str:
    """Issue a fresh signed admin token."""
    return _signer.sign(_ADMIN_SUBJECT.encode()).decode()


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
        _signer.unsign(credentials.credentials, max_age=settings.token_max_age_seconds)
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
    return _ADMIN_SUBJECT
