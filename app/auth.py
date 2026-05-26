"""Authentication helpers for admin UI and WordPress /v1 API."""

from __future__ import annotations

import secrets

import bcrypt
from fastapi import Header, HTTPException, status

from app.config import get_settings

# WordPress contract: same header name as outbound webhook (BLOG_TRANSLATION_WEBHOOK_SECRET).
WEBHOOK_SECRET_HEADER = "X-Translation-Secret"


def verify_admin_password(password: str) -> bool:
    settings = get_settings()
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            settings.admin_password.encode("utf-8"),
        )
    except ValueError:
        return password == settings.admin_password


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def verify_api_secret(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_translation_secret: str | None = Header(default=None, alias=WEBHOOK_SECRET_HEADER),
) -> None:
    """WordPress → /v1: X-Translation-Secret must match API_SECRET (= BLOG_TRANSLATION_WEBHOOK_SECRET)."""
    settings = get_settings()
    expected = settings.api_secret
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API_SECRET is not configured",
        )

    provided = x_translation_secret or _extract_bearer_token(authorization)
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API credentials",
        )