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
  (``accessibility``, ``amenities``, schedule ``exceptions``, basin physicals for the 5 NULL-prose
  pools, richer access vocabulary). Source-or-drop is decided by S5c (attempt) / S5d (recorded
  drop). ``public_holiday_policy`` LEFT this bucket in 2026-08-04 and ``last_admission_before`` in
  2026-08-06 — both are ``SOURCED`` from the pool page now; ``lockers`` left
  ``SOURCEABLE_UNBUILT`` in 2026-08-09 (``providers.mietobjekt``, mietobjekt-extraction S1).
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
    #: A source demonstrably EXISTS but no provider reads it yet. Distinct from
    #: DROP_CANDIDATE, whose whole meaning is "nothing out there produces this". Without
    #: this member every such field had to be filed as a drop candidate, which is how
    #: `lockers` (a `Mietobjekt|Preis` table on 20 of the 26 declared sources' committed
    #: fixtures — the 2026-08-02 note's "25 pages" grepped ALL fixtures, not the declared
    #: ones) and `last_admission_before` (stated verbatim on 32) came to be listed as
    #: residue scheduled for deletion. Both have since left the bucket (SOURCED).
    SOURCEABLE_UNBUILT = "sourceable-unbuilt"  # a source exists; no provider built yet
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
        "facility.public_holiday_policy",
        ProducerKind.SOURCED,
        _SCHEDULE,
        "4/57 stated; 53 honestly unknown",
        "FALSIFIED 2026-08-04: four pools write '(und Feiertage)' into a Sunday timetable row "
        "(blaesi, bungertwies, leimbach, kaeferberg) — the city stating SUNDAY_SCHEDULE. Read by "
        "schedule_scraper._holiday_policy. Every other pool is None (unknown); the field no longer "
        "defaults to a fabricated NORMAL that the resolver then acted on.",
    ),
    FieldSourcing(
        "facility.prices",
        ProducerKind.SOURCED,
        _PRICE,
        "21/26 declared sources",
        "Central city-wide admission tariff scraped by price_scraper and attached to every pool "
        "whose OWN PAGE LINKS that tariff page. The atomic `build` folds the schedule phase in, so "
        "a plain `build` produces all 21 priced rows; `scrape-gold` re-runs the same phase. "
        "Compose precedence is "
        "curated-wins today, so a curated `prices:` block still shadows the scrape until S6 "
        "deletes the authoritative curated payload; the producer is nonetheless the website "
        "scrape. FALSIFIED 2026-08-06: the age BANDS were domain constants (<=5/<=15/>=65 plus an "
        "invented SENIOR rate) while the page prints its own — 'Erwachsene (ab 20 J.)', "
        "'Jugendliche (ab 16 J.)', 'Kinder (ab 6 J.)'. `PriceEntry.min_age` now carries the "
        "published bound; a 15-year-old was overcharged and a 70-year-old undercharged. Under-6 "
        "is unpriced on the page and resolves to None, never to the adult rate. FALSIFIED "
        "2026-08-07: the page publishes TWO single-admission rates and only the general one was "
        "read — the 4 Schulschwimmanlagen were served the Hallenbad rate (Fr. 8.–/6.–/4.–) where "
        "the city prints 'Eintritte Schulschwimmanlagen' Fr. 5.–/5.–/2.50. `parse_prices` now "
        "returns both (`CityTariffs`, section-anchored within the one table carrying that "
        "section) and `etl.scrape.admission_for` picks by pool kind. FALSIFIED 2026-08-07: the "
        "fan-out gated on the literal host `stadt-zuerich.ch`, so 15 of the 26 declared sources — "
        "the ones the city publishes on sportamt.ch — were unpriced. The gate is now the tariff "
        "LINK the pool's own page emits (`price_scraper.states_city_tariff`), which prices 21 and "
        "correctly withholds a rate from the 4 pools the city states are free plus the privately "
        "run maennerbad-schanzengraben. RESOLVED 2026-08-08 (admission-union): free-ness is no "
        "longer compressed into the null — the serialized `prices` key is the `Tariff` arm of "
        "the `Admission` union, `Unknown` is `prices: null`, and `Free` rides the "
        "`admission_state` discriminant (its own row below).",
    ),
    FieldSourcing(
        "facility.admission_state",
        ProducerKind.SOURCED,
        _PRICE,
        "17/57 — 4 declared sources + the 13 Planschbecken",
        'The `Free` arm of the `Admission` union: "free" when the pool\'s own page states '
        "'Der Eintritt … ist gratis' / 'ein Gratisbad' (`price_scraper.states_free_admission`, "
        "the tight sentence only — never bare 'gratis', which the locker rows print on 21 of 26 "
        "pages), or when the shared Planschbecken page states 'Die Nutzung … ist kostenlos' for "
        "its 13 members (`providers.planschbecken`, sharedsource-fanout S3). Popped when "
        "absent, so `Tariff`/`Unknown` blobs are byte-identical to pre-union gold.",
    ),
    FieldSourcing(
        "facility.operating_season",
        ProducerKind.SOURCED,
        "providers.planschbecken",
        "13/57 — the Planschbecken members",
        "The facility-level, timetable-free season (sharedsource-fanout). The Planschbecken "
        "overview page states it once for all 13 members ('je nach Wetter von Mai bis September "
        "in Betrieb'); `etl.scrape.scrape_shared_sources` fetches that page once and fans the "
        "parsed `SharedFacts` out to every member (S3). Popped when `None`, so the other 44 "
        "blobs omit the key and serialize byte-identically.",
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
        ProducerKind.SOURCED,
        "providers.mietobjekt",
        "20/26 declared sources",
        "BUILT 2026-08-09 (mietobjekt-extraction S1): parse_mietobjekte reads the "
        "<stzh-datatable columns=[Mietobjekt, Preis]> on the pool's own page and routes the "
        "locker nouns (…kasten / Wertsachenfach / Wäschefach) to LockerOption; "
        "etl.scrape._aspects fills the compose slot that had waited since Slice F. MEASURED "
        "over the 26 declared sources' committed fixtures: 20 carry the table (the 2026-08-02 "
        "note's '25 pages' grepped all fixtures, not the declared set); the 6 without are "
        "altstetten, maennerbad, and the 4 Schulschwimmanlagen. The non-locker rows of the "
        "same table are `rentals` — parsed since S1, wired onto the facility in S2.",
    ),
    FieldSourcing(
        "facility.last_admission_before",
        ProducerKind.SOURCED,
        _SCHEDULE,
        "23/26 declared sources",
        "BUILT 2026-08-06 (seasonal-hours S2/S3): read from the sentence itself ('Der letzte "
        "Einlass erfolgt bis/spätestens 30 Minuten vor Badschluss'), NOT from the <sup>1</sup> "
        "marker — 2 pages print it as standalone prose with no marker, and au-hoengg's marker is a "
        "daylight caveat carrying no admission rule. `None` stays the honest silence.",
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
        "from the per-basin Belegungsplan public windows (S5c); (b) RICHER ACCESS — "
        "adults_only IS sourced (the school pages publish 'für Erwachsene'; the school-access "
        "vocabulary slice added girls_only/gender_diverse/accompanied_children alongside it), "
        "but lane_swim/family are emitted by neither the timetable vocabulary nor the "
        "Belegungsplan legend (public/school/club) → DROP (S5d).",
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
