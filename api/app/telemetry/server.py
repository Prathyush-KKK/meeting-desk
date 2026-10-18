"""``/metrics`` on its own port.

docs/TELEMETRY.md is explicit: the metrics endpoint is on a **separate container port**,
unauthenticated and unreachable from the public ingress. So it is not a route on the API and not a
mount on the API router - it is a second, tiny ASGI app served by a second uvicorn ``Server`` on
``METRICS_PORT`` (9464 by default), started in a daemon thread with the API and stopped with it.

A thread rather than ``uvicorn.Server.serve()`` on the API's own loop because the API is started by
whatever runs ``app.main:app`` (uvicorn, gunicorn, a test client) and must not have to know about
this. The thread owns its own event loop; nothing is shared but the registry.

Nothing but ``GET /metrics`` and ``GET /healthz`` answers, so pointing the public ingress at this
port by accident still leaks nothing but the metrics - and the Service only names it for the
ServiceMonitor.
"""

from __future__ import annotations

import logging
import threading

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.types import Receive, Scope, Send

from app.telemetry import events
from app.telemetry.logs import get_logger, log_event
from app.telemetry.metrics import Metrics, metrics

log = get_logger("metrics")

DEFAULT_METRICS_PORT = 9464


class MetricsApp:
    """The whole second app: two paths, no framework, no state."""

    def __init__(self, metric_set: Metrics | None = None) -> None:
        self._metrics = metric_set

    @property
    def metrics(self) -> Metrics:
        return self._metrics if self._metrics is not None else metrics()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await _drain_lifespan(receive, send)
            return
        if scope["type"] != "http":  # pragma: no cover - nothing else is served here
            return
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        if method not in ("GET", "HEAD"):
            await _respond(send, 405, b"method not allowed\n", "text/plain; charset=utf-8")
            return
        if path == "/metrics":
            await _respond(send, 200, generate_latest(self.metrics.registry), CONTENT_TYPE_LATEST)
            return
        if path in ("/healthz", "/health"):
            await _respond(send, 200, b"ok\n", "text/plain; charset=utf-8")
            return
        await _respond(send, 404, b"not found\n", "text/plain; charset=utf-8")


async def _drain_lifespan(receive: Receive, send: Send) -> None:
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


async def _respond(send: Send, status: int, body: bytes, content_type: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", content_type.encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def make_metrics_app(metric_set: Metrics | None = None) -> MetricsApp:
    return MetricsApp(metric_set)


class MetricsServer:
    """A uvicorn server for ``MetricsApp`` in a daemon thread."""

    def __init__(self, port: int = DEFAULT_METRICS_PORT, host: str = "0.0.0.0", app: object = None) -> None:
        self.port = port
        self.host = host
        self.app = app or make_metrics_app()
        self._server: object = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        import uvicorn

        config = uvicorn.Config(
            self.app,  # type: ignore[arg-type]
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
        self._server = server

        def run() -> None:
            try:
                server.run()
            except Exception as exc:  # pragma: no cover - the API must survive a busy port
                log_event(
                    log,
                    events.METRICS_SERVER_FAILED,
                    level=logging.ERROR,
                    port=self.port,
                    failure_reason="server_error",
                    error=type(exc).__name__,
                )

        self._thread = threading.Thread(target=run, name="metrics-server", daemon=True)
        self._thread.start()
        log_event(log, events.METRICS_SERVER_STARTED, port=self.port)
        return True

    def stop(self) -> None:
        server = self._server
        if server is not None:
            server.should_exit = True  # type: ignore[attr-defined]
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None


__all__ = ["DEFAULT_METRICS_PORT", "MetricsApp", "MetricsServer", "make_metrics_app"]
