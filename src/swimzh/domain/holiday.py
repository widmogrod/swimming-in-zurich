"""Public-holiday names as CODES.

`ZurichCalendar` carries German holiday names ("Bundesfeier", "Berchtoldstag"), and the
resolver passes the name straight through as a closure parameter — so a holiday closure
reads as German in every locale.

**Deviation from the plan, recorded deliberately.** The plan said to author codes in
`data/calendar/zurich.yaml`. Its reason was that *dates* change annually while holidays
recur, so the message must not be keyed on the date — and deriving from the NAME satisfies
that just as well, because names recur too. Doing it here instead reuses the proven
`domain.closure` idiom (exact match + audited fail-safe) and avoids threading a new field
through the DTO, the codec and the gold store for ten values. Revisit if a holiday is ever
renamed upstream: the audit will say so.

The three tiers from the plan's "Resolved: holidays" all appear in the real data:
  * shared feasts that translate cleanly       — Weihnachten, Karfreitag, Auffahrt…
  * a nameable national day                    — Bundesfeier ("Swiss National Day")
  * genuinely untranslatable Swiss-only        — Berchtoldstag (kept German, glossed)
"""

from __future__ import annotations

from enum import StrEnum


class HolidayCode(StrEnum):
    """Zürich's public holidays. `UNKNOWN` is the fail-safe, not a holiday."""

    NEW_YEAR = "new_year"
    #: Swiss/Liechtenstein only — no equivalent elsewhere. Kept German + glossed.
    BERCHTOLDSTAG = "berchtoldstag"
    GOOD_FRIDAY = "good_friday"
    EASTER_MONDAY = "easter_monday"
    LABOUR_DAY = "labour_day"
    #: "Auffahrt" is merely the Swiss-German word for Ascension, a universal feast.
    ASCENSION = "ascension"
    WHIT_MONDAY = "whit_monday"
    #: Swiss National Day — nameable descriptively, like Bastille Day.
    NATIONAL_DAY = "national_day"
    CHRISTMAS = "christmas"
    ST_STEPHENS = "st_stephens"

    #: Fail-safe: a name we do not recognise. The German rides through verbatim.
    UNKNOWN = "unknown"


_NAMES: dict[str, HolidayCode] = {
    "neujahr": HolidayCode.NEW_YEAR,
    "berchtoldstag": HolidayCode.BERCHTOLDSTAG,
    "karfreitag": HolidayCode.GOOD_FRIDAY,
    "ostermontag": HolidayCode.EASTER_MONDAY,
    "tag der arbeit": HolidayCode.LABOUR_DAY,
    "auffahrt": HolidayCode.ASCENSION,
    "pfingstmontag": HolidayCode.WHIT_MONDAY,
    "bundesfeier": HolidayCode.NATIONAL_DAY,
    "weihnachten": HolidayCode.CHRISTMAS,
    "stephanstag": HolidayCode.ST_STEPHENS,
}


def classify_holiday(name: str | None) -> HolidayCode:
    """Classify a curated holiday name. Unrecognised → `UNKNOWN` (the caller keeps the
    original name, so the label stays true)."""
    stripped = (name or "").strip()
    if not stripped:
        return HolidayCode.UNKNOWN
    return _NAMES.get(stripped.casefold(), HolidayCode.UNKNOWN)
