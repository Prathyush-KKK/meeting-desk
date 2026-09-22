"""Gmail: the recap email, on the connection whose mailbox received it.

``users.messages.list`` with the query ``recap_query`` builds
(``from:gemini-notes@google.com "<title>" after:<date>``), then ``users.messages.get`` for each
hit. The HTML body becomes text with paragraphs, breaks and list items kept as lines; a text/plain
part is used as-is when the mail carries one.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

from app.google.http import GoogleHttp
from app.google.interface import GmailMessage

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_RESULTS = 10
_ADDR_RE = re.compile(r"<([^>]+)>")
_BLANKS_RE = re.compile(r"\n{3,}")


class RealGmailClient:
    def __init__(self, http: GoogleHttp, display_tz: ZoneInfo | str = "Asia/Kolkata") -> None:
        self.http = http
        self.tz = ZoneInfo(display_tz) if isinstance(display_tz, str) else display_tz

    def search_messages(self, connection_email: str, query: str) -> list[GmailMessage]:
        listing = self.http.get(
            connection_email, f"{BASE}/messages", params={"q": query, "maxResults": MAX_RESULTS}
        )
        out: list[GmailMessage] = []
        for stub in listing.get("messages") or []:
            raw = self.http.get(connection_email, f"{BASE}/messages/{stub['id']}", params={"format": "full"})
            out.append(parse_message(raw, self.tz))
        out.sort(key=lambda m: m.received_at, reverse=True)
        return out


# --- parsing ----------------------------------------------------------------------------------------


def parse_message(raw: dict[str, Any], tz: ZoneInfo) -> GmailMessage:
    payload = raw.get("payload") or {}
    headers = {str(h.get("name", "")).lower(): str(h.get("value", "")) for h in payload.get("headers") or []}
    plain, html = _bodies(payload)
    body = plain.strip() if plain.strip() else html_to_text(html)
    millis = int(raw.get("internalDate") or 0)
    received = datetime.fromtimestamp(millis / 1000, tz=tz) if millis else datetime.now(tz)
    return GmailMessage(
        id=str(raw.get("id") or ""),
        thread_id=str(raw.get("threadId") or ""),
        subject=headers.get("subject", ""),
        from_email=_address(headers.get("from", "")),
        received_at=received,
        body=body,
    )


def _bodies(part: dict[str, Any]) -> tuple[str, str]:
    """(text/plain, text/html) concatenated over the MIME tree."""
    plain, html = "", ""
    mime = str(part.get("mimeType") or "")
    data = (part.get("body") or {}).get("data")
    if data:
        decoded = _b64(data)
        if mime == "text/plain":
            plain += decoded
        elif mime == "text/html":
            html += decoded
    for child in part.get("parts") or []:
        p, h = _bodies(child)
        plain += p
        html += h
    return plain, html


def _b64(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _address(value: str) -> str:
    m = _ADDR_RE.search(value)
    return (m.group(1) if m else value).strip().lower()


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "section"}
    SKIP = {"script", "style", "head", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag == "td":
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK and tag not in ("br", "li"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        # Whitespace between tags is layout, not a line break.
        self.parts.append(data if data.strip() else " ")


def html_to_text(html: str) -> str:
    if not html:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = unescape("".join(parser.parts))
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    return _BLANKS_RE.sub("\n\n", "\n".join(lines)).strip()
