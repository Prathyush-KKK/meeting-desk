"""Circuit breakers, one per provider.

Closed (0) -> five consecutive failures -> open (2). Thirty seconds later the next call is let
through as a trial and the breaker reads half-open (1): that call decides, success closes it,
failure opens it again for another thirty seconds.

Only a *dependency* failure counts. A 404 from Docs because nobody shared the document, a 403 from
Sheets because of a protected range and an ``invalid_grant`` on one connection's refresh token are
answers, not outages; they are counted as ``outcome="error"`` (so the alert rules still see them)
but they never move the breaker. ``app/telemetry/providers.py`` holds that list.

Postgres has no breaker: there is nowhere to fall back to and tripping it would only turn a slow
database into a hard outage. Its gauge is a constant 0, set at startup and never written again.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.telemetry import events
from app.telemetry.logs import get_logger, log_event

log = get_logger("breaker")

CLOSED = "closed"
HALF_OPEN = "half_open"
OPEN = "open"

STATE_VALUE = {CLOSED: 0.0, HALF_OPEN: 1.0, OPEN: 2.0}

FAILURE_THRESHOLD = 5
RECOVERY_SECONDS = 30.0


class BreakerOpen(RuntimeError):
    """Raised instead of making the call while the breaker is open."""

    def __init__(self, provider: str, retry_after_seconds: float = 0.0) -> None:
        super().__init__(
            f"the circuit breaker for {provider} is open; retrying in {int(retry_after_seconds) + 1} s"
        )
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds


@dataclass
class Breaker:
    provider: str
    failure_threshold: int = FAILURE_THRESHOLD
    recovery_seconds: float = RECOVERY_SECONDS
    now: Callable[[], float] = time.monotonic
    state: str = CLOSED
    consecutive_failures: int = 0
    opened_at: float = 0.0
    on_change: Callable[[str, str], None] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # --- state ------------------------------------------------------------------------------------
    @property
    def value(self) -> float:
        return STATE_VALUE[self.state]

    def _move(self, state: str, event: str) -> None:
        if state == self.state:
            return
        self.state = state
        if self.on_change is not None:
            self.on_change(self.provider, state)
        log_event(log, event, provider=self.provider, breaker_state=state)

    # --- the three calls a wrapper makes ----------------------------------------------------------
    def allow(self) -> bool:
        """May this call go out? Half-open lets it through as the trial."""
        with self._lock:
            if self.state != OPEN:
                return True
            if self.now() - self.opened_at >= self.recovery_seconds:
                self._move(HALF_OPEN, events.BREAKER_HALF_OPEN)
                return True
            return False

    def retry_after(self) -> float:
        with self._lock:
            if self.state != OPEN:
                return 0.0
            return max(0.0, self.recovery_seconds - (self.now() - self.opened_at))

    def record_success(self) -> None:
        with self._lock:
            self.consecutive_failures = 0
            self._move(CLOSED, events.BREAKER_CLOSED)

    def record_failure(self) -> None:
        with self._lock:
            self.consecutive_failures += 1
            if self.state == HALF_OPEN or self.consecutive_failures >= self.failure_threshold:
                self.opened_at = self.now()
                self._move(OPEN, events.BREAKER_OPENED)

    def reset(self) -> None:
        with self._lock:
            self.consecutive_failures = 0
            self.opened_at = 0.0
            self._move(CLOSED, events.BREAKER_CLOSED)


class BreakerRegistry:
    """The breakers, keyed by provider, with the gauge kept in step with every transition."""

    def __init__(
        self,
        providers: tuple[str, ...],
        on_change: Callable[[str, str], None] | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._breakers = {
            provider: Breaker(provider=provider, on_change=on_change, now=now) for provider in providers
        }

    def __getitem__(self, provider: str) -> Breaker:
        return self._breakers[provider]

    def get(self, provider: str) -> Breaker | None:
        return self._breakers.get(provider)

    def items(self):
        return self._breakers.items()

    def reset_all(self) -> None:
        for breaker in self._breakers.values():
            breaker.reset()


__all__ = [
    "CLOSED",
    "FAILURE_THRESHOLD",
    "HALF_OPEN",
    "OPEN",
    "RECOVERY_SECONDS",
    "STATE_VALUE",
    "Breaker",
    "BreakerOpen",
    "BreakerRegistry",
]
