"""Engine and session handling.

The engine hangs off the FastAPI app rather than a module global so tests can stand up several
apps, each against its own SQLite file, inside one process.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base
from app.telemetry.providers import POSTGRES, provider_telemetry


def instrument(engine: Engine) -> Engine:
    """Count every statement on ``external_provider_requests_total{provider="postgres"}``.

    The standard asks for Postgres to be covered like any other outbound dependency, so the counter
    and the last-success gauge are driven from the engine's own events - one op, ``query``, so the
    series count does not follow the number of statements the app happens to run.

    The provider label stays ``postgres`` even on the SQLite file a local run uses: it names the
    deployed dependency, not the driver, so a dashboard reads the same in both.

    The breaker gauge for ``postgres`` is a constant 0 (see app/telemetry/breaker.py): there is
    nothing to fall back to, and opening it would turn a slow database into a hard outage.
    """

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany) -> None:
        provider_telemetry().record_success(POSTGRES, "query")

    @event.listens_for(engine, "handle_error")
    def _error(context) -> None:
        provider_telemetry().record_failure(POSTGRES, "query", context.original_exception)

    return engine


class Database:
    def __init__(self, url: str) -> None:
        kwargs: dict = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            # One connection shared across threads: TestClient runs the app in a worker thread.
            kwargs["connect_args"] = {"check_same_thread": False}
        self.url = url
        self.engine: Engine = instrument(create_engine(url, **kwargs))
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        Base.metadata.drop_all(self.engine)

    def session(self) -> Session:
        return self.session_factory()

    def dispose(self) -> None:
        self.engine.dispose()


def get_database(request: Request) -> Database:
    return request.app.state.db


def get_session(db: Database = Depends(get_database)) -> Iterator[Session]:
    session = db.session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
