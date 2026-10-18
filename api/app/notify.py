"""After a transfer: one message to a chat webhook (``NOTIFY_WEBHOOK_URL``), so the team sees what
went into the sheet without opening it.

The body is ``{"text": ...}``, which Slack and Mattermost incoming webhooks, Google Chat space
webhooks and Discord's ``/slack``-suffixed webhook URLs all accept. It is sent after the response,
best effort: a webhook that is down or refuses is logged and counted, never a failed transfer.
"""

from __future__ import annotations

import logging

import httpx

from app.telemetry.logs import get_logger, log_event
from app.telemetry.providers import WEBHOOK, track_provider

log = get_logger("notify")

TIMEOUT_SECONDS = 5.0
MAX_LINES = 10


def transfer_message(
    *,
    actor: str,
    workbook_name: str,
    sheet_title: str,
    sheet_url: str,
    meeting_titles: list[str],
    points: list[dict[str, str]],
) -> str:
    """"Daniel Okafor sent 2 points from Vendor call to Roadmap > P1: • text - owner, due"."""
    count = f"{len(points)} point{'' if len(points) == 1 else 's'}"
    source = f" from {', '.join(meeting_titles)}" if meeting_titles else ""
    lines = [f"{actor} sent {count}{source} to {workbook_name} > {sheet_title}"]
    for point in points[:MAX_LINES]:
        extra = ", ".join(v for v in (point.get("owner", ""), point.get("due", "")) if v)
        lines.append(f"• {point.get('text', '')}" + (f" - {extra}" if extra else ""))
    if len(points) > MAX_LINES:
        lines.append(f"…and {len(points) - MAX_LINES} more")
    if sheet_url:
        lines.append(sheet_url)
    return "\n".join(lines)


def post(url: str, text: str, transport: httpx.BaseTransport | None = None) -> bool:
    """Send one message. True when the webhook took it; never raises."""
    try:
        with (
            track_provider(WEBHOOK, "post"),
            httpx.Client(transport=transport, timeout=TIMEOUT_SECONDS) as http,
        ):
            response = http.post(url, json={"text": text})
            response.raise_for_status()
    except Exception as exc:  # best effort by design: the transfer already landed
        log_event(log, "notify_failed", level=logging.WARNING, error=type(exc).__name__)
        return False
    log_event(log, "notify_sent", chars=len(text))
    return True

