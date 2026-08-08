"""S1 fidelity spike (GO/NO-GO): measure which curated facts a *website provider* can
reproduce, per fact-class, for the 7 currently-curated pools — **before** any removal.

This module is **pure** and does **no I/O**: callers hand it the already-read source strings
(a pool's WFS ``infrastruktur`` prose and its saved page HTML) plus the curated ``Facility``;
it runs the existing providers off their production path and returns two artifacts:

  1. a per-pool **schedule diff** — provider-derived facility-level ``ScheduleRule``s vs. the
     curated rules **projected to facility level** (basin identity + calendar scope dropped),
     every entry classified ``matched`` / ``source-poorer`` / ``source-richer`` (no silent
     unclassified row); and
  2. a **gap report** classifying each curated fact-class as
     ``sourced-by-<provider> | derivable-with-rule | not-in-source``, its verdict *derived from
     the measurement* (not asserted), with evidence.

It changes **no production data path**: ``build_store``/``build_spine`` are untouched. The
existing ``parse_infrastruktur`` (today only reached on the uncurated ``_location_only_facility``
path) is invoked here directly, exactly as S1 requires.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from enum import Enum

from swimzh.core.errors import ProviderError
from swimzh.core.result import Err, Ok
from swimzh.domain.models import Facility
from swimzh.domain.schedule import ScheduleRule, Weekday
from swimzh.providers.infrastruktur import ParsedBasinPhysical, parse_infrastruktur
from swimzh.providers.schedule_scraper import parse_notices, parse_schedule

# A WFS ``description`` cell is this literal string when the geoportal has no prose for a pool.
_NULL_PROSE = "NULL"


# --------------------------------------------------------------------------------------
# Measurement: run the providers off their production path over one pool's raw sources.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PoolMeasurement:
    """Everything the two artifacts need for one pool, produced by running the real providers
    over that pool's raw source strings. ``source_rules is None`` means *no page fixture exists*
    (an honest coverage gap), distinct from ``source_error`` (a fixture that failed to parse)."""

    pool_id: str
    curated: Facility
    physicals: tuple[ParsedBasinPhysical, ...]
    has_prose: bool
    source_rules: tuple[ScheduleRule, ...] | None
    source_error: ProviderError | None
    source_closures: tuple[tuple[date | None, date], ...]  # (active_from, active_to) per notice


def measure_pool(
    pool_id: str,
    curated: Facility,
    wfs_prose: str | None,
    page_html: str | None,
) -> PoolMeasurement:
    """Run ``parse_infrastruktur`` + ``parse_schedule`` + ``parse_notices`` over one pool's raw
    sources. Total: never raises — a missing source is ``None``, a parse failure is captured."""
    has_prose = wfs_prose is not None and wfs_prose.strip() not in ("", _NULL_PROSE)
    physicals = parse_infrastruktur(wfs_prose) if has_prose and wfs_prose is not None else ()

    source_rules: tuple[ScheduleRule, ...] | None = None
    source_error: ProviderError | None = None
    closures: tuple[tuple[date | None, date], ...] = ()
    if page_html is not None:
        match parse_schedule(page_html):
            case Ok(scraped):
                source_rules = scraped.rules
            case Err(error):
                source_error = error
        closures = tuple(
            (n.active_from, n.active_to)
            for n in parse_notices(page_html)
            if n.active_to is not None
        )

    return PoolMeasurement(
        pool_id=pool_id,
        curated=curated,
        physicals=physicals,
        has_prose=has_prose,
        source_rules=source_rules,
        source_error=source_error,
        source_closures=closures,
    )


# --------------------------------------------------------------------------------------
# Artifact 1 — the per-pool schedule diff (facility-level).
# --------------------------------------------------------------------------------------


class DiffClass(Enum):
    """Every diff entry is exactly one of these — a set-difference partition, so no row is
    ever silently unclassified."""

    MATCHED = "matched"  # both source and curated (projected) assert this rule
    SOURCE_POORER = "source-poorer"  # curated asserts it; the source does not reproduce it
    SOURCE_RICHER = "source-richer"  # the source asserts it; curated never authored it


@dataclass(frozen=True, slots=True)
class RuleKey:
    """A ``ScheduleRule`` projected to what a website timetable can carry: weekdays, the time
    window, and the access *category*. Basin identity and calendar scope are dropped — those are
    exactly the dimensions the flat source row list cannot express (they surface in the gap
    report, not here)."""

    weekdays: frozenset[Weekday]
    start: str  # "HH:MM"
    end: str
    access: str  # SessionAccess subclass name


@dataclass(frozen=True, slots=True)
class DiffEntry:
    classification: DiffClass
    key: RuleKey


@dataclass(frozen=True, slots=True)
class PoolScheduleDiff:
    pool_id: str
    source_available: bool
    curated_rule_count: int
    entries: tuple[DiffEntry, ...]

    def count(self, classification: DiffClass) -> int:
        return sum(1 for e in self.entries if e.classification is classification)

    def source_rule_count(self) -> int:
        """Distinct facility-level rules the source emitted = matched + source-richer."""
        return self.count(DiffClass.MATCHED) + self.count(DiffClass.SOURCE_RICHER)


def _hhmm(value: time) -> str:
    return value.strftime("%H:%M")


def _rule_key(rule: ScheduleRule) -> RuleKey:
    return RuleKey(
        weekdays=rule.weekdays,
        start=_hhmm(rule.time.start),
        end=_hhmm(rule.time.end),
        access=type(rule.access).__name__,
    )


def _project_curated(facility: Facility) -> frozenset[RuleKey]:
    """Flatten every basin's rules to facility level (basin + scope dropped)."""
    return frozenset(_rule_key(rule) for basin in facility.basins for rule in basin.rules)


def _sort_key(key: RuleKey) -> tuple[tuple[int, ...], str, str, str]:
    return (tuple(sorted(int(d) for d in key.weekdays)), key.start, key.end, key.access)


def diff_schedule(measurement: PoolMeasurement) -> PoolScheduleDiff:
    """Classify every facility-level rule as matched / source-poorer / source-richer.

    A pool with no page fixture (``source_rules is None``) yields ``source_available=False`` and
    zero entries — an explicit coverage gap, never a silent unclassified row."""
    curated = _project_curated(measurement.curated)
    if measurement.source_rules is None:
        return PoolScheduleDiff(
            pool_id=measurement.pool_id,
            source_available=False,
            curated_rule_count=len(curated),
            entries=(),
        )
    source = frozenset(_rule_key(rule) for rule in measurement.source_rules)
    entries = [
        *(DiffEntry(DiffClass.MATCHED, k) for k in curated & source),
        *(DiffEntry(DiffClass.SOURCE_POORER, k) for k in curated - source),
        *(DiffEntry(DiffClass.SOURCE_RICHER, k) for k in source - curated),
    ]
    entries.sort(key=lambda e: (e.classification.value, _sort_key(e.key)))
    return PoolScheduleDiff(
        pool_id=measurement.pool_id,
        source_available=True,
        curated_rule_count=len(curated),
        entries=tuple(entries),
    )


# --------------------------------------------------------------------------------------
# Artifact 2 — the fact-class gap report.
# --------------------------------------------------------------------------------------


class Sourcing(Enum):
    SOURCED_BY_INFRASTRUKTUR = "sourced-by-infrastruktur"
    SOURCED_BY_SCHEDULE = "sourced-by-schedule"
    DERIVABLE_WITH_RULE = "derivable-with-rule"
    NOT_IN_SOURCE = "not-in-source"


@dataclass(frozen=True, slots=True)
class GapEntry:
    fact_class: str
    sourcing: Sourcing
    evidence: str


@dataclass(frozen=True, slots=True)
class GapReport:
    entries: tuple[GapEntry, ...]


def _prose_pools(ms: tuple[PoolMeasurement, ...]) -> tuple[PoolMeasurement, ...]:
    return tuple(m for m in ms if m.has_prose)


def _null_prose_ids(ms: tuple[PoolMeasurement, ...]) -> tuple[str, ...]:
    return tuple(sorted(m.pool_id for m in ms if not m.has_prose))


def _curated_kinds(facility: Facility) -> frozenset[str]:
    return frozenset(b.kind.value for b in facility.basins)


def _source_access_kinds(ms: tuple[PoolMeasurement, ...]) -> frozenset[str]:
    return frozenset(
        type(rule.access).__name__
        for m in ms
        if m.source_rules is not None
        for rule in m.source_rules
    )


def _curated_pools_declaring(ms: tuple[PoolMeasurement, ...], access: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            m.pool_id
            for m in ms
            if any(type(r.access).__name__ == access for b in m.curated.basins for r in b.rules)
        )
    )


def _kind_entry(ms: tuple[PoolMeasurement, ...]) -> GapEntry:
    prose = _prose_pools(ms)
    reproduced: list[str] = []
    any_match = False
    for m in prose:
        parsed = frozenset(p.kind.value for p in m.physicals)
        curated = _curated_kinds(m.curated)
        any_match = any_match or bool(parsed & curated)
        reproduced.append(f"{m.pool_id}: parsed={sorted(parsed)} curated={sorted(curated)}")
    null_ids = _null_prose_ids(ms)
    evidence = (
        f"prose present {len(prose)}/{len(ms)} pools; "
        + "; ".join(reproduced)
        + f"; NULL-prose (kind falls back to curated, NOT sourced): {list(null_ids)}"
    )
    return GapEntry(
        "basin.kind",
        Sourcing.SOURCED_BY_INFRASTRUKTUR if any_match else Sourcing.NOT_IN_SOURCE,
        evidence,
    )


def _dimensions_entry(ms: tuple[PoolMeasurement, ...]) -> GapEntry:
    prose = _prose_pools(ms)
    matched: list[str] = []
    for m in prose:
        parsed_lengths = {str(p.dimensions.length_m) for p in m.physicals if p.dimensions}
        curated_lengths = {
            str(b.dimensions.length_m) for b in m.curated.basins if b.dimensions is not None
        }
        hit = parsed_lengths & curated_lengths
        if hit:
            matched.append(f"{m.pool_id}: lengths {sorted(hit)} match")
    return GapEntry(
        "basin.dimensions",
        Sourcing.SOURCED_BY_INFRASTRUKTUR if matched else Sourcing.NOT_IN_SOURCE,
        f"prose present {len(prose)}/{len(ms)} pools; "
        + ("; ".join(matched) if matched else "no curated length reproduced from prose")
        + f"; NULL-prose: {list(_null_prose_ids(ms))}",
    )


def _lanes_entry(ms: tuple[PoolMeasurement, ...]) -> GapEntry:
    matched: list[str] = []
    for m in _prose_pools(ms):
        parsed_lanes = {p.lanes for p in m.physicals if p.lanes is not None}
        curated_lanes = {b.lanes for b in m.curated.basins if b.lanes is not None}
        hit = parsed_lanes & curated_lanes
        if hit:
            matched.append(f"{m.pool_id}: lanes {sorted(hit)} match")
    return GapEntry(
        "basin.lanes",
        Sourcing.SOURCED_BY_INFRASTRUKTUR if matched else Sourcing.NOT_IN_SOURCE,
        ("; ".join(matched) if matched else "no curated lane count reproduced from prose")
        + f"; NULL-prose: {list(_null_prose_ids(ms))}",
    )


def _access_category_entry(ms: tuple[PoolMeasurement, ...]) -> GapEntry:
    source_kinds = _source_access_kinds(ms)
    curated_public = _curated_pools_declaring(ms, "PublicSwim")
    reproduced = source_kinds & {"PublicSwim", "WomenOnly", "SeniorsOnly", "SchoolReserved"}
    measured = sum(1 for m in ms if m.source_rules is not None)
    return GapEntry(
        "access.category (public/women/seniors/school)",
        Sourcing.SOURCED_BY_SCHEDULE if reproduced else Sourcing.NOT_IN_SOURCE,
        f"source timetable emits access kinds {sorted(source_kinds)}; "
        f"reproduced categories {sorted(reproduced)}; "
        f"(the scraper also maps Senioren/Schul, but neither appears in any of the "
        f"{measured} measured pages); "
        f"curated pools declaring PublicSwim: {list(curated_public)}",
    )


def _absent_access_entry(ms: tuple[PoolMeasurement, ...], access: str, label: str) -> GapEntry:
    """Is a curated-only access kind reproduced by the source, or not?

    The verdict is DERIVED, not asserted: `AdultsOnly` was a not-in-source class only for as
    long as the scraper folded ``"für\\xa0Erwachsene"`` into `PublicSwim`. Hard-coding
    `NOT_IN_SOURCE` here would have kept printing that claim after it became false.
    """
    declaring = _curated_pools_declaring(ms, access)
    source_kinds = _source_access_kinds(ms)
    emitted = access in source_kinds
    verdict = (
        "the source timetable now emits it" if emitted else "the source timetable never emits it"
    )
    folds = "" if emitted else " — the scraper folds any unmarked category to PublicSwim"
    return GapEntry(
        f"access.{label}",
        Sourcing.SOURCED_BY_SCHEDULE if emitted else Sourcing.NOT_IN_SOURCE,
        f"curated declares {access} in {list(declaring)}; {verdict} "
        f"(observed source access kinds: {sorted(source_kinds)}){folds}",
    )


def _closures_entry(ms: tuple[PoolMeasurement, ...]) -> GapEntry:
    matched: list[str] = []
    for m in ms:
        curated_ranges = {(c.start, c.end) for c in m.curated.closures}
        source_ranges = set(m.source_closures)
        hit = curated_ranges & source_ranges
        if hit:
            ranges = sorted(f"{start.isoformat()}..{end.isoformat()}" for start, end in hit)
            matched.append(f"{m.pool_id}: {ranges}")
    return GapEntry(
        "facility.closures",
        Sourcing.SOURCED_BY_SCHEDULE if matched else Sourcing.NOT_IN_SOURCE,
        "parse_notices reproduces a curated closure range with exact dates: "
        + ("; ".join(matched) if matched else "none reproduced from available fixtures"),
    )


def _structural_entry(fact_class: str, evidence: str) -> GapEntry:
    """A fact-class the source *format* cannot express — verified by the shape of the parser's
    input, not by a per-pool measurement (so it holds regardless of fixture coverage)."""
    return GapEntry(fact_class, Sourcing.NOT_IN_SOURCE, evidence)


def build_gap_report(measurements: tuple[PoolMeasurement, ...]) -> GapReport:
    """Classify every curated fact-class from the measurement. Verdicts for reproducible classes
    (kind/dimensions/lanes/access/closures) are *derived*; structural residue classes
    (basin-schedule-split, prices, holiday policy, scope) are fixed by the source format."""
    entries = (
        _kind_entry(measurements),
        _dimensions_entry(measurements),
        _lanes_entry(measurements),
        _access_category_entry(measurements),
        _closures_entry(measurements),
        _absent_access_entry(measurements, "LaneSwim", "lane_swim"),
        _absent_access_entry(measurements, "FamilyTime", "family"),
        _absent_access_entry(measurements, "AdultsOnly", "adults_only"),
        _structural_entry(
            "basin.schedule-split",
            "the stadt-zuerich timetable is a flat facility-level row list [day, hours, "
            "category] with no basin column — a session cannot be attributed to a basin",
        ),
        _structural_entry(
            "schedule.scope (school_term/school_holiday)",
            "the timetable states one set of hours; it carries no term-vs-holiday variant",
        ),
        _structural_entry(
            "facility.prices (admission)",
            "neither the timetable rows nor the infrastruktur basin prose carry admission "
            "prices; admission is sourced elsewhere — the central tariff page (price_scraper) "
            "or the pool page's own gratis sentence (states_free_admission), as the Admission "
            "union",
        ),
        _structural_entry(
            "facility.public_holiday_policy",
            "no signal in the timetable or prose distinguishes closed/sunday-schedule/normal",
        ),
    )
    return GapReport(entries=entries)


# --------------------------------------------------------------------------------------
# Deterministic markdown rendering (the committed artifacts the S1 human gate reads).
# --------------------------------------------------------------------------------------

_DAY_SHORT: dict[Weekday, str] = {
    Weekday.MONDAY: "Mon",
    Weekday.TUESDAY: "Tue",
    Weekday.WEDNESDAY: "Wed",
    Weekday.THURSDAY: "Thu",
    Weekday.FRIDAY: "Fri",
    Weekday.SATURDAY: "Sat",
    Weekday.SUNDAY: "Sun",
}


def _fmt_days(days: frozenset[Weekday]) -> str:
    return "/".join(_DAY_SHORT[d] for d in sorted(days, key=int))


def _pool_section(diff: PoolScheduleDiff) -> list[str]:
    if not diff.source_available:
        return [
            f"## {diff.pool_id}",
            "",
            f"NO PAGE FIXTURE — schedule fidelity **not measured** "
            f"(curated projected rules: {diff.curated_rule_count}). Coverage gap recorded.",
            "",
        ]
    lines = [
        f"## {diff.pool_id}",
        "",
        f"source rules: {diff.source_rule_count()} "
        f"| curated (projected) rules: {diff.curated_rule_count} | "
        f"matched: {diff.count(DiffClass.MATCHED)} | "
        f"source-poorer: {diff.count(DiffClass.SOURCE_POORER)} | "
        f"source-richer: {diff.count(DiffClass.SOURCE_RICHER)}",
        "",
        "| class | weekdays | time | access |",
        "|-------|----------|------|--------|",
    ]
    lines += [
        f"| {e.classification.value} | {_fmt_days(e.key.weekdays)} | "
        f"{e.key.start}–{e.key.end} | {e.key.access} |"
        for e in diff.entries
    ]
    lines.append("")
    return lines


def render_schedule_diff(diffs: tuple[PoolScheduleDiff, ...]) -> str:
    ordered = sorted(diffs, key=lambda d: d.pool_id)
    measured = [d for d in ordered if d.source_available]
    missing = [d.pool_id for d in ordered if not d.source_available]
    lines = [
        "# S1 fidelity — provider-derived vs. curated schedule (facility-level)",
        "",
        "Generated by `swimzh.etl.fidelity_report`; deterministic from committed fixtures. "
        "Curated rules are projected to facility level (basin identity + calendar scope dropped) "
        "before the set diff.",
        "",
        "## Coverage",
        "",
        f"- pools: {len(ordered)}",
        f"- with page fixture (measured): {len(measured)} "
        f"({', '.join(d.pool_id for d in measured) or 'none'})",
        f"- missing page fixture (gap): {len(missing)} ({', '.join(missing) or 'none'})",
        "",
    ]
    for diff in ordered:
        lines += _pool_section(diff)
    return "\n".join(lines).rstrip() + "\n"


def render_gap_report(report: GapReport) -> str:
    lines = [
        "# S1 gap report — curated fact-class -> sourcing",
        "",
        "Generated by `swimzh.etl.fidelity_report`; deterministic from committed fixtures. "
        "Each verdict is one of `sourced-by-<provider>` / `derivable-with-rule` / `not-in-source`.",
        "",
        "| fact class | sourcing | evidence |",
        "|------------|----------|----------|",
    ]
    lines += [f"| {e.fact_class} | {e.sourcing.value} | {e.evidence} |" for e in report.entries]
    return "\n".join(lines).rstrip() + "\n"
