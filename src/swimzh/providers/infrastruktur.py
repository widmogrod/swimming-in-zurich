"""Parse the WFS `infrastruktur` free-text prose into partial basin physicals.

The geoportal describes each facility's water in one prose blob, e.g.::

    Schwimmerbecken 50 x 15 m (6 Bahnen) 28°C, Nichtschwimmerbecken 10,5 x 7 m 30°C,
    Variobecken … 30°C, gemischte Sauna 8-22 Uhr Eintritt Fr. 10.-

This parser is deliberately **partial and best-effort**: it extracts only what it can
recognise (kind, dimensions, lanes, nominal temperature), leaves everything else `None`,
and never fails — unrecognisable segments are simply skipped. Non-basin segments (sauna,
steam bath, …) are not basins and are ignored here (they become `Feature`s in a later
slice). German decimal commas ("10,5", "16,66") become `Decimal` values.

Parsed physicals are merged into an existing scheduled `Basin` with `apply_physicals`,
which marks the basin `physical_source=PARSED_PROSE` so the UI can caveat
"auto-extracted".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal

from swimzh.domain.models import Basin, BasinKind, BasinSource, Dimensions

# Split prose into segments. A comma directly followed by a digit is a German decimal
# separator ("10,5"), not a segment boundary.
_SEGMENT_RE = re.compile(r"[;\n]|,(?!\d)")

_NUM = r"\d+(?:[.,]\d+)?"
_DIMENSIONS_RE = re.compile(rf"({_NUM})\s*[x×]\s*({_NUM})\s*m\b", re.IGNORECASE)
_LENGTH_RE = re.compile(rf"({_NUM})\s*m\b(?!\s*(?:²|2\b))", re.IGNORECASE)
_LANES_RE = re.compile(r"(\d+)\s*Bahnen", re.IGNORECASE)
_TEMP_RE = re.compile(rf"({_NUM})\s*°\s*C", re.IGNORECASE)
_NAME_RE = re.compile(r"^[^\d(…]*")

# Ordered: more specific keywords first ("nichtschwimmerbecken" contains "schwimmerbecken").
_KIND_KEYWORDS: tuple[tuple[str, BasinKind], ...] = (
    ("nichtschwimmer", BasinKind.NON_SWIMMER),
    ("schwimmerbecken", BasinKind.LAP),
    ("sportbecken", BasinKind.LAP),
    ("sprungbecken", BasinKind.DIVING),
    ("tauchbecken", BasinKind.DIVING),
    ("variobecken", BasinKind.VARIO),
    ("lehrschwimmbecken", BasinKind.TEACHING),
    ("lernschwimmbecken", BasinKind.TEACHING),
    ("kinderbecken", BasinKind.CHILDREN),
    ("planschbecken", BasinKind.CHILDREN),
    ("aussenbecken", BasinKind.OUTDOOR),
    ("außenbecken", BasinKind.OUTDOOR),
)


@dataclass(frozen=True, slots=True)
class ParsedBasinPhysical:
    """Physical facts about one basin, as far as the prose reveals them. Missing facts
    stay `None` — never assert completeness."""

    name: str
    kind: BasinKind
    dimensions: Dimensions | None
    lanes: int | None
    nominal_temp_c: Decimal | None
    raw: str  # the exact prose segment, for audit/reparse


def _decimal(token: str) -> Decimal:
    return Decimal(token.replace(",", "."))


def _kind(lowered: str) -> BasinKind:
    for keyword, kind in _KIND_KEYWORDS:
        if keyword in lowered:
            return kind
    return BasinKind.OTHER


def _dimensions(segment: str) -> Dimensions | None:
    both = _DIMENSIONS_RE.search(segment)
    if both is not None:
        return Dimensions(length_m=_decimal(both.group(1)), width_m=_decimal(both.group(2)))
    length = _LENGTH_RE.search(segment)
    if length is not None:
        return Dimensions(length_m=_decimal(length.group(1)))
    return None


def _name(segment: str) -> str:
    match = _NAME_RE.match(segment)
    name = match.group(0).strip(" .-–—:") if match is not None else ""
    return name or segment


def _parse_segment(segment: str) -> ParsedBasinPhysical | None:
    lowered = segment.lower()
    if "becken" not in lowered:
        return None  # sauna, steam bath, prices, … — not swimmable water
    lanes = _LANES_RE.search(segment)
    temp = _TEMP_RE.search(segment)
    return ParsedBasinPhysical(
        name=_name(segment),
        kind=_kind(lowered),
        dimensions=_dimensions(segment),
        lanes=int(lanes.group(1)) if lanes is not None else None,
        nominal_temp_c=_decimal(temp.group(1)) if temp is not None else None,
        raw=segment,
    )


def parse_infrastruktur(text: str) -> tuple[ParsedBasinPhysical, ...]:
    """Extract the basin segments of an `infrastruktur` prose blob. Total: never raises;
    yields nothing when the prose describes no recognisable basins."""
    parsed: list[ParsedBasinPhysical] = []
    for raw_segment in _SEGMENT_RE.split(text):
        segment = raw_segment.strip()
        if not segment:
            continue
        physical = _parse_segment(segment)
        if physical is not None:
            parsed.append(physical)
    return tuple(parsed)


def apply_physicals(basin: Basin, physical: ParsedBasinPhysical) -> Basin:
    """Enrich a scheduled basin with prose-parsed physicals, marking it PARSED_PROSE so
    downstream surfaces can caveat "auto-extracted". Schedule rules stay untouched."""
    return replace(
        basin,
        kind=physical.kind,
        dimensions=physical.dimensions,
        lanes=physical.lanes,
        nominal_temp_c=physical.nominal_temp_c,
        physical_source=BasinSource.PARSED_PROSE,
    )
