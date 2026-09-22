"""Install procrastinate's own tables (``make jobs-schema``).

The queue keeps its jobs in the same Postgres as the app, in tables procrastinate owns and
migrates itself; they are deliberately outside Alembic so ``alembic check`` stays about spec
section 4. Run once per database before the first worker starts.
"""

from __future__ import annotations

from app.config import get_settings
from app.jobs.queue import build_job_app


def main() -> None:  # pragma: no cover - a one-off command against Postgres
    settings = get_settings()
    if settings.is_sqlite:
        raise SystemExit("The job queue needs Postgres; point DATABASE_URL at it first.")
    job_app = build_job_app(settings, sync=True)
    with job_app.open():
        job_app.schema_manager.apply_schema()
    print(f"procrastinate schema applied to {settings.jobs_conninfo.split('@')[-1]}")


if __name__ == "__main__":  # pragma: no cover
    main()
