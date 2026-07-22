"""Parse the WFS `infrastruktur` free-text prose into partial basin physicals.

The geoportal describes each facility's water in one prose blob, e.g.::

    Schwimmerbecken 50 x 15 m (6 Bahnen) 28°C, Nichtschwimmerbecken 10,5 x 7 m 30°C,
    Variobecken … 30°C, gemischte Sauna 8-22 Uhr Eintritt Fr. 10.-

This parser is deliberately **partial and best-effort**: it extracts only what it can
recognise (kind, dimensions, lanes, nominal temperature), leaves everything else `None`,
and never fails — unrecognisable segments are simply skipped. German decimal commas ("10,5",
"16,66") become `Decimal` values.

Basin segments (containing "becken") become `ParsedBasinPhysical`s; the non-basin segments
(sauna, steam bath, terrace, restaurant, …) become `Feature`s via `parse_features`.

Parsed physicals reach the domain two ways: `apply_physicals` merges them into an *existing*
scheduled `Basin` (schedule untouched), while `basin_from_physical` mints a *schedule-less*
`Basin` for an otherwise location-only pool. Both tag the basin `physical_source=PARSED_PROSE`
so the UI can caveat "auto-extracted".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal

from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    BasinSource,
    Dimensions,
    Feature,
    FeatureKind,
)

# Split prose into segments. A comma directly followed by a digit is a German decimal
# separator ("10,5"), not a segment boundary.
_SEGMENT_RE = re.compile(r"[;\n]|,(?!\d)")

_NUM = r"\d+(?:[.,]\d+)?"
_DIMENSIONS_RE = re.compile(rf"({_NUM})\s*[x×]\s*({_NUM})\s*m\b", re.IGNORECASE)
_LENGTH_RE = re.compile(rf"({_NUM})\s*m\b(?!\s*(?:²|2\b))", re.IGNORECASE)
_LANES_RE = re.compile(r"(\d+)\s*Bahnen", re.IGNORECASE)
_TEMP_RE = re.compile(rf"({_NUM})\s*°\s*C", re.IGNORECASE)
_NAME_RE = re.compile(r"^[^\d(…]*")
# Diving platform/board heights as a slash-list ("1/3/5m", "1/3 m"). Requires at least one
# slash so it never swallows a plain basin dimension ("25m").
_PLATFORM_RE = re.compile(rf"({_NUM}(?:\s*/\s*{_NUM})+)\s*m\b", re.IGNORECASE)

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
    diving_platforms_m: tuple[Decimal, ...] = ()  # e.g. (1, 3, 5) from "Sprungbecken 1/3/5m"


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


def _diving_platforms(segment: str) -> tuple[Decimal, ...]:
    match = _PLATFORM_RE.search(segment)
    if match is None:
        return ()
    return tuple(_decimal(tok.strip()) for tok in match.group(1).split("/"))


def _parse_segment(segment: str) -> ParsedBasinPhysical | None:
    lowered = segment.lower()
    if "becken" not in lowered:
        return None  # sauna, steam bath, prices, … — not swimmable water
    lanes = _LANES_RE.search(segment)
    temp = _TEMP_RE.search(segment)
    platforms = _diving_platforms(segment)
    # When the segment carries a slash-list of platform heights ("1/3/5m") those numbers are
    # board heights, NOT a basin dimension — don't let `_dimensions` misread the last one as a
    # length. A basin never states both a slash platform-list and an "L x W m" size in one segment.
    dimensions = None if platforms else _dimensions(segment)
    return ParsedBasinPhysical(
        name=_name(segment),
        kind=_kind(lowered),
        dimensions=dimensions,
        lanes=int(lanes.group(1)) if lanes is not None else None,
        nominal_temp_c=_decimal(temp.group(1)) if temp is not None else None,
        raw=segment,
        diving_platforms_m=platforms,
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
    downstream surfaces can caveat "auto-extracted". Schedule rules stay untouched.

    INTENTIONALLY UNWIRED in Slice F (disclosed deferral, not an oversight). It is the
    *enrich-an-existing-scheduled-basin* primitive — distinct from `basin_from_physical`, which
    *mints* a schedule-less prose basin for a location-only pool (the path the build actually
    uses). No sound build call site exists today: over the committed inputs, every curated basin
    that carries prose (Hallenbad City, Bungertwies) ALREADY holds hand-verified `CURATED`
    physicals, so applying prose would overwrite hand-verified data and downgrade it to
    PARSED_PROSE (forbidden); and the curated basins that lack physicals (`aemtler-becken`,
    `oerlikon-sprungbecken`) belong to pools whose WFS `description` is empty (no prose to
    enrich). It is kept — with its contract test — for a future slice that matches a prose
    segment to a specific scheduled basin (e.g. a fuzzy basin-name match at the compose seam),
    guarded so a `CURATED` basin is never clobbered.
    """
    return replace(
        basin,
        kind=physical.kind,
        dimensions=physical.dimensions,
        lanes=physical.lanes,
        nominal_temp_c=physical.nominal_temp_c,
        diving_platforms_m=physical.diving_platforms_m,
        physical_source=BasinSource.PARSED_PROSE,
    )


def basin_from_physical(physical: ParsedBasinPhysical, basin_id: BasinId) -> Basin:
    """Build a **schedule-less** ``Basin`` for a pool that is otherwise location-only: it carries
    the prose-parsed physicals tagged ``PARSED_PROSE`` but **no rules**.

    The empty ``rules`` is the Decision #5 gate in the data itself — a basin with no schedule
    yields no sessions, so ``find_swim_options`` can never turn this auto-extracted basin into a
    ``/swim`` option; it is surfaced only in the ``/pools/{id}`` detail (with the caveat).
    """
    return Basin(
        basin_id=basin_id,
        name=physical.name,
        rules=(),
        kind=physical.kind,
        dimensions=physical.dimensions,
        lanes=physical.lanes,
        nominal_temp_c=physical.nominal_temp_c,
        diving_platforms_m=physical.diving_platforms_m,
        physical_source=BasinSource.PARSED_PROSE,
    )


# Non-basin amenity keywords -> a `FeatureKind` + a clean display label. Ordered most-specific
# first ("sonnenterrasse" before "terrasse"). A segment that matches none yields no feature — we
# never emit an uncategorised amenity from noise.
_FEATURE_KEYWORDS: tuple[tuple[str, FeatureKind, str], ...] = (
    ("dampfbad", FeatureKind.STEAM_BATH, "Dampfbad"),
    ("sauna", FeatureKind.SAUNA, "Sauna"),
    ("rutschbahn", FeatureKind.SLIDE, "Rutschbahn"),
    ("rutsche", FeatureKind.SLIDE, "Rutschbahn"),
    ("sprudel", FeatureKind.HOT_TUB, "Sprudelbad"),
    ("massagedüsen", FeatureKind.HOT_TUB, "Massagebad"),
    ("whirlpool", FeatureKind.HOT_TUB, "Whirlpool"),
    ("sonnenterrasse", FeatureKind.TERRACE, "Sonnenterrasse"),
    ("terrasse", FeatureKind.TERRACE, "Terrasse"),
    ("restaurant", FeatureKind.GASTRONOMY, "Restaurant"),
    ("kiosk", FeatureKind.GASTRONOMY, "Kiosk"),
    ("liegewiese", FeatureKind.REST, "Liegewiese"),
    ("sandstrand", FeatureKind.REST, "Sandstrand"),
)


def _feature_for(segment: str) -> Feature | None:
    lowered = segment.lower()
    if "becken" in lowered:
        return None  # a swimmable basin is handled by `_parse_segment`, not as a feature
    for keyword, kind, label in _FEATURE_KEYWORDS:
        if keyword in lowered:
            temp = _TEMP_RE.search(segment)
            return Feature(
                kind=kind,
                name=label,
                temp_c=_decimal(temp.group(1)) if temp is not None else None,
                note=segment,
            )
    return None


def parse_features(text: str) -> tuple[Feature, ...]:
    """Extract the non-basin amenity segments (sauna, steam bath, terrace, restaurant, …) of an
    ``infrastruktur`` prose blob as ``Feature``s. Total: never raises; yields nothing when the
    prose describes no recognisable amenity."""
    features: list[Feature] = []
    for raw_segment in _SEGMENT_RE.split(text):
        segment = raw_segment.strip()
        if not segment:
            continue
        feature = _feature_for(segment)
        if feature is not None:
            features.append(feature)
    return tuple(features)
