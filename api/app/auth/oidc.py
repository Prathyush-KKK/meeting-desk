"""Google OIDC sign-in.

Scaffolded here and exercised end to end in phase 3; phase 1 and the tests use ``AUTH_DEV_USER``.
The flow is deliberately thin: Google identifies the person, the allow-list decides access, and the
allow-list entry binds to the Google ``sub`` on first sign-in.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import session as session_cookie
from app.auth.deps import authenticate, get_config
from app.config import Settings
from app.db import get_session
from app.models import AllowListEntry, Connection, User

router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"


def build_oauth(settings: Settings) -> OAuth:
    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url=GOOGLE_METADATA,
        # ``code_challenge_method`` turns PKCE on: authlib puts the S256 challenge in the redirect,
        # keeps the verifier in the session with the state, and sends it with the code. Sign-in is
        # a public-facing redirect, so the code must be useless to anyone who intercepts it.
        client_kwargs={
            "scope": "openid email profile",
            "prompt": "select_account",
            "code_challenge_method": "S256",
        },
    )
    return oauth


def _google(request: Request, settings: Settings) -> Any:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google sign-in is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, "
            "or run locally with AUTH_DEV_USER.",
        )
    oauth = getattr(request.app.state, "oauth", None)
    if oauth is None:
        oauth = build_oauth(settings)
        request.app.state.oauth = oauth
    return oauth.google


@router.get("/login")
async def login(request: Request, settings: Settings = Depends(get_config)) -> Response:
    if settings.auth_dev_user:
        return RedirectResponse(settings.web_base_url)
    client = _google(request, settings)
    extra = {"hd": settings.google_hosted_domain} if settings.google_hosted_domain else {}
    return await client.authorize_redirect(request, settings.google_oidc_redirect_uri, **extra)


@router.get("/callback")
async def callback(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_config),
) -> Response:
    client = _google(request, settings)
    token = await client.authorize_access_token(request)
    claims = token.get("userinfo") or {}
    email = str(claims.get("email", "")).strip().lower()
    google_sub = str(claims.get("sub", ""))
    domain = str(claims.get("hd", "")) or email.split("@")[-1]
    if not email or not google_sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google did not return an account.")
    if settings.google_hosted_domain and domain != settings.google_hosted_domain:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Sign in with a {settings.google_hosted_domain} account.",
        )

    entry = db.get(AllowListEntry, email)
    if entry is None:
        admins = ", ".join(
            db.scalars(select(AllowListEntry.email).where(AllowListEntry.role == "admin")).all()
        )
        # The attempt is logged with the email so an admin can see who tried.
        from app.activity import log

        log(db, email, "Sign-in refused: not on the allow-list")
        db.commit()
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"{email} is not on the Meeting Desk allow-list. Ask an admin to add it: {admins}.",
        )

    user = db.scalar(select(User).where(User.google_sub == google_sub)) or db.scalar(
        select(User).where(User.email == email)
    )
    if user is None:
        user = User(google_sub=google_sub, email=email, name=str(claims.get("name", "")), role=entry.role)
        db.add(user)
        db.flush()
    user.google_sub = google_sub
    user.email = email
    user.role = entry.role
    entry.matched_user_id = user.id
    db.commit()

    # An admin who has not connected their Google account goes straight on to that consent
    # screen: one sign-in, one scope screen, and Step 1 already has their calendar. Everyone else
    # lands in the app.
    response = RedirectResponse(first_signin_redirect(db, settings, user) or settings.web_base_url)
    session_cookie.issue(settings, response, google_sub, email)
    return response


def first_signin_redirect(db: Session, settings: Settings, user: User) -> str | None:
    """The connect flow for an admin with no working connection of their own, else ``None``.

    Only when the real Google clients are in use and the connect flow is configured (client id,
    secret and the token key): in fake mode or on a half-configured box the person is not sent
    into a flow that would answer 503. The path is relative, so it resolves against the API's
    own origin whether the SPA is served from it or from Vite.
    """
    if user.role != "admin" or settings.fake_google:
        return None
    if not (settings.google_client_id and settings.google_client_secret and settings.token_key):
        return None
    connected = db.scalar(
        select(Connection.id).where(Connection.email == user.email).where(Connection.status == "ok")
    )
    if connected is not None:
        return None
    return "/admin/connections/connect?" + urlencode({"email": user.email, "next": "/"})


@router.post("/logout")
def logout(settings: Settings = Depends(get_config)) -> Response:
    response = JSONResponse({"ok": True})
    session_cookie.clear(settings, response)
    return response


@router.get("/me")
def me(user: User = Depends(authenticate), settings: Settings = Depends(get_config)) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "is_admin": user.role == "admin",
        # What the UI needs to render the workspace's way: the zone every time is shown in, the
        # workstreams to offer, and the Workspace domain sign-in is limited to (empty: any).
        "timezone": settings.display_timezone or "UTC",
        "workstreams": settings.workstream_list,
        "hosted_domain": settings.google_hosted_domain,
    }
