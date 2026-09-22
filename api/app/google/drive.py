"""Drive: the Notes by Gemini search and the ``capabilities.canEdit`` check.

``files.list`` with a ``q`` built from the meeting title, limited to Google Docs whose name also
carries "Notes by Gemini", created inside the window the caller gives (±2 h of the meeting start).
``files.get`` with ``fields=name,capabilities/canEdit`` is what the workbook connect flow asks
before it trusts a connection to write.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.google.http import GoogleHttp
from app.google.interface import GEMINI_NOTES_MARKER, DriveFile, NotFoundError, PermissionDenied

BASE = "https://www.googleapis.com/drive/v3"
DOC_MIME = "application/vnd.google-apps.document"
FILE_FIELDS = "id,name,mimeType,createdTime,modifiedTime,webViewLink"
SHARED_DRIVES = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}


def escape_q(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def gemini_notes_query(
    name_contains: str, created_after: datetime | None, created_before: datetime | None
) -> str:
    parts = [
        f"mimeType = '{DOC_MIME}'",
        "trashed = false",
        f"name contains '{escape_q(GEMINI_NOTES_MARKER)}'",
    ]
    needle = (name_contains or "").strip()
    if needle:
        parts.append(f"name contains '{escape_q(needle)}'")
    if created_after is not None:
        parts.append(f"createdTime >= '{_rfc3339(created_after)}'")
    if created_before is not None:
        parts.append(f"createdTime <= '{_rfc3339(created_before)}'")
    return " and ".join(parts)


class RealDriveClient:
    def __init__(self, http: GoogleHttp, display_tz: ZoneInfo | str = "Asia/Kolkata") -> None:
        self.http = http
        self.tz = ZoneInfo(display_tz) if isinstance(display_tz, str) else display_tz

    def search(
        self,
        connection_email: str,
        name_contains: str,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list[DriveFile]:
        body = self.http.get(
            connection_email,
            f"{BASE}/files",
            params={
                "q": gemini_notes_query(name_contains, created_after, created_before),
                "fields": f"files({FILE_FIELDS})",
                "orderBy": "createdTime desc",
                "pageSize": 25,
                "corpora": "allDrives",
                **SHARED_DRIVES,
            },
        )
        return [self._file(f) for f in body.get("files") or []]

    def get_file(self, connection_email: str, file_id: str) -> DriveFile | None:
        try:
            body = self.http.get(
                connection_email,
                f"{BASE}/files/{file_id}",
                params={"fields": FILE_FIELDS, "supportsAllDrives": True},
            )
        except (NotFoundError, PermissionDenied):
            return None
        return self._file(body)

    def can_edit(self, connection_email: str, file_id: str) -> bool:
        """``files.get?fields=name,capabilities/canEdit``: False when unreadable, too."""
        try:
            body = self.http.get(
                connection_email,
                f"{BASE}/files/{file_id}",
                params={"fields": "name,capabilities/canEdit", "supportsAllDrives": True},
            )
        except (NotFoundError, PermissionDenied):
            return False
        return bool((body.get("capabilities") or {}).get("canEdit"))

    def _file(self, raw: dict[str, Any]) -> DriveFile:
        return DriveFile(
            id=str(raw.get("id") or ""),
            name=str(raw.get("name") or ""),
            mime_type=str(raw.get("mimeType") or DOC_MIME),
            modified_at=_parse_dt(raw.get("modifiedTime"), self.tz),
            created_at=_parse_dt(raw.get("createdTime"), self.tz),
            web_view_link=str(raw.get("webViewLink") or ""),
        )


def _parse_dt(raw: Any, tz: ZoneInfo) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)).astimezone(tz)


def _rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    return value.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
