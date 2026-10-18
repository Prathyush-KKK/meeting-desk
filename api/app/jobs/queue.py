"""The procrastinate queue: extraction on demand, Doc fetch every 5 minutes, token health daily.

Three plain functions do the work (``run_extraction_job``, ``run_fetch_missing_docs``,
``run_token_health``) against a ``Runtime``; the procrastinate tasks are thin wrappers around
them, which is what the tests call. The API process opens the app with a sync connector to
``defer``; ``python -m app.jobs.queue`` (``make worker``) runs the worker with the async one.
``JOBS_ENABLED=0`` (the default for SQLite and tests) means no queue: the route runs extraction
inline and the periodic jobs can be run by hand through the admin routes.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.config import Settings, get_settings
from app.extract.provider import ExtractionError
from app.jobs.extract import extraction_out, perform_extraction
from app.jobs.fetch_doc import fetch_missing_docs
from app.jobs.token_health import check_connection_health
from app.models import Connection, Extraction, Meeting
from app.runtime import Runtime
from app.telemetry import configure_logging, metrics, provider_telemetry
from app.telemetry.server import MetricsServer

try:  # procrastinate is a core dependency, but the import stays guarded so a slim image still boots
    import procrastinate
except ImportError:  # pragma: no cover
    procrastinate = None  # type: ignore[assignment]

log = logging.getLogger("meeting_desk.jobs")

EXTRACT_TASK = "meeting_desk.extract_meeting"
FETCH_DOCS_TASK = "meeting_desk.fetch_missing_docs"
TOKEN_HEALTH_TASK = "meeting_desk.token_health"
FETCH_DOCS_CRON = "*/5 * * * *"  # every 5 minutes; the job itself limits to the hour after a meeting
TOKEN_HEALTH_CRON = "30 21 * * *"  # 21:30 UTC, daily


# --- the work ------------------------------------------------------------------------------------------


def run_extraction_job(runtime: Runtime, extraction_id: str, actor: str = "") -> dict[str, Any]:
    """The queued half of ``POST /meetings/{id}/extract``."""
    with runtime.db.session() as session:
        extraction = session.get(Extraction, uuid.UUID(str(extraction_id)))
        if extraction is None:
            raise LookupError(f"unknown extraction {extraction_id}")
        meeting = session.get(Meeting, extraction.meeting_id)
        if meeting is None:
            extraction.error = "The meeting was removed before extraction ran."
            session.commit()
            return extraction_out(extraction, [])
        emails = list(
            session.scalars(
                select(Connection.email).where(Connection.status == "ok").order_by(Connection.connected_at)
            ).all()
        )
        try:
            created = perform_extraction(
                session,
                extraction,
                meeting,
                runtime.extraction,
                runtime.clock,
                actor=actor,
                google=runtime.google,
                connection_emails=emails,
            )
        except ExtractionError as exc:
            session.commit()
            log.warning("extraction %s failed: %s", extraction_id, exc)
            return extraction_out(extraction, [])
        from app.activity import log as activity_log

        activity_log(
            session, actor or "meeting-desk (job)", f"Extracted {len(created)} points from {meeting.title}"
        )
        session.commit()
        return extraction_out(extraction, created)


def run_fetch_missing_docs(runtime: Runtime) -> dict[str, list[str]]:
    with runtime.db.session() as session:
        report = fetch_missing_docs(session, runtime.google, runtime.clock)
        session.commit()
        return report.to_dict()


def run_token_health(runtime: Runtime) -> dict[str, Any]:
    with runtime.db.session() as session:
        unhealthy = check_connection_health(session, runtime.google, runtime.clock.now())
        session.commit()
        return {"checked": True, "unhealthy": [c.email for c in unhealthy]}


# --- the procrastinate app ------------------------------------------------------------------------------

_RUNTIME: Runtime | None = None


def configure(runtime: Runtime | None) -> None:
    """The runtime the task bodies use. A worker builds one from settings when none was given."""
    global _RUNTIME
    _RUNTIME = runtime


def current_runtime() -> Runtime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = Runtime.build(get_settings())
    return _RUNTIME


def build_job_app(settings: Settings, connector: Any = None, sync: bool = False) -> Any:
    """A procrastinate ``App`` with the three tasks registered. ``connector`` lets tests use memory."""
    if procrastinate is None:  # pragma: no cover
        raise RuntimeError("procrastinate is not installed")
    if connector is None:
        connector = (
            procrastinate.SyncPsycopgConnector(conninfo=settings.jobs_conninfo)
            if sync
            else procrastinate.PsycopgConnector(conninfo=settings.jobs_conninfo)
        )
    job_app = procrastinate.App(connector=connector, import_paths=[])
    register_tasks(job_app)
    return job_app


def register_tasks(job_app: Any) -> dict[str, Any]:
    @job_app.task(name=EXTRACT_TASK, retry=2)
    def extract_meeting(extraction_id: str, actor: str = "") -> dict[str, Any]:
        return run_extraction_job(current_runtime(), extraction_id, actor)

    @job_app.periodic(cron=FETCH_DOCS_CRON)
    @job_app.task(name=FETCH_DOCS_TASK, queueing_lock="fetch_missing_docs")
    def fetch_missing_docs_task(timestamp: int) -> dict[str, list[str]]:
        return run_fetch_missing_docs(current_runtime())

    @job_app.periodic(cron=TOKEN_HEALTH_CRON)
    @job_app.task(name=TOKEN_HEALTH_TASK, queueing_lock="token_health")
    def token_health_task(timestamp: int) -> dict[str, Any]:
        return run_token_health(current_runtime())

    return {
        EXTRACT_TASK: extract_meeting,
        FETCH_DOCS_TASK: fetch_missing_docs_task,
        TOKEN_HEALTH_TASK: token_health_task,
    }


def enqueue_extraction(job_app: Any, extraction_id: str, actor: str) -> int | None:
    """Defer the extraction task; returns procrastinate's job id."""
    task = job_app.tasks[EXTRACT_TASK]
    return task.defer(extraction_id=str(extraction_id), actor=actor)


def main() -> None:  # pragma: no cover - the worker entry point
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    configure_logging(settings.log_level)
    metrics().set_build_info(settings.app_version, settings.git_commit)
    provider_telemetry().initialise()
    if not settings.jobs_enabled:
        raise SystemExit("JOBS_ENABLED is off; set it to 1 (and DATABASE_URL to Postgres) to run a worker.")
    configure(Runtime.build(settings))
    # The worker emits background_job_* where the jobs actually run, so it serves /metrics on the
    # same port the API does - the chart gives it its own (headless) Service for the scrape.
    server: MetricsServer | None = None
    if settings.metrics_enabled:
        server = MetricsServer(port=settings.metrics_port, host=settings.metrics_host)
        server.start()
    job_app = build_job_app(settings)
    try:
        # run_worker opens the (async) connector itself and closes it on exit.
        job_app.run_worker(install_signal_handlers=True)
    finally:
        if server is not None:
            server.stop()


if __name__ == "__main__":  # pragma: no cover
    main()
