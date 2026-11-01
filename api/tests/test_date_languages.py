"""Due phrases in the other languages of NOTES_LANGUAGES read like their English versions."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import date_languages
from app.config import Settings
from app.extract.postprocess import parse_due
from app.main import create_app
from app.sheets.dates import parse_date
from tests.conftest import make_settings, saved_meeting_id

# A Tuesday: the meeting's week runs Mon 19 - Sun 25 October.
MEETING = datetime(2026, 10, 20, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
FRIDAY = date(2026, 10, 23)


@pytest.fixture(autouse=True)
def _languages() -> Iterator[None]:
    date_languages.configure(["de", "fr", "es", "pt", "it", "nl", "ja"])
    yield
    date_languages.configure([])


def due(text: str) -> date | None:
    parsed = parse_due(text, MEETING)
    return parsed.date() if parsed else None


@pytest.mark.parametrize(
    "phrase",
    [
        "bis Freitag",
        "Freitag",
        "avant vendredi",
        "d'ici vendredi",
        "para el viernes",
        "até sexta",
        "entro venerdì",
        "voor vrijdag",
        "金曜日まで",
    ],
)
def test_a_weekday_behind_a_preposition_is_read(phrase: str) -> None:
    assert due(phrase) == FRIDAY


@pytest.mark.parametrize(
    ("phrase", "english"),
    [
        ("nächsten Montag", "next Monday"),
        ("bis kommenden Montag", "next Monday"),
        ("lundi prochain", "next Monday"),
        ("d'ici lundi prochain", "next Monday"),
        ("el próximo lunes", "next Monday"),
        ("prossimo lunedì", "next Monday"),
        ("volgende maandag", "next Monday"),
        ("bis Ende der Woche", "end of week"),
        ("fin de la semaine", "end of week"),
        ("fin du mois", "end of month"),
        ("até o fim do mês", "end of month"),
        ("la semana que viene", "next week"),
        ("entro fine mese", "end of month"),
        ("uiterlijk eind van de maand", "end of month"),
    ],
)
def test_shorthand_follows_the_english_rule(phrase: str, english: str) -> None:
    """ "nächsten Montag" is the Monday of the following week, exactly as "next Monday" is."""
    assert due(english) is not None
    assert due(phrase) == due(english)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("bis zum 31.10.", date(2026, 10, 31)),
        ("jusqu\u2019au 30 octobre", date(2026, 10, 30)),
        ("antes del 30 de octubre", date(2026, 10, 30)),
        ("entro il 30 ottobre", date(2026, 10, 30)),
    ],
)
def test_a_date_behind_a_preposition_is_read(phrase: str, expected: date) -> None:
    assert due(phrase) == expected


def test_english_is_unchanged_and_read_first() -> None:
    assert due("by Friday") == FRIDAY
    assert due("next Monday") == date(2026, 10, 26)


def test_only_the_configured_languages_are_read() -> None:
    date_languages.configure([])
    assert due("bis Freitag") is None
    date_languages.configure(["de"])
    assert due("bis Freitag") == FRIDAY
    assert due("avant vendredi") is None


def test_nonsense_stays_empty() -> None:
    assert due("bis irgendwann") is None
    assert due("quand on peut") is None


def test_the_sheets_date_column_reads_them_too() -> None:
    assert parse_date("bis Freitag", MEETING) == FRIDAY
    assert parse_date("fin du mois", MEETING) == date(2026, 10, 31)


def test_an_unknown_language_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match=r"NOTES_LANGUAGES.*xx"):
        date_languages.configure(["de", "xx"])


def test_the_setting_is_a_list_with_english_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTES_LANGUAGES", " de, fr ,de,")
    settings = Settings(_env_file=None)
    assert settings.notes_language_list == ["de", "fr"]
    assert date_languages.configure(settings.notes_language_list) == ("en", "de", "fr")
    assert Settings(_env_file=None, notes_languages="").notes_language_list == []


def test_the_api_reads_a_point_typed_in_german_once_the_app_is_set_to_it(tmp_path: Path) -> None:
    """The app configures the languages from its settings: a point typed with "bis Freitag" gets
    the first Friday from its meeting, and "nächsten Montag" the same day "next Monday" gives."""
    with TestClient(create_app(make_settings(tmp_path, notes_languages="de"))) as client:
        meeting_id = saved_meeting_id(client, "Mobile roadmap review")
        meeting = client.get(f"/meetings/{meeting_id}").json()
        start = date.fromisoformat(meeting["start_at"][:10])
        created = client.post(
            "/points", json={"meeting_id": meeting_id, "text": "Fragebogen senden", "due_text": "bis Freitag"}
        )
        assert created.status_code == 201, created.text
        friday = date.fromisoformat(created.json()["due_date"][:10])
        assert friday.weekday() == 4 and 0 <= (friday - start).days < 7
        moved = client.patch(f"/points/{created.json()['id']}", json={"due_text": "nächsten Montag"})
        english = client.patch(f"/points/{created.json()['id']}", json={"due_text": "next Monday"})
        assert moved.json()["due_date"] == english.json()["due_date"]
        assert date.fromisoformat(moved.json()["due_date"][:10]).weekday() == 0
