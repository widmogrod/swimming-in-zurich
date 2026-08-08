"""Pydantic v2 DTOs for the hand-curated YAML (calendar, registry, per-pool files).

These validate the on-disk shape; `providers.curated` maps them into the domain. Access
rules are a discriminated union on `type`, mirroring the domain's `SessionAccess` tagged
union so the boundary and the domain stay in one-to-one correspondence.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from swimzh.core.errors import JsonValue

_Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_Scope = Literal["always", "school_term", "school_holiday"]
_HolidayPolicy = Literal["normal", "sunday_schedule", "closed"]
_Weather = Literal["any", "fair_only"]
_DatePrecision = Literal["day", "month"]
_PoolKind = Literal["indoor", "outdoor", "river", "lake", "school", "paddling", "thermal"]
_PriceCategory = Literal["child", "youth", "adult"]
#: The stored-blob discriminant for the `Free` arm of the admission union. `"free"` is its only
#: value: `Tariff` is discriminated by a non-null `prices` table and `Unknown` by the absence of
#: both, so a pre-union blob (`prices: null`, no `admission_state` key) loads as `Unknown` — the
#: honest reading of a blob that predates the distinction.
_AdmissionState = Literal["free"]
_BasinKind = Literal[
    "lap", "non_swimmer", "diving", "vario", "teaching", "children", "outdoor", "other"
]
_BasinSource = Literal["curated", "parsed_prose"]
_PlanConfidence = Literal["complete", "partial"]
_FeatureKind = Literal[
    "sauna", "steam_bath", "wellness", "slide", "hot_tub", "terrace", "rest", "gastronomy"
]
_LockerCategory = Literal["wardrobe", "valuables", "laundry"]
_LockerMechanism = Literal["coin", "key", "chip", "wristband", "other"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- access (discriminated union) -------------------------------------------------


class PublicDTO(_Strict):
    type: Literal["public"]


class LaneSwimDTO(_Strict):
    type: Literal["lane_swim"]
    note: str = ""


class FamilyDTO(_Strict):
    type: Literal["family"]
    note: str = ""


class WomenOnlyDTO(_Strict):
    type: Literal["women_only"]
    note: str = ""


class SeniorsOnlyDTO(_Strict):
    type: Literal["seniors_only"]
    min_age: int = 60


class SchoolReservedDTO(_Strict):
    type: Literal["school_reserved"]


class ClubReservedDTO(_Strict):
    type: Literal["club_reserved"]
    club: str = ""


class AdultsOnlyDTO(_Strict):
    type: Literal["adults_only"]
    min_age: int = 18
    note: str = ""


class GirlsOnlyDTO(_Strict):
    type: Literal["girls_only"]


class GenderDiverseDTO(_Strict):
    type: Literal["gender_diverse"]
    #: Required, mirroring the domain: the page states the bound, so nothing may default it.
    min_age: int


class AccompaniedChildrenDTO(_Strict):
    type: Literal["accompanied_children"]


AccessDTO = Annotated[
    PublicDTO
    | LaneSwimDTO
    | FamilyDTO
    | WomenOnlyDTO
    | SeniorsOnlyDTO
    | SchoolReservedDTO
    | ClubReservedDTO
    | AdultsOnlyDTO
    | GirlsOnlyDTO
    | GenderDiverseDTO
    | AccompaniedChildrenDTO,
    Field(discriminator="type"),
]


# --- schedule ---------------------------------------------------------------------


class SeasonDTO(_Strict):
    """A year-free part of the year. `start_*` > `end_*` wraps New Year.

    The day fields are always present and always meaningful; `precision` decides whether they
    are *read*. `"month"` means whole months inclusive, so the days carry the natural bounds
    (1st and last of the month) and a consumer that ignored `precision` would still be close
    rather than wrong.
    """

    start_month: int = Field(ge=1, le=12)
    start_day: int = Field(ge=1, le=31)
    end_month: int = Field(ge=1, le=12)
    end_day: int = Field(ge=1, le=31)
    precision: _DatePrecision = "day"


class RuleDTO(_Strict):
    weekdays: list[_Weekday]
    start: time
    end: time
    access: AccessDTO
    scope: _Scope = "always"
    #: The verbatim source cell the access was classified from. Empty for every rule that
    #: came from a source without a category column (and for every hand-authored rule).
    source_text: str = ""
    #: The part of the year this rule applies to; `None` == all year round.
    season: SeasonDTO | None = None
    weather: _Weather = "any"

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Additive-and-invisible: a defaulted field must not appear in the payload, so a rule
        # that predates it serialises to exactly the same bytes as before it. Note this pops BY
        # NAME — every new defaulted field has to be added here, or it leaks into every blob.
        data: dict[str, Any] = handler(self)
        if not self.source_text:
            data.pop("source_text", None)
        if self.season is None:
            data.pop("season", None)
        if self.weather == "any":
            data.pop("weather", None)
        return data


class ResolvedSessionDTO(_Strict):
    start: time
    end: time
    access: AccessDTO
    weather: _Weather = "any"

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # This DTO had NO serializer before `weather`: it is reached via `ExceptionDTO.sessions`,
        # so a bare additive field would have added a key to every exception-bearing blob.
        data: dict[str, Any] = handler(self)
        if self.weather == "any":
            data.pop("weather", None)
        return data


class ExceptionDTO(_Strict):
    date: date
    closed: bool = False
    reason: str = ""
    sessions: list[ResolvedSessionDTO] = []


class ClosureDTO(_Strict):
    start: date
    end: date
    reason: str = ""


class DimensionsDTO(_Strict):
    length_m: Decimal
    width_m: Decimal | None = None


# --- ProviderError (closed union, lossless codec) ---------------------------------
#
# A discriminated union over `type`, one arm per `core.errors` variant, so a persisted
# `LanePlanUnavailable.cause` round-trips losslessly (no variant special-cased, no `repr`).
# `ProviderSpecific.detail` is `JsonValue` — the narrowing that makes the whole union encodable.


class TimeoutDTO(_Strict):
    type: Literal["timeout"]
    url: str
    after_s: float


class ConnectionFailedDTO(_Strict):
    type: Literal["connection_failed"]
    url: str
    detail: str


class HttpStatusDTO(_Strict):
    type: Literal["http_status"]
    url: str
    status: int
    body_snippet: str


class RateLimitedDTO(_Strict):
    type: Literal["rate_limited"]
    url: str
    retry_after_s: float | None


class DecodeErrorDTO(_Strict):
    type: Literal["decode_error"]
    source: str
    detail: str


class ParseErrorDTO(_Strict):
    type: Literal["parse_error"]
    source: str
    detail: str
    raw_snippet: str


class SchemaMismatchDTO(_Strict):
    type: Literal["schema_mismatch"]
    source: str
    detail: str


class TooLargeDTO(_Strict):
    type: Literal["too_large"]
    url: str
    limit_bytes: int


class RedirectDTO(_Strict):
    type: Literal["redirect"]
    url: str
    location: str
    count: int


class ProviderSpecificDTO(_Strict):
    type: Literal["provider_specific"]
    provider: str
    detail: JsonValue


ProviderErrorDTO = Annotated[
    TimeoutDTO
    | ConnectionFailedDTO
    | HttpStatusDTO
    | RateLimitedDTO
    | DecodeErrorDTO
    | ParseErrorDTO
    | SchemaMismatchDTO
    | TooLargeDTO
    | RedirectDTO
    | ProviderSpecificDTO,
    Field(discriminator="type"),
]


# --- lane reservations (Belegungsplan) --------------------------------------------


class LanePlanSourceDTO(_Strict):
    url: str
    section: str | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Additive-and-invisible: a `None` `section` must not appear in the payload.
        data: dict[str, Any] = handler(self)
        if self.section is None:
            data.pop("section", None)
        return data


class LanePlanUnavailableDTO(_Strict):
    """The extraction-failed state persisted on a basin's `lane_plan`. Structurally disjoint
    from `LanePlanDTO` (no `lane_count`/`coverage`), so a pydantic smart union discriminates the
    two by shape — a pre-existing `LanePlanDTO` blob still validates unchanged."""

    source_url: str
    cause: ProviderErrorDTO
    observed_at: datetime
    section: str | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.section is None:
            data.pop("section", None)
        return data


class LaneReservationDTO(_Strict):
    weekdays: list[_Weekday]
    start: time
    end: time
    lanes: list[int]
    access: AccessDTO
    section: str | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Additive-and-invisible: a `None` `section` must not appear in the payload, so a
        # pre-existing reservation serialises to exactly the same bytes as before this field.
        data: dict[str, Any] = handler(self)
        if self.section is None:
            data.pop("section", None)
        return data


class PlanCoverageDTO(_Strict):
    confidence: _PlanConfidence
    cells_total: int
    cells_resolved: int
    unresolved_lanes: list[int] = []


class LanePlanDTO(_Strict):
    lane_count: int
    reservations: list[LaneReservationDTO]
    valid_from: date | None = None
    coverage: PlanCoverageDTO
    fetched_at: datetime | None = None
    lanes_by_weekday: dict[_Weekday, int] | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Additive-and-invisible: a `None` `lanes_by_weekday` must not appear in the payload, so
        # an existing uniform plan serialises to exactly the same bytes as before this field.
        data: dict[str, Any] = handler(self)
        if self.lanes_by_weekday is None:
            data.pop("lanes_by_weekday", None)
        return data


class BasinDTO(_Strict):
    basin_id: str
    name: str
    # Optional (default empty) since S1 of delete-curated-schedule-tier: a stripped pool file
    # carries only the crosswalk binding (`basin_id`/`name`/`lane_plan_source`), no schedule.
    # A rule-less basin derives `awaiting_scrape`/`no_source` freshness, never a `/swim` option.
    rules: list[RuleDTO] = []
    exceptions: list[ExceptionDTO] = []
    kind: _BasinKind = "other"
    dimensions: DimensionsDTO | None = None
    lanes: int | None = None
    nominal_temp_c: Decimal | None = None
    measured_temp_c: Decimal | None = None
    diving_platforms_m: list[Decimal] = []
    physical_source: _BasinSource = "curated"
    # Curated input (where the lane document lives) vs the extraction outcome. `lane_plan` widens
    # to carry a typed extraction FAILURE (`LanePlanUnavailableDTO`) as first-class persisted
    # state; a pydantic smart union discriminates it from a parsed `LanePlanDTO` by shape.
    lane_plan_source: LanePlanSourceDTO | None = None
    lane_plan: LanePlanDTO | LanePlanUnavailableDTO | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Additive-and-invisible (like Slice D): a basin with none of the additive fields set must
        # serialise to exactly the same bytes as a pre-existing basin, so existing gold blobs
        # round-trip byte-identically. Drop the defaults (`None` / empty list) from the payload.
        data: dict[str, Any] = handler(self)
        if self.measured_temp_c is None:
            data.pop("measured_temp_c", None)
        if not self.diving_platforms_m:
            data.pop("diving_platforms_m", None)
        if self.lane_plan_source is None:
            data.pop("lane_plan_source", None)
        return data


# --- features & lockers (facility-level statics) ----------------------------------


class FeatureDTO(_Strict):
    kind: _FeatureKind
    name: str
    hours: list[RuleDTO] = []
    surcharge_chf: Decimal | None = None
    temp_c: Decimal | None = None
    note: str = ""


class LockerOptionDTO(_Strict):
    category: _LockerCategory
    fee_chf: Decimal | None = None
    deposit_chf: Decimal | None = None
    period: str | None = None
    mechanism: _LockerMechanism | None = None
    raw: str = ""


# --- pricing ----------------------------------------------------------------------


class PriceEntryDTO(_Strict):
    category: _PriceCategory
    amount_chf: Decimal
    display: str
    min_age: int | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Additive-and-invisible: an entry with no published bound serialises to exactly the
        # bytes it did before `min_age` existed.
        data: dict[str, Any] = handler(self)
        if self.min_age is None:
            data.pop("min_age", None)
        return data


class PriceTableDTO(_Strict):
    entries: list[PriceEntryDTO]
    valid_as_of: date | None = None
    source_url: str | None = None


# --- geo --------------------------------------------------------------------------


class GeoDTO(_Strict):
    lat: float
    lon: float


# --- facility ---------------------------------------------------------------------


class FacilityDTO(_Strict):
    facility_id: str
    # Optional since S1 of delete-curated-schedule-tier: a stripped pool file omits `address`
    # (sourced from the WFS roster in the build/seed path — never defaulted to "") and `source`
    # (build-assigned). Physical basin fields already default (see `BasinDTO`), so a blob reduced
    # to `facility_id` + basins-with-only-`lane_plan_source` validates.
    address: str | None = None
    source: str | None = None
    valid_as_of: date | None = None
    geo: GeoDTO | None = None
    #: `None` (the default) == the author did not state it. Previously defaulted to "normal",
    #: which turned silence into a positive claim that the resolver then acted on.
    public_holiday_policy: _HolidayPolicy | None = None
    prices: PriceTableDTO | None = None
    closures: list[ClosureDTO] = []
    basins: list[BasinDTO]
    website: str | None = None
    features: list[FeatureDTO] = []
    lockers: list[LockerOptionDTO] = []
    last_admission_before: timedelta | None = None


# --- registry & calendar ----------------------------------------------------------


class IdentityDTO(_Strict):
    facility_id: str
    name: str
    kind: _PoolKind
    # `geo_sport_id` is no longer a registry-crosswalk field: since S5b it is SOURCED from the
    # WFS `poi_id` by the roster/spine build (`build_spine`), so it is deliberately absent here.
    crowdmonitor_keys: list[str] = Field(default_factory=list)
    baditicker_poiid: str | None = None  # Baditicker water-temp feed poiid; None when unmapped
    aliases: list[str] = Field(default_factory=list)


class RegistryDTO(_Strict):
    facilities: list[IdentityDTO]


class PublicHolidayDTO(_Strict):
    date: date
    name: str


class SchoolHolidayDTO(_Strict):
    name: str
    start: date
    end: date


class CalendarDTO(_Strict):
    known_years: list[int]
    public_holidays: list[PublicHolidayDTO]
    school_holidays: list[SchoolHolidayDTO]
