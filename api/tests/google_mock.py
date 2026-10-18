"""A scripted Google for the contract tests.

``MockGoogleApi`` is an ``httpx.MockTransport`` handler that answers by (method, path) from the
fixtures under ``tests/fixtures/google/`` and records every request, so a test can assert both the
exact request the client sent (query, fields mask, JSON body) and what it made of the answer.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from app.google.http import GoogleHttp
from app.google.tokens import StaticTokens

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "google"

Responder = Callable[[httpx.Request], httpx.Response]


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def json_response(
    name_or_body: str | dict[str, Any], status: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    body = fixture(name_or_body) if isinstance(name_or_body, str) else name_or_body
    return httpx.Response(status, json=body, headers=headers)


class MockGoogleApi:
    def __init__(self) -> None:
        self.routes: list[tuple[str, str, Responder | list[Responder]]] = []
        self.requests: list[httpx.Request] = []

    def on(
        self, method: str, path: str, responder: Responder | list[Responder] | str | dict[str, Any]
    ) -> MockGoogleApi:
        """``path`` matches a URL whose path *contains* it. A list answers in order, then repeats the last."""
        if isinstance(responder, str | dict):
            fixed = responder
            responder = lambda request: json_response(fixed)  # noqa: E731
        self.routes = [r for r in self.routes if (r[0], r[1]) != (method.upper(), path)]
        self.routes.append((method.upper(), path, responder))
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for method, path, responder in self.routes:
            if request.method == method and path in request.url.path:
                if isinstance(responder, list):
                    answer = responder.pop(0) if len(responder) > 1 else responder[0]
                    return answer(request)
                return responder(request)
        return httpx.Response(
            500, json={"error": {"code": 500, "message": f"unscripted {request.method} {request.url}"}}
        )

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def http(self, sleep: Callable[[float], None] | None = None, **kwargs: Any) -> GoogleHttp:
        tokens = kwargs.pop("tokens", None) or StaticTokens()
        # No jitter unless a test asks for one, so the backoff schedule stays assertable.
        kwargs.setdefault("jitter", lambda: 0.0)
        return GoogleHttp(tokens, self.transport(), sleep=sleep or (lambda s: None), **kwargs)

    # --- assertions ------------------------------------------------------------------------------
    def sent(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method.upper() and path in r.url.path]

    @staticmethod
    def params(request: httpx.Request) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for key, value in request.url.params.multi_items():
            out.setdefault(key, []).append(value)
        return out

    @staticmethod
    def body(request: httpx.Request) -> Any:
        return json.loads(request.content.decode()) if request.content else None
