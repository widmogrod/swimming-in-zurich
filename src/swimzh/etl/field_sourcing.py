"""S5a field→producer audit: the machine-checkable source-of-truth table that maps every
serialized ``facility_doc`` field to exactly one producer.

``facility_doc`` is ``storage.codec.dumps(facility)`` == ``StoredFacilityDTO.model_dump_json()``,
so the serialization boundary is precisely the fields of two pydantic roots: ``StoredFacilityDTO``
(facility level) and the nested ``BasinDTO`` (basin level, the one list whose members carry
*independently sourced* facts — physicals, per-basin rules, the lane binding key). Every leaf below
those roots (``RuleDTO``/``AccessDTO``/``PriceEntryDTO``/``LanePlanDTO`` sub-fields) inherits its
parent field's producer and is not enumerated separately.

This is an AUDIT artifact, not a runtime data path: nothing here changes what a build writes. Its
job is to fix the *true residue* — what curated YAML still adds that no website provider produces —
so later sub-slices (S5b/S5c/S5d) do not build a provider for a fact already sourced. The companion
test (``tests/etl/test_field_sourcing.py``) asserts this table covers exactly the serialized fields
of both roots — no field unlisted, no stale entry (S5 acceptance #1, scoped to the audit).

Producer kinds
--------------
* ``SOURCED`` — a website provider module already produces this fact (identity/geo → WFS roster;
  schedules/access-categories/closures/notices → ``schedule_scraper``; prices → ``price_scraper``,
  wired into ``scrape-gold``; basin physicals → ``infrastruktur`` for the 2/7 prose pools; lane
  plans → ``belegungsplan`` via ``scrape-lanes``). ``coverage`` states the honest scope.
* ``CURATED_CROSSWALK`` — an irreducible correlation/binding fact that is on **no** website
  (per-basin lane URL→basin binding, ``baditicker_poiid``, ``crowdmonitor_keys``, human
  ``aliases``). The retained thin crosswalk (S3/S6 checkpoint). ``geo_sport_id`` LEFT this bucket
  in S5b — it is now ``SOURCED`` from the WFS ``poi_id``.
* ``DROP_CANDIDATE`` — genuine residue: a curated fact with **no** website producer today
  (``public_holiday_policy``, ``lockers``, ``accessibility``, ``last_admission_before``,
  ``amenities``, schedule ``exceptions``, basin physicals for the 5 NULL-prose pools, richer access
  vocabulary). Source-or-drop is decided by S5c (attempt) / S5d (recorded drop).
* ``BUILD_METADATA`` — provenance / honesty tags produced by the build itself, not by a data
  provider (``source``, ``curated``, ``valid_as_of``, ``fetched_at``, basin ``physical_source``).
  A fourth bucket beyond the plan's three because forcing provenance fields into a data-provider
  bucket would be dishonest; "producer" (S5a's word) legitimately includes the composer/codec.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProducerKind(Enum):
    """How a serialized ``facility_doc`` field is produced."""

    SOURCED = "sourced"  # a website provider already produces it
    CURATED_CROSSWALK = "curated-crosswalk"  # irreducible binding/correlation fact, on no website
    DROP_CANDIDATE = "drop-candidate"  # genuine residue: no website producer today
    BUILD_METADATA = "build-metadata"  # provenance/honesty tag, from the build not a provider


@dataclass(frozen=True, slots=True)
class FieldSourcing:
    """One serialized field's producer classification.

    ``field`` is a qualified name — ``facility.<x>`` for a ``StoredFacilityDTO`` field,
    ``basin.<x>`` for a ``BasinDTO`` field. ``module`` names the producing provider when
    ``SOURCED`` (dotted, e.g. ``providers.schedule_scraper``), else ``None``. ``coverage`` is the
    honest scope of the claim (e.g. ``2/7 prose pools``). ``note`` carries the evidence / the
    onward S5 routing.
    """

    field: str
    producer: ProducerKind
    module: str | None
    coverage: str
    note: str


_ROSTER = "etl.roster"  # WFS identity spine + geo (S3)
_SCHEDULE = "providers.schedule_scraper"  # timetable → rules; parse_notices → notices/closures
_PRICE = "providers.price_scraper"  # central admission tariff, wired into scrape-gold
_INFRA = "providers.infrastruktur"  # WFS `infrastruktur` prose → basin physicals + features
_LANE = "providers.belegungsplan"  # per-basin Belegungsplan PDF → LanePlan


# --- facility-level fields (StoredFacilityDTO) ------------------------------------------

_FACILITY: tuple[FieldSourcing, ...] = (
    FieldSourcing(
        "facility.facility_id",
        ProducerKind.SOURCED,
        _ROSTER,
        "7/7",
        "Canonical PoolId minted from the WFS identity spine (S3).",
    ),
    FieldSourcing("facility.name", ProducerKind.SOURCED, _ROSTER, "7/7", "WFS display name."),
    FieldSourcing(
        "facility.kind",
        ProducerKind.SOURCED,
        _ROSTER,
        "7/7",
        "Facility PoolKind from the WFS layer; the kaeferberg `thermal` override rides the "
        "retained registry crosswalk (S3), not a per-field source.",
    ),
    FieldSourcing("facility.address", ProducerKind.SOURCED, _ROSTER, "7/7", "WFS address."),
    FieldSourcing(
        "facility.source",
        ProducerKind.BUILD_METADATA,
        None,
        "n/a",
        "provenance.source string ('schedule_scraper'/'curated'/'infrastruktur'), set by the "
        "build/compose layer.",
    ),
    FieldSourcing(
        "facility.curated",
        ProducerKind.BUILD_METADATA,
        None,
        "n/a",
        "Provenance flag serialized from Provenance.curated by the build/codec, not from a data "
        "provider (distinct from codec.schedule_freshness, a separate read-time derivation for "
        "the schedule-freshness status).",
    ),
    FieldSourcing(
        "facility.valid_as_of", ProducerKind.BUILD_METADATA, None, "n/a", "provenance freshness."
    ),
    FieldSourcing(
        "facility.fetched_at", ProducerKind.BUILD_METADATA, None, "n/a", "provenance freshness."
    ),
    FieldSourcing(
        "facility.geo_sport_id",
        ProducerKind.SOURCED,
        _ROSTER,
        "7/7 indoor (recorded)",
        "geo-sport occupancy key, SOURCED from the WFS `poi_id` by build_spine (S5b): the roster "
        "carries `poi_id` (e.g. `hb001`) and the spine stamps it as `geo_sport_id`, replacing the "
        "retired registry-crosswalk placeholder. Verified 7/7 against the indoor WFS cassette "
        "(hb001–hb007); live WFS carries poi_id per layer for the rest.",
    ),
    FieldSourcing(
        "facility.crowdmonitor_keys",
        ProducerKind.CURATED_CROSSWALK,
        None,
        "crosswalk",
        "Crowdmonitor occupancy keys; on no website, irreducible crosswalk.",
    ),
    FieldSourcing(
        "facility.baditicker_poiid",
        ProducerKind.CURATED_CROSSWALK,
        None,
        "crosswalk",
        "Baditicker water-temp feed poiid; on no website, irreducible crosswalk.",
    ),
    FieldSourcing(
        "facility.aliases",
        ProducerKind.CURATED_CROSSWALK,
        None,
        "crosswalk",
        "Human alias strings for reconcile; on no website, irreducible crosswalk.",
    ),
    FieldSourcing(
        "facility.geo",
        ProducerKind.SOURCED,
        _ROSTER,
        "7/7",
        "WFS lat/lon (live WFS since S3; previously committed catalog.json).",
    ),
    FieldSourcing(
        "facility.amenities",
        ProducerKind.DROP_CANDIDATE,
        None,
        "0/7",
        "Facility amenity string-set — curated-only; NO provider emits it. `infrastruktur` emits "
        "structured `features`, not this free string-set. Residue → S5d drop unless folded into "
        "features.",
    ),
    FieldSourcing(
        "facility.public_holiday_policy",
        ProducerKind.DROP_CANDIDATE,
        None,
        "0/7",
        "Not in any source (S1 residue). Recorded-drop candidate (S5d) unless a discovered signal "
        "is found.",
    ),
    FieldSourcing(
        "facility.prices",
        ProducerKind.SOURCED,
        _PRICE,
        "city-run pools",
        "Central city-wide admission tariff scraped by price_scraper and attached to stadt-"
        "zuerich.ch pools in the scrape-gold layer (NOT the base `build`). Compose precedence is "
        "curated-wins today, so a curated `prices:` block still shadows the scrape until S6 "
        "deletes the authoritative curated payload; the producer is nonetheless the website "
        "scrape.",
    ),
    FieldSourcing(
        "facility.closures",
        ProducerKind.SOURCED,
        _SCHEDULE,
        "3/7 observed",
        "parse_notices → _closures_from_notices (disturber notices with a date range + a closure "
        "word). Proven in S1 for bungertwies/city/oerlikon.",
    ),
    FieldSourcing(
        "facility.basins",
        ProducerKind.SOURCED,
        _SCHEDULE,
        "7/7 facility-level",
        "The scrape mints a single 'Hauptbecken' basin carrying the facility-level timetable "
        "rules. Per-basin DECOMPOSITION is residue (see basin.* rows); basin physicals come from "
        "infrastruktur. See the basin-level entries for per-field producers.",
    ),
    FieldSourcing(
        "facility.notices",
        ProducerKind.SOURCED,
        _SCHEDULE,
        "7/7",
        "parse_notices over the pool page (alerts/notices).",
    ),
    FieldSourcing(
        "facility.website",
        ProducerKind.SOURCED,
        _ROSTER,
        "7/7",
        "WFS `www` / official pool page URL.",
    ),
    FieldSourcing(
        "facility.features",
        ProducerKind.SOURCED,
        _INFRA,
        "2/7 prose pools",
        "parse_features over WFS `infrastruktur` prose (sauna/terrace/gastronomy…). Only city & "
        "bungertwies have prose; the other 5 are literal 'NULL' → residue (S5d) for them. NOTE the "
        "parser today runs only on the uncurated location-only path; S5 formalizes it as the "
        "producer for curated pools too.",
    ),
    FieldSourcing(
        "facility.lockers",
        ProducerKind.DROP_CANDIDATE,
        None,
        "0/7",
        "Locker options — curated-only; no provider extracts them. Residue → S5d drop.",
    ),
    FieldSourcing(
        "facility.accessibility",
        ProducerKind.DROP_CANDIDATE,
        None,
        "0/7",
        "Free-text accessibility note — curated-only; no provider. Residue → S5d drop.",
    ),
    FieldSourcing(
        "facility.last_admission_before",
        ProducerKind.DROP_CANDIDATE,
        None,
        "0/7",
        "Last-admission offset — curated-only; no provider. Residue → S5d drop.",
    ),
)


# --- basin-level fields (BasinDTO) ------------------------------------------------------

_BASIN: tuple[FieldSourcing, ...] = (
    FieldSourcing(
        "basin.basin_id",
        ProducerKind.SOURCED,
        _SCHEDULE,
        "7/7 facility-level",
        "Scrape mints `<pool_id>-main`; a real per-basin id set is part of the per-basin-split "
        "residue (S5c/S5d).",
    ),
    FieldSourcing(
        "basin.name",
        ProducerKind.SOURCED,
        _SCHEDULE,
        "7/7 facility-level",
        "Scrape mints 'Hauptbecken'; per-basin names belong to the per-basin split (S5c/S5d).",
    ),
    FieldSourcing(
        "basin.rules",
        ProducerKind.SOURCED,
        _SCHEDULE,
        "7/7 facility-level",
        "parse_schedule → facility-level ScheduleRules (day/hours/access-category). Two residues "
        "ride this field: (a) PER-BASIN SPLIT — routing the flat timetable to basins → SOURCEABLE "
        "from the per-basin Belegungsplan public windows (S5c); (b) RICHER ACCESS "
        "(lane_swim/family/adults_only) — NOT sourceable: both the timetable's category vocabulary "
        "(public/women/seniors/school) and the Belegungsplan legend vocabulary "
        "(public/school/club) are closed and emit none of them → DROP (S5d).",
    ),
    FieldSourcing(
        "basin.exceptions",
        ProducerKind.DROP_CANDIDATE,
        None,
        "0/7",
        "Per-date session overrides — curated-only; not in source (closures ARE sourced, but "
        "date-specific session substitutions are not). Residue → S5d drop.",
    ),
    FieldSourcing(
        "basin.kind",
        ProducerKind.SOURCED,
        _INFRA,
        "2/7 prose pools",
        "parse_infrastruktur basin kind. Only city & bungertwies have prose (and even there kind "
        "can mis-parse, S1); the other 5 are 'NULL' → S5d drop for them.",
    ),
    FieldSourcing(
        "basin.dimensions",
        ProducerKind.SOURCED,
        _INFRA,
        "2/7 prose pools",
        "parse_infrastruktur dimensions; residue for the 5 NULL-prose pools (S5d).",
    ),
    FieldSourcing(
        "basin.lanes",
        ProducerKind.SOURCED,
        _INFRA,
        "2/7 prose pools",
        "parse_infrastruktur lane count; residue for the 5 NULL-prose pools (S5d). (The "
        "Belegungsplan also yields a lane_count, but only for basins with a lane PDF.)",
    ),
    FieldSourcing(
        "basin.nominal_temp_c",
        ProducerKind.SOURCED,
        _INFRA,
        "2/7 prose pools",
        "parse_infrastruktur nominal temp; residue for the 5 NULL-prose pools (S5d).",
    ),
    FieldSourcing(
        "basin.measured_temp_c",
        ProducerKind.DROP_CANDIDATE,
        None,
        "0/7",
        "A live measured reading — out of scope (occupancy/live track); never written today.",
    ),
    FieldSourcing(
        "basin.diving_platforms_m",
        ProducerKind.SOURCED,
        _INFRA,
        "2/7 prose pools",
        "parse_infrastruktur diving platforms; residue for the 5 NULL-prose pools (S5d).",
    ),
    FieldSourcing(
        "basin.physical_source",
        ProducerKind.BUILD_METADATA,
        None,
        "n/a",
        "Honesty tag (curated vs parsed_prose) for the basin physicals; set by the physical "
        "producer, not sourced.",
    ),
    FieldSourcing(
        "basin.lane_plan_source",
        ProducerKind.CURATED_CROSSWALK,
        None,
        "crosswalk",
        "The per-basin URL→basin BINDING KEY. Irreducibly per-basin (a single-basin PDF header "
        "cannot name its basin — S2), so it stays authored crosswalk; discovery supplies the "
        "fetch-set, not this binding.",
    ),
    FieldSourcing(
        "basin.lane_plan",
        ProducerKind.SOURCED,
        _LANE,
        "basins with a lane PDF",
        "parse_belegungsplan → LanePlan, attached by scrape-lanes on the URL-keyed join.",
    ),
)


FACILITY_FIELD_SOURCING: tuple[FieldSourcing, ...] = _FACILITY + _BASIN


def classified_fields() -> frozenset[str]:
    """Every qualified field name the table classifies (for the coverage test)."""
    return frozenset(entry.field for entry in FACILITY_FIELD_SOURCING)
