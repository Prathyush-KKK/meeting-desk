"""The connection picker: the first healthy admin connection able to see an item.

Every read goes through ``first_able``. It tries the connections in order, skips the ones Google
refuses (not shared, not found, rate-limited, expired) or whose answer the caller does not accept
(an empty search), and reports which connection answered - the source line and the workbook name
it. A ``Pick`` with no email carries the last refusal for the message.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from app.google.interface import AuthExpired, GoogleError, NotFoundError, PermissionDenied, RateLimited

T = TypeVar("T")

SKIPPABLE: tuple[type[GoogleError], ...] = (PermissionDenied, NotFoundError, RateLimited, AuthExpired)


@dataclass(slots=True)
class Pick:
    email: str | None = None
    value: Any = None
    detail: str = ""
    tried: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    exceptions: dict[str, BaseException] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.email is not None

    @property
    def expired(self) -> dict[str, str]:
        """Connections whose refresh token was refused on the way: they need reconnecting."""
        return {email: str(exc) for email, exc in self.exceptions.items() if isinstance(exc, AuthExpired)}

    @property
    def only_rate_limited(self) -> RateLimited | None:
        """Nothing answered, and every connection that was tried was throttled.

        Then "not shared with any admin account" is the wrong message: nobody was refused access,
        Google said "slower". The caller re-raises this so the route answers 503 with a
        ``Retry-After`` and the UI can show the retry.
        """
        if self.ok or not self.tried or len(self.exceptions) != len(self.tried):
            return None
        limits = [exc for exc in self.exceptions.values() if isinstance(exc, RateLimited)]
        if len(limits) != len(self.exceptions):
            return None
        return max(limits, key=lambda exc: exc.retry_after_seconds)


def first_able(
    emails: Iterable[str],
    attempt: Callable[[str], T],
    accept: Callable[[T], bool] | None = None,
    skip: tuple[type[BaseException], ...] = SKIPPABLE,
) -> Pick:
    """Run ``attempt`` per connection until one answers acceptably.

    A refusal of a kind not in ``skip`` (a 5xx, a transport failure) is also recorded and skipped,
    so one broken connection never stops the others being tried; the last error is in ``detail``.
    """
    pick = Pick()
    for email in emails:
        pick.tried.append(email)
        try:
            value = attempt(email)
        except (*skip, GoogleError) as exc:
            pick.errors[email] = _describe(exc)
            pick.exceptions[email] = exc
            pick.detail = pick.errors[email]
            continue
        if accept is not None and not accept(value):
            continue
        pick.email = email
        pick.value = value
        return pick
    return pick


def _describe(exc: BaseException) -> str:
    detail = getattr(exc, "detail", "")
    return f"{exc} ({detail})" if detail and detail != str(exc) else str(exc)
