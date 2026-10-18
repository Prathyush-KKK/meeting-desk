"""Calendar and Drive contract tests against recorded responses."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.google.calendar import FIELDS, RealCalendarClient
from app.google.drive import RealDriveClient, gemini_notes_query
from app.google.interface import RateLimited
from tests.google_mock import MockGoogleApi, json_response

IST = ZoneInfo("Asia/Kolkata")
ME = "daniel.okafor@example.com"
WINDOW = (datetime(2026, 9, 15, 0, 0, tzinfo=IST), datetime(2026, 9, 22, 23, 59, 59, tzinfo=IST))


def _calendar(api: MockGoogleApi, **kw) -> RealCalendarClient:
    return RealCalendarClient(api.http(), "Asia/Kolkata", **kw)


def test_events_list_sends_single_events_ordered_by_start_with_a_fields_mask_and_follows_pages() -> None:
    api = MockGoogleApi().on(
        "GET",
        "/calendars/primary/events",
        [
            lambda r: json_response("calendar_events_page1.json"),
            lambda r: json_response("calendar_events_page2.json"),
        ],
    )
    events = _calendar(api).list_events(ME, *WINDOW)

    first, second = api.sent("GET", "/calendars/primary/events")
    params = MockGoogleApi.params(first)
    assert params["singleEvents"] == ["true"]
    assert params["orderBy"] == ["startTime"]
    assert params["timeMin"] == ["2026-09-15T00:00:00+05:30"]
    assert params["timeMax"] == ["2026-09-22T23:59:59+05:30"]
    assert params["fields"] == [FIELDS]
    assert "pageToken" not in params
    assert MockGoogleApi.params(second)["pageToken"] == [
        "CigKGjNpY2ZjYnRxb2VpdDVnZ2JqYjRiNXVrYWRxGAEggIDAoLzk5a4YGg0IABIAGLDQ8-2Tt48DIAEoAQ"
    ]
    # Both pages, cancelled events dropped, newest first.
    assert [e.title for e in events] == ["Team offsite", "Northwind vendor call", "Mobile roadmap review"]


def test_event_fields_land_where_models_py_stores_them() -> None:
    api = MockGoogleApi().on(
        "GET",
        "/calendars/primary/events",
        [
            lambda r: json_response("calendar_events_page1.json"),
            lambda r: json_response("calendar_events_page2.json"),
        ],
    )
    events = {e.title: e for e in _calendar(api).list_events(ME, *WINDOW)}
    review = events["Mobile roadmap review"]
    assert review.id == "3icfcbtqoeit5ggbjb4b5ukadq_20260919T103000Z"
    assert review.ical_uid == "3icfcbtqoeit5ggbjb4b5ukadq@google.com"
    assert review.recurring_event_id == "3icfcbtqoeit5ggbjb4b5ukadq"
    assert review.calendar_id == ME
    assert review.start_at == datetime(2026, 9, 19, 16, 0, tzinfo=IST)
    assert review.end_at.strftime("%H:%M") == "16:45"
    assert review.timezone == "Asia/Kolkata"
    assert review.organizer_email == ME
    assert review.organizer_name == "Daniel Okafor"
    assert [(a.email, a.name, a.response) for a in review.attendees] == [
        (ME, "Daniel Okafor", "accepted"),
        ("anna.moreno@example.com", "Anna Moreno", "accepted"),
        ("noah.s@example.com", "", "tentative"),
    ]
    assert review.conference == {
        "meet_link": "https://meet.google.com/abc-defg-hij",
        "phone": "tel:+91-22-7127-0000",
        "solution": "Google Meet",
    }
    assert [a.to_dict() for a in review.attachments] == [
        {
            "title": "Mobile roadmap review - 2026/09/19 16:00 IST - Notes by Gemini",
            "kind": "doc",
            "file_id": "1qX9Lm3kNotesDocIdForMobile",
            "url": "https://docs.google.com/document/d/1qX9Lm3kNotesDocIdForMobile/edit",
        }
    ]
    assert review.html_link.startswith("https://www.google.com/calendar/event?eid=")
    assert review.updated_at == datetime(2026, 9, 18, 11, 42, 44, 101000, tzinfo=IST)


def test_times_in_the_organizers_zone_are_shown_in_asia_kolkata_and_the_zone_is_kept() -> None:
    api = MockGoogleApi().on(
        "GET",
        "/calendars/primary/events",
        [
            lambda r: json_response("calendar_events_page1.json"),
            lambda r: json_response("calendar_events_page2.json"),
        ],
    )
    events = {e.title: e for e in _calendar(api).list_events(ME, *WINDOW)}
    call = events["Northwind vendor call"]
    assert call.start_at.strftime("%Y-%m-%d %H:%M %z") == "2026-09-21 19:00 +0530"
    assert call.timezone == "America/New_York"
    assert call.conference == {}
    assert call.attachments == []


def test_an_all_day_event_starts_at_midnight_in_the_display_zone() -> None:
    api = MockGoogleApi().on("GET", "/calendars/primary/events", "calendar_events_page2.json")
    (offsite,) = _calendar(api).list_events(ME, *WINDOW)
    assert offsite.start_at == datetime(2026, 9, 22, 0, 0, tzinfo=IST)
    assert offsite.end_at == datetime(2026, 9, 23, 0, 0, tzinfo=IST)


def test_the_list_is_cached_sixty_seconds_per_connection_and_window() -> None:
    api = MockGoogleApi().on("GET", "/calendars/primary/events", "calendar_events_page2.json")
    clock = [0.0]
    calendar = _calendar(api, cache_seconds=60, now=lambda: clock[0])
    calendar.list_events(ME, *WINDOW)
    calendar.list_events(ME, *WINDOW)
    assert len(api.requests) == 1
    calendar.list_events("alex.s@example.com", *WINDOW)  # another connection: its own read
    assert len(api.requests) == 2
    clock[0] = 61
    calendar.list_events(ME, *WINDOW)
    assert len(api.requests) == 3
    calendar.forget(ME)
    calendar.list_events(ME, *WINDOW)
    assert len(api.requests) == 4


def test_a_rate_limited_connection_raises_without_in_call_retries() -> None:
    api = MockGoogleApi().on(
        "GET", "/calendars/primary/events", lambda r: json_response("error_403_rate_limit.json", 403)
    )
    calendar = _calendar(api)
    with pytest.raises(RateLimited):
        calendar.list_events(ME, *WINDOW)
    assert len(api.requests) == 1  # no retry loop on the list path; the connection is backed off
    with pytest.raises(RateLimited):
        calendar.list_events(ME, *WINDOW)
    assert len(api.requests) == 1


def test_get_event_returns_none_on_404() -> None:
    api = MockGoogleApi().on("GET", "/events/nope", lambda r: json_response("error_404.json", 404))
    assert _calendar(api).get_event(ME, "nope") is None
    api.on(
        "GET",
        "/events/real",
        lambda r: json_response(json_response("calendar_events_page1.json").json()["items"][0]),
    )
    event = _calendar(api).get_event(ME, "real")
    assert event is not None and event.title == "Mobile roadmap review"


def test_a_page_token_that_repeats_does_not_loop_forever() -> None:
    api = MockGoogleApi().on("GET", "/calendars/primary/events", "calendar_events_page1.json")
    events = _calendar(api).list_events(ME, *WINDOW)
    assert len(api.requests) == 2  # the page, one follow-up with the same token, then stop
    assert len(events) == 4  # both pages carried the same items


# --- Drive ------------------------------------------------------------------------------------------


def test_gemini_notes_query_is_scoped_to_docs_by_name_and_creation_window() -> None:
    q = gemini_notes_query(
        "Mobile roadmap review",
        datetime(2026, 9, 19, 14, 0, tzinfo=IST),
        datetime(2026, 9, 19, 18, 0, tzinfo=IST),
    )
    assert q == (
        "mimeType = 'application/vnd.google-apps.document' and trashed = false and "
        "name contains 'Notes by Gemini' and name contains 'Mobile roadmap review' and "
        "createdTime >= '2026-09-19T08:30:00Z' and createdTime <= '2026-09-19T12:30:00Z'"
    )
    assert "name contains 'Alex\\'s 1:1'" in gemini_notes_query("Alex's 1:1", None, None)


def test_drive_search_sends_the_query_and_parses_files_with_creation_time() -> None:
    api = MockGoogleApi().on("GET", "/drive/v3/files", "drive_files_list.json")
    drive = RealDriveClient(api.http(), "Asia/Kolkata")
    start = datetime(2026, 9, 19, 16, 0, tzinfo=IST)
    files = drive.search(ME, "Mobile roadmap review", start, start)
    params = MockGoogleApi.params(api.requests[0])
    assert params["fields"] == ["files(id,name,mimeType,createdTime,modifiedTime,webViewLink)"]
    assert params["supportsAllDrives"] == ["true"]
    assert params["includeItemsFromAllDrives"] == ["true"]
    assert params["orderBy"] == ["createdTime desc"]
    assert "name contains 'Notes by Gemini'" in params["q"][0]
    assert files[0].id == "1qX9Lm3kNotesDocIdForMobile"
    assert files[0].created_at == datetime(2026, 9, 19, 16, 49, 41, 226000, tzinfo=IST)
    assert files[0].modified_at.date().isoformat() == "2026-09-21"
    assert files[0].web_view_link.startswith("https://docs.google.com/document/d/")


def test_can_edit_reads_capabilities_and_treats_refusals_as_false() -> None:
    api = (
        MockGoogleApi()
        .on("GET", "/files/editable", "drive_file_get_can_edit.json")
        .on("GET", "/files/readonly", "drive_file_get_readonly.json")
        .on("GET", "/files/hidden", lambda r: json_response("error_404.json", 404))
        .on("GET", "/files/private", lambda r: json_response("error_403_forbidden.json", 403))
    )
    drive = RealDriveClient(api.http())
    assert drive.can_edit(ME, "editable") is True
    assert MockGoogleApi.params(api.requests[0])["fields"] == ["name,capabilities/canEdit"]
    assert drive.can_edit(ME, "readonly") is False
    assert drive.can_edit(ME, "hidden") is False
    assert drive.can_edit(ME, "private") is False


def test_get_file_returns_the_file_or_none() -> None:
    api = (
        MockGoogleApi()
        .on("GET", "/files/1qX9Lm3kNotesDocIdForMobile", "drive_file_get_full.json")
        .on("GET", "/files/gone", lambda r: json_response("error_404.json", 404))
    )
    drive = RealDriveClient(api.http())
    found = drive.get_file(ME, "1qX9Lm3kNotesDocIdForMobile")
    assert found is not None and found.name.endswith("Notes by Gemini")
    assert drive.get_file(ME, "gone") is None
