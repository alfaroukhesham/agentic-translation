"""Admin authentication helpers."""

from __future__ import annotations

import bcrypt

from app.config import get_settings


def verify_admin_password(password: str) -> bool:
    settings = get_settings()
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            settings.admin_password.encode("utf-8"),
        )
    except ValueError:
        return password == settings.admin_password
