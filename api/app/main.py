"""The app factory.

Everything the app needs hangs off ``app.state``: settings, database, clock, Google suite,
extraction provider and, when ``JOBS_ENABLED`` is on, the procrastinate app. That is what lets a
test stand up a complete, isolated app in one call - in fake mode, or in real mode against an
``httpx.MockTransport`` handed in as ``transport``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app.auth import auth_router
from app.config import (
    DEFAULT_SESSION_SECRET,
    MIN_SESSION_SECRET_LENGTH,
    UNGUARDED_ENVIRONMENTS,
    Settings,
    get_settings,
)
from app.google.interface import AuthExpired, GoogleError, NotFoundError, PermissionDenied, RateLimited
from app.routes import admin, extract, meetings, notes, points, sheets, transfers, workbooks
from app.runtime import Runtime
from app.telemetry import TelemetryMiddleware, configure_logging, metrics, provider_telemetry
from app.telemetry.server import MetricsServer

ROUTERS: list[APIRouter] = [
    meetings.router,
    notes.router,
    extract.router,
    points.router,
    workbooks.router,
    transfers.router,
    sheets.router,
    admin.router,
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    app.state.db.create_all()
    if settings.seed_demo and settings.fake_google:
        from app.bootstrap import seed_demo

        with app.state.db.session() as session:
            seed_demo(session, app.state.google, app.state.clock)
    if settings.bootstrap_admin_emails:
        from app.bootstrap import bootstrap_admins

        with app.state.db.session() as session:
            bootstrap_admins(session, settings.bootstrap_admin_emails)
    jobs = app.state.jobs
    if jobs is not None:
        jobs.open()
    # /metrics listens on its own port, in its own thread. A busy port must not stop the API.
    server: MetricsServer | None = None
    if settings.metrics_enabled:
        server = MetricsServer(port=settings.metrics_port, host=settings.metrics_host)
        server.start()
    app.state.metrics_server = server
    try:
        yield
    finally:
        if server is not None:
            server.stop()
        if jobs is not None:
            jobs.close()
        app.state.runtime.close()


class UnsafeConfiguration(RuntimeError):
    """A deployment asked for a developer convenience that must never leave a laptop."""


def guard_environment(settings: Settings) -> None:
    """Refuse to start a deployment with the local shortcuts still in place.

    ``local`` and ``test`` keep every convenience; anything else (``staging``, ``production``, an
    environment nobody named) fails fast at import time rather than serving one request with a
    known secret, an authentication bypass or a wildcard CORS origin that carries credentials.
    """
    if not settings.is_guarded:
        # Local, but with Google sign-in in use and the real Google clients: the session cookie is
        # the whole of authentication, so its secret has to be real even on a laptop. This is the
        # live launch (docker-compose.live.yml), where scripts/live.sh generates the value.
        if not settings.fake_google and not settings.auth_dev_user:
            if settings.session_secret == DEFAULT_SESSION_SECRET or not settings.session_secret:
                raise UnsafeConfiguration(
                    "FAKE_GOOGLE=0 without AUTH_DEV_USER means Google sign-in is in use: set "
                    "SESSION_SECRET to a real value (32+ characters). scripts/live.sh does."
                )
            if len(settings.session_secret) < MIN_SESSION_SECRET_LENGTH:
                raise UnsafeConfiguration(
                    f"SESSION_SECRET is shorter than {MIN_SESSION_SECRET_LENGTH} characters while "
                    "Google sign-in is in use (FAKE_GOOGLE=0, no AUTH_DEV_USER)."
                )
        return
    allowed = ", ".join(UNGUARDED_ENVIRONMENTS)
    problems: list[str] = []
    if settings.session_secret == DEFAULT_SESSION_SECRET:
        problems.append("SESSION_SECRET is still the default from the repository")
    if len(settings.session_secret) < MIN_SESSION_SECRET_LENGTH:
        problems.append(f"SESSION_SECRET is shorter than {MIN_SESSION_SECRET_LENGTH} characters")
    if settings.auth_dev_user:
        problems.append(
            f"AUTH_DEV_USER is set to {settings.auth_dev_user!r}, which signs every request in "
            "as that person without Google"
        )
    if any(origin.strip() == "*" for origin in settings.cors_origins):
        problems.append(
            'CORS_ORIGINS contains "*" while the API sends credentials; name the web origins instead'
        )
    if problems:
        raise UnsafeConfiguration(
            f"ENVIRONMENT={settings.environment!r} (anything but {allowed} is a deployment): "
            + "; ".join(problems)
        )


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    jobs: Any = None,
    extraction: Any = None,
) -> FastAPI:
    resolved = settings or get_settings()
    guard_environment(resolved)
    configure_logging(resolved.log_level)
    metrics().set_build_info(resolved.app_version, resolved.git_commit)
    # Every breaker gauge reads 0 from the first scrape, before any call has been made.
    provider_telemetry().initialise()
    app = FastAPI(title=resolved.app_name, version="0.1.0", lifespan=lifespan)

    runtime = Runtime.build(resolved, transport=transport, extraction=extraction)
    app.state.runtime = runtime
    for name, value in runtime.as_state().items():
        setattr(app.state, name, value)
    app.state.transport = transport
    app.state.calendar_cache = {}

    if jobs is None and resolved.jobs_enabled:
        from app.jobs.queue import build_job_app

        jobs = build_job_app(resolved, sync=True)
    if jobs is not None:
        from app.jobs.queue import configure

        configure(runtime)
    app.state.jobs = jobs

    # This session is only ever the OAuth ``state`` round trip: its own cookie name, ten minutes,
    # and Secure everywhere but local and test, so the state cannot be read off a plain-HTTP hop.
    app.add_middleware(
        SessionMiddleware,
        secret_key=resolved.session_secret,
        session_cookie=resolved.state_cookie,
        max_age=resolved.state_cookie_max_age_seconds,
        same_site="lax",
        https_only=resolved.is_guarded,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Added last, so it is the outermost user middleware: it sees the status every request leaves
    # with, including the ones CORS or the session answer on their own.
    app.add_middleware(TelemetryMiddleware)

    app.include_router(auth_router)
    for router in ROUTERS:
        app.include_router(router)

    # Google's refusals become plain HTTP answers rather than 500s, so the UI can say what happened.
    @app.exception_handler(NotFoundError)
    def _not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(PermissionDenied)
    def _denied(request: Request, exc: PermissionDenied) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "google_detail": exc.detail}, status_code=403)

    @app.exception_handler(RateLimited)
    def _rate_limited(request: Request, exc: RateLimited) -> JSONResponse:
        return JSONResponse(
            {"detail": f"Google is rate-limiting us: {exc}", "retry_after_seconds": exc.retry_after_seconds},
            status_code=503,
            headers={"Retry-After": str(int(exc.retry_after_seconds) + 1)},
        )

    @app.exception_handler(AuthExpired)
    def _auth_expired(request: Request, exc: AuthExpired) -> JSONResponse:
        return JSONResponse(
            {"detail": f"A Google connection needs reconnecting: {exc}"},
            status_code=502,
        )

    @app.exception_handler(GoogleError)
    def _google_error(request: Request, exc: GoogleError) -> JSONResponse:
        return JSONResponse({"detail": f"Google said no: {exc}"}, status_code=502)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "environment": resolved.environment,
            "fake_google": resolved.fake_google,
            "fake_llm": resolved.fake_llm,
            "jobs": resolved.jobs_enabled,
            "extraction_provider": getattr(app.state.extraction, "name", "fake"),
            "now": app.state.clock.now().isoformat(),
        }

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, Any]:
        """Readiness: the database answers. What the Helm readinessProbe calls."""
        with app.state.db.session() as session:
            session.execute(text("SELECT 1"))
        return {"ok": True, "service": "meeting-desk"}

    @app.get("/livez", tags=["ops"])
    def livez() -> dict[str, Any]:
        """Liveness: the process is up. No dependency is touched, so a slow database cannot
        get the pod killed - that is readiness' job."""
        return {"ok": True, "service": "meeting-desk"}

    mount_web(app, resolved.web_dist)
    return app


class SpaFiles(StaticFiles):
    """Static files with the single-page fallback: an unknown path serves ``index.html``.

    The routers are registered first, so every API path is matched before this mount is reached and
    only the web app's own routes fall through to it.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        if is_dotfile(path):
            # Neither the file nor the SPA fallback: a build never has one, and answering
            # index.html for /.env or /.git/config invites a scan to keep going.
            raise StarletteHTTPException(status_code=404)
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404:
            return await super().get_response("index.html", scope)
        return response


def is_dotfile(path: str) -> bool:
    """Any segment starting with a dot: ``.env``, ``.git/config``, ``assets/.DS_Store``.

    ``.`` and ``..`` are not dotfiles - Starlette normalises "/" to "." and refuses traversal
    itself - so they are left to it.
    """
    segments = path.replace("\\", "/").split("/")
    return any(s.startswith(".") and s not in (".", "..") for s in segments if s)


def mount_web(app: FastAPI, web_dist: str) -> bool:
    """Serve ``WEB_DIST`` (``web/dist``) at "/" so one container serves the API and the app."""
    if not web_dist:
        return False
    root = Path(web_dist).expanduser()
    if not (root / "index.html").is_file():
        return False
    app.mount("/", SpaFiles(directory=root, html=True), name="web")
    return True


app = create_app()
