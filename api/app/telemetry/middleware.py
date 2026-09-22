"""The request middleware: a request id, the two HTTP metrics, one log line per request.

Pure ASGI rather than ``BaseHTTPMiddleware`` for two reasons: it can read the *matched* route out
of the scope after the router has run, and it can work the route out **before** the app runs.

Both halves matter. The standard wants ``route`` on every line of a request, not only the last one,
so the route has to be in the context variable before the handler makes its first outbound call -
which means matching the route table here, the way Starlette itself does (first full match in
registration order, then a partial one, which is how a 405 happens). Afterwards
``scope["endpoint"]`` is authoritative and is what the metric label uses; the two agree, and the
pre-match is what the log lines in between carried.

Either way the label is a templated path (``/meetings/{meeting_id}/extract``) and never a record
id, and everything unmatched collapses into one bucket.

Added last in ``create_app``, so it is the outermost user middleware and sees the status every
request actually leaves with.
"""

from __future__ import annotations

import logging
import time

from starlette.routing import Match, Mount
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.telemetry import events
from app.telemetry.events import FailureReason
from app.telemetry.logs import (
    get_logger,
    log_event,
    new_request_id,
    reset_request_id,
    reset_route,
    set_request_id,
    set_route,
)
from app.telemetry.metrics import Metrics, metrics, status_class

log = get_logger("http")

REQUEST_ID_HEADER = "x-request-id"

#: Anything the router did not match. One bucket, so a scan or a typo cannot grow the series count.
UNMATCHED = "__unmatched__"


def route_index(routes: list) -> dict[int, str]:
    """endpoint -> the route's declared path. Built once, after the routers are registered."""
    index: dict[int, str] = {}
    for route in routes:
        path = getattr(route, "path", "")
        if isinstance(route, Mount):
            # The SPA mount at "/" answers every unknown path; one label for all of it.
            path = f"{route.path}/{{path:path}}"
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None and isinstance(route, Mount):
            endpoint = route.app
        if endpoint is not None and path:
            index.setdefault(id(endpoint), path)
    return index


class TelemetryMiddleware:
    def __init__(self, app: ASGIApp, metric_set: Metrics | None = None) -> None:
        self.app = app
        self._metrics = metric_set
        self._index: dict[int, str] | None = None
        self._routes_holder: list = []

    @property
    def metrics(self) -> Metrics:
        return self._metrics if self._metrics is not None else metrics()

    def _routes(self, scope: Scope) -> list:
        if self._index is None:
            app = scope.get("app")
            self._routes_holder = list(getattr(app, "routes", []) or [])
            self._index = route_index(self._routes_holder)
        return self._routes_holder

    def _predict_route(self, scope: Scope) -> str:
        """The route Starlette is about to pick, worked out before the app runs.

        Same algorithm and same order as ``starlette.routing.Router``: the first full match wins, a
        partial one (the path matches, the method does not - a 405) is the fallback. It costs one
        compiled-regex match per route, which is what puts ``route`` on the log lines the handler
        itself writes.
        """
        partial = ""
        for route in self._routes(scope):
            try:
                match, _ = route.matches(scope)
            except Exception:  # pragma: no cover - a route that cannot match is not our problem
                continue
            path = self._path_of(route)
            if match == Match.FULL:
                return path or UNMATCHED
            if match == Match.PARTIAL and not partial:
                partial = path
        return partial or UNMATCHED

    def _path_of(self, route: object) -> str:
        assert self._index is not None
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None and isinstance(route, Mount):
            endpoint = route.app
        return self._index.get(id(endpoint), "") if endpoint is not None else ""

    def _route_label(self, scope: Scope, predicted: str) -> str:
        """After the app has run, ``scope["endpoint"]`` is what actually handled it."""
        endpoint = scope.get("endpoint")
        if endpoint is None:
            return predicted
        assert self._index is not None
        return self._index.get(id(endpoint), predicted)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _header(scope, REQUEST_ID_HEADER)
        request_id = incoming if _is_safe_request_id(incoming) else new_request_id()
        id_token = set_request_id(request_id)
        predicted = self._predict_route(scope)
        route_token = set_route(predicted)
        method = scope.get("method", "GET").upper()
        started = time.perf_counter()
        status = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = int(message["status"])
                headers = list(message.get("headers") or [])
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        failed: BaseException | None = None
        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException as exc:
            failed = exc
            status["code"] = 500
            raise
        finally:
            duration = time.perf_counter() - started
            route = self._route_label(scope, predicted)
            set_route(route)
            code = status["code"]
            self.metrics.http_requests.labels(
                route=route, method=method, status_class=status_class(code)
            ).inc()
            self.metrics.http_duration.labels(route=route, method=method).observe(duration)
            _log_request(route, method, code, duration, failed)
            reset_route(route_token)
            reset_request_id(id_token)


def _log_request(route: str, method: str, code: int, duration: float, failed: BaseException | None) -> None:
    duration_ms = duration * 1000
    if failed is not None:
        log_event(
            log,
            events.UNHANDLED_EXCEPTION,
            level=logging.ERROR,
            route=route,
            method=method,
            status=code,
            status_class=status_class(code),
            failure_reason=FailureReason.SERVER_ERROR,
            duration_ms=duration_ms,
            exc_info=failed,
        )
        return
    if code >= 500:
        log_event(
            log,
            events.REQUEST_FAILED,
            level=logging.ERROR,
            route=route,
            method=method,
            status=code,
            status_class=status_class(code),
            failure_reason=FailureReason.SERVER_ERROR,
            duration_ms=duration_ms,
        )
        return
    if code >= 400:
        log_event(
            log,
            events.REQUEST_FAILED,
            level=logging.WARNING,
            route=route,
            method=method,
            status=code,
            status_class=status_class(code),
            failure_reason=FailureReason.CONFLICT if code == 409 else FailureReason.CLIENT_ERROR,
            duration_ms=duration_ms,
        )
        return
    log_event(
        log,
        events.REQUEST_COMPLETED,
        route=route,
        method=method,
        status=code,
        status_class=status_class(code),
        duration_ms=duration_ms,
    )


def _header(scope: Scope, name: str) -> str:
    wanted = name.encode()
    for key, value in scope.get("headers") or []:
        if key.lower() == wanted:
            return value.decode("latin-1")
    return ""


def _is_safe_request_id(value: str) -> bool:
    """A caller may pass one in; it goes on every log line, so it has to be boring."""
    return bool(value) and len(value) <= 64 and all(c.isalnum() or c in "-_" for c in value)


def observe_request(
    metric_set: Metrics,
    route: str,
    method: str,
    code: int,
    duration_seconds: float,
) -> None:
    """The recording half on its own, for tests."""
    metric_set.http_requests.labels(route=route, method=method, status_class=status_class(code)).inc()
    metric_set.http_duration.labels(route=route, method=method).observe(duration_seconds)


__all__ = ["REQUEST_ID_HEADER", "UNMATCHED", "TelemetryMiddleware", "observe_request", "route_index"]
