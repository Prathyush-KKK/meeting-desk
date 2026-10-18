"""Daily connection health.

An internal OAuth app means tokens do not expire on a timer, but they still get revoked (password
change, admin action, the app removed from the account). A cheap Calendar call per connection
exercises the refresh token: an ``AuthExpired`` - the refresh token refused, ``invalid_grant`` -
marks the connection ``expired`` with ``last_error`` so every page can show the banner naming the
admin. Every other refusal (a rate limit, a 500, Calendar being down) is recorded in
``last_error`` and leaves the status alone: the connection is not broken, only unlucky.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.google.interface import AuthExpired, GoogleError, GoogleSuite, RateLimited
from app.models import Connection
from app.telemetry.providers import track_job


def check_connection_health(db: Session, google: GoogleSuite, now: datetime) -> list[Connection]:
    """Returns the connections that are not healthy."""
    with track_job("token_health"):
        return _check_connection_health(db, google, now)


def _check_connection_health(db: Session, google: GoogleSuite, now: datetime) -> list[Connection]:
    unhealthy: list[Connection] = []
    for connection in db.scalars(select(Connection).order_by(Connection.connected_at)).all():
        try:
            google.calendar.list_events(connection.email, now, now)
        except AuthExpired as exc:
            # The refresh token itself was refused. Only this means "reconnect me".
            connection.status = "expired"
            connection.last_error = str(exc)
            unhealthy.append(connection)
            continue
        except (RateLimited, GoogleError) as exc:
            # A 429, a 500 or a Calendar outage says nothing about the token: remember why the
            # check did not pass and leave the status alone, or a bad afternoon at Google would
            # send every admin to the reconnect screen.
            connection.last_error = str(exc)
            continue
        connection.status = "ok"
        connection.last_ok_at = now
        connection.last_error = None
    return unhealthy
