"""Docs, Gmail and People contract tests against recorded responses."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.google.docs import RealDocsClient, preferred_tab
from app.google.gmail import RealGmailClient, html_to_text
from app.google.interface import PermissionDenied, quoted_phrase, recap_query
from app.google.people import RealPeopleClient
from tests.google_mock import MockGoogleApi, json_response

IST = ZoneInfo("Asia/Kolkata")
ME = "daniel.okafor@example.com"


# --- Docs -------------------------------------------------------------------------------------------


def test_documents_get_asks_for_tabs_content_and_walks_the_tab_tree() -> None:
    api = MockGoogleApi().on("GET", "/v1/documents/1qX9Lm3kNotesDocIdForMobile", "docs_document_tabs.json")
    doc = RealDocsClient(api.http()).get_document(ME, "1qX9Lm3kNotesDocIdForMobile")
    assert MockGoogleApi.params(api.requests[0]) == {"includeTabsContent": ["true"]}
    assert doc.id == "1qX9Lm3kNotesDocIdForMobile"
    assert doc.title.endswith("Notes by Gemini")
    # Depth-first, document order: the transcript is nested two levels down.
    assert [(t.id, t.title) for t in doc.tabs] == [
        ("t.0", "Quick notes"),
        ("t.1", "Full notes"),
        ("t.2", "Transcript"),
    ]
    assert preferred_tab(doc).title == "Full notes"


def test_tab_text_keeps_headings_bullets_tables_and_people_as_lines() -> None:
    api = MockGoogleApi().on("GET", "/v1/documents/", "docs_document_tabs.json")
    doc = RealDocsClient(api.http()).get_document(ME, "1qX9Lm3kNotesDocIdForMobile")
    text = doc.tab("Full notes").text
    assert text.startswith("Mobile roadmap review\n\nSummary\n")
    assert "\n\nThe Next Steps\n- Anna Moreno: Review dataset for currency information by 3 Oct\n" in text
    assert "- Weight data: the OpenRates mirror is missing portion weights for 40% of Indian items.\n" in text
    assert "  - Anna Moreno will review the dataset for currency information.\n" in text  # nested bullet
    assert "Item | Owner\nVendor questionnaire | Alex S\n" in text  # the table
    assert "- Daniel: Mirror OpenRates before launch\n" in text  # a smart-chip person
    assert "\n\n\n" not in text  # runs of blank paragraphs collapse
    assert text.endswith("Risk: the upload flag has no rollback plan")
    assert doc.tab("Transcript").text.startswith("00:00 Daniel Okafor:")


def test_a_doc_without_tabs_is_one_tab_named_after_the_document() -> None:
    api = MockGoogleApi().on("GET", "/v1/documents/", "docs_document_no_tabs.json")
    doc = RealDocsClient(api.http()).get_document(ME, "1legacyDocWithoutTabs")
    assert [t.title for t in doc.tabs] == ["Old style doc"]
    assert doc.tabs[0].text == "Only a body\nOne line."


def test_without_tabs_content_only_the_first_tab_comes_back() -> None:
    api = MockGoogleApi().on("GET", "/v1/documents/", "docs_document_tabs.json")
    doc = RealDocsClient(api.http()).get_document(ME, "x", include_tabs_content=False)
    assert "includeTabsContent" not in MockGoogleApi.params(api.requests[0])
    assert [t.title for t in doc.tabs] == ["Quick notes"]


def test_a_doc_not_shared_with_the_connection_is_permission_denied() -> None:
    api = MockGoogleApi().on(
        "GET", "/v1/documents/", lambda r: json_response("error_403_forbidden.json", 403)
    )
    with pytest.raises(PermissionDenied):
        RealDocsClient(api.http()).get_document(ME, "secret")


# --- Gmail ------------------------------------------------------------------------------------------


def test_recap_query_and_its_quoted_phrase() -> None:
    q = recap_query('Mobile "roadmap" review', datetime(2026, 9, 19, 16, 0, tzinfo=IST))
    assert q == 'from:gemini-notes@google.com "Mobile  roadmap  review" after:2026/09/19'
    assert quoted_phrase(q) == "Mobile  roadmap  review"
    assert quoted_phrase("Recap: Platform squad sync") == "Recap: Platform squad sync"


def test_gmail_search_lists_then_fetches_each_message_and_turns_html_into_text() -> None:
    api = (
        MockGoogleApi()
        .on("GET", "/messages/18f2c1a9b7e4d3f0", "gmail_message_full.json")
        .on("GET", "/gmail/v1/users/me/messages", "gmail_messages_list.json")
    )
    query = recap_query("Mobile roadmap review", datetime(2026, 9, 19, tzinfo=IST))
    (message,) = RealGmailClient(api.http(), "Asia/Kolkata").search_messages(ME, query)

    listing, fetch = api.requests
    assert MockGoogleApi.params(listing) == {"q": [query], "maxResults": ["10"]}
    assert MockGoogleApi.params(fetch) == {"format": ["full"]}
    assert message.id == "18f2c1a9b7e4d3f0"
    assert message.subject == "Recap: Mobile roadmap review"
    assert message.from_email == "gemini-notes@google.com"
    assert message.received_at == datetime(2026, 9, 19, 16, 40, 1, tzinfo=IST)
    assert message.body.startswith("Recap: Mobile roadmap review\n\nHi Daniel,\nHere is the recap")
    assert "\nNext steps\n\n- Anna Moreno: Review dataset for currency information by 3 Oct\n" in message.body
    assert "dataset gaps & agreed" in message.body  # entities decoded
    assert "track()" not in message.body and "color:red" not in message.body


def test_html_to_text_keeps_breaks_and_list_items() -> None:
    assert html_to_text("<p>a<br>b</p><ul><li>one</li><li>two</li></ul>") == "a\nb\n\n- one\n- two"
    assert html_to_text("") == ""


# --- People -----------------------------------------------------------------------------------------


def test_search_directory_people_is_a_prefix_query_over_domain_profiles() -> None:
    api = MockGoogleApi().on("GET", "/people:searchDirectoryPeople", "people_search.json")
    people = RealPeopleClient(api.http()).search_directory(ME, "Sham")
    assert MockGoogleApi.params(api.requests[0]) == {
        "query": ["Sham"],
        "readMask": ["names,emailAddresses"],
        "sources": ["DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE"],
        "pageSize": ["20"],
    }
    # The primary address wins, addresses are lower-cased, a profile without mail is skipped.
    assert [(p.name, p.email) for p in people] == [
        ("Sofia Silva", "sofia.silva@example.com"),
        ("Shamik Bose", "shamik.bose@example.com"),
    ]
    assert RealPeopleClient(api.http()).search_directory(ME, "   ") == []
