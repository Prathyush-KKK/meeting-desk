"""Docs: ``documents.get?includeTabsContent=true``, walked tab by tab into plain text.

A Notes by Gemini doc has three tabs (Quick notes, Full notes, Transcript, nested under the first
in newer docs). ``DocDocument.tabs`` is the flattened tree in document order; ``preferred_tab``
picks "Full notes" over "Quick notes" the way the import route does. Each tab's text keeps
headings and bullets as their own lines, which is what the rule-based extractor and the prompt
both key on.
"""

from __future__ import annotations

import re
from typing import Any

from app.google.http import GoogleHttp
from app.google.interface import DocDocument, DocTab

BASE = "https://docs.googleapis.com/v1"
PREFERRED_TABS = ("Full notes", "Quick notes")
_BLANKS_RE = re.compile(r"\n{3,}")


class RealDocsClient:
    def __init__(self, http: GoogleHttp) -> None:
        self.http = http

    def get_document(
        self, connection_email: str, document_id: str, include_tabs_content: bool = True
    ) -> DocDocument:
        body = self.http.get(
            connection_email,
            f"{BASE}/documents/{document_id}",
            params={"includeTabsContent": True} if include_tabs_content else None,
        )
        return parse_document(body, include_tabs_content)


def preferred_tab(document: DocDocument) -> DocTab | None:
    for name in PREFERRED_TABS:
        tab = document.tab(name)
        if tab is not None:
            return tab
    return document.tabs[0] if document.tabs else None


# --- parsing ----------------------------------------------------------------------------------------


def parse_document(body: dict[str, Any], include_tabs_content: bool = True) -> DocDocument:
    doc = DocDocument(id=str(body.get("documentId") or ""), title=str(body.get("title") or ""))
    tabs = body.get("tabs")
    if tabs and include_tabs_content:
        _walk_tabs(tabs, doc.tabs)
    elif tabs:
        first = tabs[0]
        props = first.get("tabProperties") or {}
        content = ((first.get("documentTab") or {}).get("body") or {}).get("content") or []
        doc.tabs.append(
            DocTab(id=str(props.get("tabId") or ""), title=str(props.get("title") or ""), text="")
        )
        doc.tabs[0].text = elements_text(content)
    else:
        # A doc without tabs metadata: the body is the single tab.
        content = (body.get("body") or {}).get("content") or []
        doc.tabs.append(DocTab(id="", title=doc.title, text=elements_text(content)))
    return doc


def _walk_tabs(tabs: list[dict[str, Any]], out: list[DocTab]) -> None:
    """Depth-first, document order: a tab, then its child tabs."""
    for tab in tabs:
        props = tab.get("tabProperties") or {}
        content = ((tab.get("documentTab") or {}).get("body") or {}).get("content") or []
        out.append(
            DocTab(
                id=str(props.get("tabId") or ""),
                title=str(props.get("title") or ""),
                text=elements_text(content),
            )
        )
        if tab.get("childTabs"):
            _walk_tabs(tab["childTabs"], out)


def elements_text(elements: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    _collect(elements, lines)
    text = "\n".join(lines)
    return _BLANKS_RE.sub("\n\n", text).strip()


def _collect(elements: list[dict[str, Any]], lines: list[str]) -> None:
    for element in elements:
        if "paragraph" in element:
            lines.extend(_paragraph_lines(element["paragraph"]))
        elif "table" in element:
            for row in element["table"].get("tableRows") or []:
                cells = []
                for cell in row.get("tableCells") or []:
                    inner: list[str] = []
                    _collect(cell.get("content") or [], inner)
                    cells.append(" ".join(ln.strip() for ln in inner if ln.strip()))
                if any(cells):
                    lines.append(" | ".join(cells))
        # sectionBreak, tableOfContents: nothing to say.


def _paragraph_lines(paragraph: dict[str, Any]) -> list[str]:
    text = "".join(_element_text(e) for e in paragraph.get("elements") or [])
    text = text.replace("\x0b", "\n").rstrip("\n")
    if not text.strip():
        return [""]
    style = str((paragraph.get("paragraphStyle") or {}).get("namedStyleType") or "")
    bullet = paragraph.get("bullet")
    out: list[str] = []
    if style.startswith("HEADING") or style in ("TITLE", "SUBTITLE"):
        # A heading is a line of its own with air above it, like "The Next Steps".
        out.append("")
        out.append(text.strip())
        return out
    if bullet is not None:
        level = int(bullet.get("nestingLevel") or 0)
        return ["  " * level + "- " + text.strip()]
    return [text.rstrip()]


def _element_text(element: dict[str, Any]) -> str:
    if "textRun" in element:
        return str(element["textRun"].get("content") or "")
    if "richLink" in element:
        props = element["richLink"].get("richLinkProperties") or {}
        return str(props.get("title") or props.get("uri") or "")
    if "person" in element:
        props = element["person"].get("personProperties") or {}
        return str(props.get("name") or props.get("email") or "")
    if "dateElement" in element:
        props = element["dateElement"].get("dateElementProperties") or {}
        return str(props.get("displayText") or "")
    return ""
