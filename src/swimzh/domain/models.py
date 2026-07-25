"""Facility-level domain models: identity, basins, provenance, and the
`Facility` aggregate that the query surface reads.

A `Facility` (e.g. "Hallenbad City") contains one or more `Basin`s, each with its *own*
schedule — modelled explicitly because one address can host basins with independent hours
and access rules. Closures and public-holiday policy sit at the facility level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import NewType

from swimzh.core.errors import ProviderError
from swimzh.domain.geo import GeoPoint
from swimzh.domain.lane_plan import LanePlan
from swimzh.domain.lockers import LockerOption
from swimzh.domain.pricing import PriceTable
from swimzh.domain.schedule import (
    ClosureRange,
    HolidayPolicy,
    ScheduleException,
    ScheduleRule,
)

PoolId = NewType("PoolId", str)
BasinId = NewType("BasinId", str)


def reconstruct_pool_id(value: str) -> PoolId:
    """Re-wrap a canonical id string that was ALREADY minted upstream — a persisted gold row
    or a validated DTO — back into a ``PoolId``.

    This is *reconstruction*, not minting: the id already passed through the two minting seams
    (``build.reconcile`` / ``build.seed``, the only sites that create an id from an external
    ref) before it was stored, so trusting it here introduces no new identity. Kept as a single
    named boundary so the minter grep-guard can allow exactly ONE reconstruction door (this
    module) instead of every trusted call-site (persisted-row codec / validated DTO providers).
    """
    return PoolId(value)


class PoolKind(Enum):
    INDOOR = "indoor"  # Hallenbad
    OUTDOOR = "outdoor"  # Freibad
    RIVER = "river"  # Flussbad
    LAKE = "lake"  # Seebad
    SCHOOL = "school"  # Schulschwimmanlage
    PADDLING = "paddling"  # Planschbecken
    THERMAL = "thermal"  # Wärmebad


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a piece of data came from and how fresh it is. Attached to every answer so a
    stale-but-typed wrong answer is at least visibly stale."""

    source: str
    curated: bool
    valid_as_of: date | None = None
    fetched_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PoolIdentity:
    """Canonical identity + crosswalk into other data sources' namespaces."""

    facility_id: PoolId
    name: str
    kind: PoolKind
    geo_sport_id: str | None = None
    crowdmonitor_keys: tuple[str, ...] = field(default_factory=tuple)
    # Baditicker (OGD water-temperature feed) stable external id (e.g. `fb012` for Freibad
    # Heuried). A single poiid because the feed is poiid-keyed; `None` when this pool has no
    # Baditicker mapping. Persisted in gold (unlike the live reading, which never is).
    baditicker_poiid: str | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Notice:
    """A scraped alert/notice about a pool (e.g. a maintenance closure), with the period it
    is active. Surfaced to users; closure-type notices also drive a `ClosureRange`."""

    text: str
    active_from: date | None = None
    active_to: date | None = None

    def active_on(self, day: date) -> bool:
        after_start = self.active_from is None or day >= self.active_from
        before_end = self.active_to is None or day <= self.active_to
        return after_start and before_end


class BasinKind(Enum):
    """What kind of swimmable water a basin holds — parsed from `infrastruktur` prose."""

    LAP = "lap"  # Schwimmerbecken
    NON_SWIMMER = "non_swimmer"  # Nichtschwimmerbecken
    DIVING = "diving"  # Sprung-/Tauchbecken
    VARIO = "vario"  # Variobecken (Hubboden)
    TEACHING = "teaching"  # Lehrschwimmbecken
    CHILDREN = "children"  # Kinderbecken
    OUTDOOR = "outdoor"  # Aussenbecken
    OTHER = "other"


class BasinSource(Enum):
    """Honesty signal for a basin's physical attributes: hand-verified vs prose-scraped."""

    CURATED = "curated"  # hand-verified YAML
    PARSED_PROSE = "parsed_prose"  # extracted from `infrastruktur` free text


@dataclass(frozen=True, slots=True)
class Dimensions:
    """Basin surface dimensions. `Decimal` because prose dimensions are fractional
    (e.g. "10,5 x 7 m", "16,66 m")."""

    length_m: Decimal
    width_m: Decimal | None = None


@dataclass(frozen=True, slots=True)
class LanePlanSource:
    """Where a basin's lane document (its Belegungsplan PDF) lives — a FIRST-CLASS domain
    attribute authored in ``data/pools/*.yaml``. Every declared source is a PDF we parse; there
    is no ``format``/``label``/fallback. ``section`` is the bare basin token for a STACKED
    multi-basin sheet (``None`` => the whole sheet is this one basin's plan)."""

    url: str
    section: str | None = None


@dataclass(frozen=True, slots=True)
class LanePlanUnavailable:
    """A declared ``lane_plan_source`` whose extraction was attempted and FAILED — first-class
    persisted state, not an exception. ``cause`` is the real closed-union ``ProviderError``,
    persisted losslessly, so partial extraction loses nothing and recovery can select failed
    rows by error class."""

    source_url: str
    section: str | None
    cause: ProviderError
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class Basin:
    basin_id: BasinId
    name: str
    rules: tuple[ScheduleRule, ...]
    exceptions: tuple[ScheduleException, ...] = field(default_factory=tuple)
    kind: BasinKind = BasinKind.OTHER
    dimensions: Dimensions | None = None
    lanes: int | None = None  # "(6 Bahnen)"
    nominal_temp_c: Decimal | None = None  # "28°C" — a design target, NOT a live reading
    # A distinct, actually-measured water temperature (e.g. a scraped "aktuell 26°C" reading), as
    # opposed to the `nominal_temp_c` design target. Kept separate so the UI can show the measured
    # value while a tooltip still carries the nominal one (decision #4). `physical_source` tags the
    # honesty of the basin's physicals as a whole (curated vs prose-scraped).
    measured_temp_c: Decimal | None = None
    diving_platforms_m: tuple[Decimal, ...] = ()  # e.g. (1, 3, 5) from "Sprungbecken 1/3/5m"
    physical_source: BasinSource = BasinSource.CURATED
    # Curated INPUT: where this basin's lane document lives (drives extraction). Distinct from
    # `lane_plan`, the extraction OUTCOME below.
    lane_plan_source: LanePlanSource | None = None
    # Extraction OUTCOME, first-class persisted state:
    #   None                -> nothing to extract (no source) OR scrape not yet run
    #   LanePlan            -> parsed grid
    #   LanePlanUnavailable -> source declared, extraction attempted and FAILED (cause persisted)
    lane_plan: LanePlan | LanePlanUnavailable | None = None


class FeatureKind(Enum):
    """A non-swim amenity kind. Deliberately NOT a `BasinKind`: features cannot host
    swim sessions, and folding them into basins would leak non-swim rows into
    `find_swim_options` (see docs/entities/feature.md)."""

    SAUNA = "sauna"
    STEAM_BATH = "steam_bath"
    WELLNESS = "wellness"
    SLIDE = "slide"
    HOT_TUB = "hot_tub"
    TERRACE = "terrace"  # Sonnenterrasse / sun deck
    REST = "rest"  # Liegewiese / Sandstrand — a rest/sunbathing area
    GASTRONOMY = "gastronomy"  # Restaurant / kiosk / café


@dataclass(frozen=True, slots=True)
class Feature:
    """A non-swim amenity on a facility — static. `hours` reuses `ScheduleRule`, so
    "is the sauna open now?" resolves through the existing resolver; empty means the
    feature has no separately stated hours."""

    kind: FeatureKind
    name: str
    hours: tuple[ScheduleRule, ...] = ()
    surcharge_chf: Decimal | None = None  # "Eintritt Fr. 10.-"
    temp_c: Decimal | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class Facility:
    identity: PoolIdentity
    address: str
    provenance: Provenance
    basins: tuple[Basin, ...]
    geo: GeoPoint | None = None
    amenities: frozenset[str] = frozenset()
    closures: tuple[ClosureRange, ...] = field(default_factory=tuple)
    public_holiday_policy: HolidayPolicy = HolidayPolicy.NORMAL
    prices: PriceTable | None = None
    notices: tuple[Notice, ...] = field(default_factory=tuple)
    website: str | None = None  # static (WFS `www` / official pool page)
    features: tuple[Feature, ...] = field(default_factory=tuple)
    lockers: tuple[LockerOption, ...] = field(default_factory=tuple)
    # Free-text accessibility note ("barrierefrei", "Lift zum Becken") — static, best-effort.
    accessibility: str | None = None
    # How long before closing the last admission is (e.g. 30 min). `timedelta` so the UI can render
    # it against the resolved closing time rather than hard-coding a clock.
    last_admission_before: timedelta | None = None
