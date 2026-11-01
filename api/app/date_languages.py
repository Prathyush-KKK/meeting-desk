"""Due phrases in the other languages the notes are written in (``NOTES_LANGUAGES``).

dateparser reads a bare date in any of its languages ("Freitag", "vendredi", "3 de octubre") but
nothing behind a preposition ("bis Freitag", "avant vendredi", "entro venerdì"), and in most of
them it has no "next Monday" or "end of the week". English has its own handling
(``app/relative_dates.py`` and the leading words in ``extract/postprocess.py``); this module is
the same for each other configured language, tried after English has found nothing:

* the prepositions and articles in front of a due phrase come off, one at a time, the way "by"
  and "before" do in English (and a trailing particle, for languages that put it after);
* "end of the week / month" and "next week / month" are translated into the English phrase, and
  "next <weekday>" into "next <English weekday>", so they follow the rules in
  ``relative_dates`` exactly as their English versions do;
* whatever is left goes to dateparser in that language alone.

A language without a table here still gets dateparser's own reading of the bare phrase.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import dateparser
from dateparser.data.languages_info import language_order
from dateparser.languages import default_loader

from app.relative_dates import resolve as resolve_relative

ENGLISH = "en"
ENGLISH_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(frozen=True, slots=True)
class Words:
    leading: tuple[str, ...] = ()  # prepositions and articles before a date
    trailing: tuple[str, ...] = ()  # particles after one ("金曜日まで")
    next_words: frozenset[str] = frozenset()  # "next", wherever it sits ("lundi prochain")
    periods: dict[str, str] = field(default_factory=dict)  # phrase -> the English relative_dates reads


EOW, EOM, NEXT_WEEK, NEXT_MONTH = "end of week", "end of month", "next week", "next month"

WORDS: dict[str, Words] = {
    "de": Words(
        leading=(
            "bis spätestens",
            "bis zum",
            "bis zur",
            "bis",
            "spätestens",
            "vor dem",
            "vor der",
            "vor",
            "am",
            "zum",
            "zur",
            "fällig",
            "den",
            "dem",
            "der",
            "die",
        ),
        next_words=frozenset({"nächsten", "nächster", "nächste", "kommenden", "kommender", "kommende"}),
        periods={
            "ende der woche": EOW,
            "ende dieser woche": EOW,
            "wochenende": EOW,
            "ende der nächsten woche": "end of next week",
            "ende nächster woche": "end of next week",
            "ende des monats": EOM,
            "ende dieses monats": EOM,
            "monatsende": EOM,
            "ende des nächsten monats": "end of next month",
            "nächste woche": NEXT_WEEK,
            "nächster woche": NEXT_WEEK,
            "kommende woche": NEXT_WEEK,
            "nächsten monat": NEXT_MONTH,
            "kommenden monat": NEXT_MONTH,
        },
    ),
    "fr": Words(
        leading=(
            "au plus tard le",
            "au plus tard",
            "jusqu'au",
            "jusqu'à",
            "d'ici le",
            "d'ici à",
            "d'ici",
            "avant le",
            "avant",
            "pour le",
            "pour",
            "le",
            "la",
            "l'",
        ),
        next_words=frozenset({"prochain", "prochaine"}),
        periods={
            "fin de semaine": EOW,
            "fin de la semaine": EOW,
            "fin de cette semaine": EOW,
            "fin de la semaine prochaine": "end of next week",
            "fin du mois": EOM,
            "fin de ce mois": EOM,
            "fin du mois prochain": "end of next month",
            "semaine prochaine": NEXT_WEEK,
            "la semaine prochaine": NEXT_WEEK,
            "mois prochain": NEXT_MONTH,
            "le mois prochain": NEXT_MONTH,
        },
    ),
    "es": Words(
        leading=(
            "a más tardar el",
            "a más tardar",
            "antes del",
            "antes de",
            "hasta el",
            "hasta",
            "para el",
            "para",
            "el",
            "la",
        ),
        next_words=frozenset({"próximo", "próxima", "proximo", "proxima"}),
        periods={
            "fin de semana": EOW,
            "final de la semana": EOW,
            "fin de esta semana": EOW,
            "fin de mes": EOM,
            "fin del mes": EOM,
            "final del mes": EOM,
            "fin de este mes": EOM,
            "próxima semana": NEXT_WEEK,
            "la próxima semana": NEXT_WEEK,
            "la semana que viene": NEXT_WEEK,
            "semana que viene": NEXT_WEEK,
            "próximo mes": NEXT_MONTH,
            "el próximo mes": NEXT_MONTH,
            "el mes que viene": NEXT_MONTH,
            "mes que viene": NEXT_MONTH,
        },
    ),
    "pt": Words(
        leading=(
            "até o",
            "até a",
            "até ao",
            "até à",
            "até",
            "antes do",
            "antes da",
            "antes de",
            "para o",
            "para a",
            "para",
            "no",
            "na",
            "em",
            "o",
            "a",
        ),
        next_words=frozenset({"próximo", "próxima", "proximo", "proxima"}),
        periods={
            "fim da semana": EOW,
            "final da semana": EOW,
            "fim desta semana": EOW,
            "fim do mês": EOM,
            "final do mês": EOM,
            "fim deste mês": EOM,
            "próxima semana": NEXT_WEEK,
            "a próxima semana": NEXT_WEEK,
            "semana que vem": NEXT_WEEK,
            "próximo mês": NEXT_MONTH,
            "o próximo mês": NEXT_MONTH,
            "mês que vem": NEXT_MONTH,
        },
    ),
    "it": Words(
        leading=(
            "entro il",
            "entro la",
            "entro",
            "prima del",
            "prima della",
            "prima di",
            "per il",
            "per la",
            "per",
            "il",
            "la",
            "lo",
        ),
        next_words=frozenset({"prossimo", "prossima"}),
        periods={
            "fine settimana": EOW,
            "fine della settimana": EOW,
            "fine di questa settimana": EOW,
            "fine mese": EOM,
            "fine del mese": EOM,
            "fine di questo mese": EOM,
            "settimana prossima": NEXT_WEEK,
            "la settimana prossima": NEXT_WEEK,
            "la prossima settimana": NEXT_WEEK,
            "prossima settimana": NEXT_WEEK,
            "mese prossimo": NEXT_MONTH,
            "il mese prossimo": NEXT_MONTH,
            "il prossimo mese": NEXT_MONTH,
            "prossimo mese": NEXT_MONTH,
        },
    ),
    "nl": Words(
        leading=("uiterlijk op", "uiterlijk", "vóór", "voor", "tegen", "op", "de", "het"),
        next_words=frozenset({"volgende", "komende"}),
        periods={
            "eind van de week": EOW,
            "einde van de week": EOW,
            "eind deze week": EOW,
            "einde van deze week": EOW,
            "eind van de maand": EOM,
            "einde van de maand": EOM,
            "eind deze maand": EOM,
            "volgende week": NEXT_WEEK,
            "komende week": NEXT_WEEK,
            "volgende maand": NEXT_MONTH,
            "komende maand": NEXT_MONTH,
        },
    ),
    "hi": Words(trailing=("तक", "से पहले")),
    "ja": Words(trailing=("までに", "まで")),
}

_EDGE_PUNCT_RE = re.compile(r"^[\s,;:!?()\"]+|[\s,;:!?()\"]+$")

_languages: tuple[str, ...] | None = None


def configure(codes: Iterable[str]) -> tuple[str, ...]:
    """The languages due phrases are read in, English first; unknown codes are an error."""
    global _languages
    wanted = [c.strip() for c in codes if c and c.strip()]
    unknown = [c for c in wanted if c not in language_order]
    if unknown:
        raise ValueError(f"NOTES_LANGUAGES: dateparser has no language {', '.join(unknown)}")
    _languages = tuple(dict.fromkeys([ENGLISH, *wanted]))
    return _languages


def languages() -> tuple[str, ...]:
    if _languages is None:
        from app.config import get_settings

        return configure(get_settings().notes_language_list)
    return _languages


def parse(text: str, base: datetime, settings: dict[str, Any]) -> date | None:
    """The date a due phrase means in one of the configured languages other than English."""
    for language in languages():
        if language != ENGLISH:
            found = _parse_in(text, language, base, settings)
            if found is not None:
                return found
    return None


def _parse_in(text: str, language: str, base: datetime, settings: dict[str, Any]) -> date | None:
    words = WORDS.get(language, Words())
    for candidate in _candidates(text, words):
        english = words.periods.get(candidate) or _next_weekday(candidate, language, words)
        if english:
            return resolve_relative(english, base.date())
        parsed = dateparser.parse(candidate, languages=[language], settings=settings)
        if parsed is not None:
            return parsed.date()
    return None


def _candidates(text: str, words: Words) -> list[str]:
    """The phrase, then with each leading preposition and trailing particle taken off in turn."""
    value = _EDGE_PUNCT_RE.sub("", " ".join(text.replace("\u2019", "'").lower().split()))
    for particle in words.trailing:
        if value.endswith(particle) and value != particle:
            value = value[: -len(particle)].strip()
            break
    out = [value]
    for _ in range(3):
        for word in words.leading:
            if value.startswith(word + " ") or (word.endswith("'") and value.startswith(word)):
                value = value[len(word) :].strip()
                out.append(value)
                break
        else:
            break
    return [c for c in out if c]


def _next_weekday(phrase: str, language: str, words: Words) -> str | None:
    """'nächsten montag', 'lundi prochain' -> 'next monday'; anything else -> None."""
    tokens = phrase.split()
    if not words.next_words or not any(t in words.next_words for t in tokens):
        return None
    rest = [t for t in tokens if t not in words.next_words and t not in words.leading]
    if len(rest) != 1:
        return None
    info = default_loader.get_locale(language).info
    for english in ENGLISH_WEEKDAYS:
        if rest[0] in {name.lower() for name in info.get(english, [])}:
            return f"next {english}"
    return None
