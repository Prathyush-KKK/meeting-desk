"""The session cookie.

A signed, 30-day cookie holding the Google ``sub`` and the email it signed in with. Nothing else
is stored client-side; roles and access come from the database on every request.
"""

from __future__ import annotations

from typing import Any

from fastapi import Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import Settings

SALT = "meeting-desk-session"


def serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt=SALT)


def issue(settings: Settings, response: Response, google_sub: str, email: str) -> None:
    token = serializer(settings).dumps({"sub": google_sub, "email": email})
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=settings.session_max_age_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.environment not in ("local", "test"),
        path="/",
    )


def read(settings: Settings, raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        return serializer(settings).loads(raw, max_age=settings.session_max_age_days * 24 * 3600)
    except (BadSignature, SignatureExpired):
        return None


def clear(settings: Settings, response: Response) -> None:
    response.delete_cookie(settings.session_cookie, path="/")
