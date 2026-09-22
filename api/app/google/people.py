"""People: ``people:searchDirectoryPeople`` for owner resolution.

A prefix query over the Workspace directory (domain profiles). Post-processing calls it for an
owner the attendee list did not settle, with the first token of the name.
"""

from __future__ import annotations

from typing import Any

from app.google.http import GoogleHttp
from app.google.interface import DirectoryPerson

BASE = "https://people.googleapis.com/v1"
PAGE_SIZE = 20


class RealPeopleClient:
    def __init__(self, http: GoogleHttp) -> None:
        self.http = http

    def search_directory(self, connection_email: str, query: str) -> list[DirectoryPerson]:
        needle = (query or "").strip()
        if not needle:
            return []
        body = self.http.get(
            connection_email,
            f"{BASE}/people:searchDirectoryPeople",
            params={
                "query": needle,
                "readMask": "names,emailAddresses",
                "sources": "DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE",
                "pageSize": PAGE_SIZE,
            },
        )
        out: list[DirectoryPerson] = []
        for person in body.get("people") or []:
            parsed = parse_person(person)
            if parsed is not None:
                out.append(parsed)
        return out


def parse_person(person: dict[str, Any]) -> DirectoryPerson | None:
    names = person.get("names") or []
    emails = person.get("emailAddresses") or []
    if not emails:
        return None
    primary = next((e for e in emails if (e.get("metadata") or {}).get("primary")), emails[0])
    email = str(primary.get("value") or "").strip().lower()
    if not email:
        return None
    name = str(names[0].get("displayName") or "") if names else ""
    return DirectoryPerson(name=name or email.split("@")[0], email=email)
