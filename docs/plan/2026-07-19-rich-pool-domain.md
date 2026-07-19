---
type: plan
status: in-progress      # draft -> approved -> in-progress -> done (approved by owner 2026-07-19: all 4 slices, pause_after S1)
created: 2026-07-19
feature: rich-pool-domain
gates:
  qa: full               # make qa — ruff, format, mypy strict, pytest+coverage floor, CRAP
  review: adversarial    # critic subagent must find no blocking issues
pause_after: [S1]        # model+migration+parser is the riskiest slice — human review before fan-out
links: ["[[basin]]", "[[locker-option]]", "[[feature]]"]
---

# Plan — Rich pool domain model (lanes, basins, temps, lockers, occupancy, notices, website)

Design produced by 2 design sub-agents (purist + pragmatic) → 2 critic agents
(YAGNI/complexity + type-rigor/serialization) → this synthesis. Crystallized into
the plan contract for /dev:implement.

## Context

The catalog already lists all 57 pools and `/swim` answers eligibility from scraped
schedules, prices, and notices. The owner asked to model, cleanly, a set of richer facts:
**swim lanes; multiple basins per facility with their type; school-pool public/adults-only
windows; live occupancy; water temperatures; locker schemes (free/deposit/rental, coin/key
mechanism); and the facility website.** Most physical data comes from parsing the free-text
WFS `infrastruktur` prose (e.g. *"Schwimmerbecken 50 x 15 m (6 Bahnen) 28°C,
Nichtschwimmerbecken 10,5 x 7 m 30°C, Variobecken … 30°C, gemischte Sauna 8-22 Uhr Eintritt
Fr. 10.-"*) — so it is **partial and uncertain**. This plan defines the domain shapes; it is
the companion to the code and must be implemented behind the existing conventions
(frozen dataclasses, tagged unions + `assert_never`, `Result` errors, medallion → SQLite
gold via a pydantic codec, tz-aware Europe/Zurich).

## Decisions (adjudicated)

| # | Question | Verdict | Why |
|---|----------|---------|-----|
| 1 | Tri-state `Fact[T]` (Present/Absent/Unknown + Confidence) on every parsed field | **Reject** | Both critics: quadruples the hand-maintained codec/DTO/mapping triple to encode a distinction the UI collapses to "not shown". Known-absent already falls out of `BasinKind`. |
| 2 | Sauna / steam / wellness / slide | **`Feature` on `Facility`** (not a `BasinKind`) | They have no lanes/water and can't host a `ResolvedSession`; folding into `Basin` leaks non-swim rows into `find_swim_options` and runs `eligibility` on them. Basins = swimmable water. |
| 3 | Locker cost model | **Orthogonal optionals** `fee_chf`/`deposit_chf` **+ `period` + `raw`** (not a tagged union) | Real rows have fee **and** refundable deposit **and** a period co-occurring; a single-tag union can't hold all three independent axes. |
| 4 | Occupancy contract | **`LiveOccupancy \| OccupancyUnavailable` union in `query.py`**, freshness **derived** | Matches house style (`EligibilityResult`/`FacilityStatus` never return bare bool/None); but a stored `freshness` enum + `age_s` can drift from `measured_at`, so derive it. |
| 5 | Adults-only school windows | **Add `AdultsOnly(min_age=18)` to `SessionAccess` now** | School pools really do run adults-only public hours; modelling them as `PublicSwim` would tell a child "you can swim" — a correctness bug in the core surface. Add a coverage test for `ACCESS_TYPES`. |
| 6 | `length_m: int → Decimal` | **Yes, via a `Dimensions(Decimal, …)` field** | Prose dimensions are fractional (`10,5`, `16,66 m`) — int is lossy. No committed gold snapshots exist, so the JSON number→string flip risk Critic 2 flagged does not apply here; migrate the 3 curated YAMLs. |
| 7 | Per-field provenance/confidence | **Reject; one `BasinSource(CURATED \| PARSED_PROSE)` per basin** | Carries the only honesty signal that pays rent (hand-verified vs prose-scraped) without a second provenance system next to facility-level `Provenance`. |

## Design (signature altitude)

New/changed types. Plain `| None` unless noted. Every field annotated with **source** and
**static** (stored in gold) vs **live** (query-time only).

### `domain/models.py` — `Basin` gains physical attributes (flat, five fields)

```python
class BasinKind(Enum):                     # static — parsed from infrastruktur prose
    LAP = "lap"                # Schwimmerbecken
    NON_SWIMMER = "non_swimmer"  # Nichtschwimmerbecken
    DIVING = "diving"          # Sprung-/Tauchbecken
    VARIO = "vario"            # Variobecken (Hubboden)
    TEACHING = "teaching"      # Lehrschwimmbecken
    CHILDREN = "children"      # Kinderbecken
    OUTDOOR = "outdoor"        # Aussenbecken
    OTHER = "other"

class BasinSource(Enum):
    CURATED = "curated"        # hand-verified YAML
    PARSED_PROSE = "parsed_prose"  # extracted from infrastruktur free text

@dataclass(frozen=True, slots=True)
class Dimensions:
    length_m: Decimal          # fractional in prose (16.66)
    width_m: Decimal | None = None

@dataclass(frozen=True, slots=True)
class Basin:                   # CHANGED
    basin_id: BasinId
    name: str
    rules: tuple[ScheduleRule, ...]
    exceptions: tuple[ScheduleException, ...] = ()
    kind: BasinKind = BasinKind.OTHER          # NEW  static
    dimensions: Dimensions | None = None       # NEW  static (replaces length_m: int|None)
    lanes: int | None = None                   # NEW  static  "(6 Bahnen)"
    nominal_temp_c: Decimal | None = None      # NEW  static  "28°C" (design temp, NOT live)
    physical_source: BasinSource = BasinSource.CURATED  # NEW
```

### `domain/models.py` — non-swim `Feature`s + `Facility` additions

```python
class FeatureKind(Enum):       # static
    SAUNA = "sauna"; STEAM_BATH = "steam_bath"; WELLNESS = "wellness"
    SLIDE = "slide"; HOT_TUB = "hot_tub"

@dataclass(frozen=True, slots=True)
class Feature:
    kind: FeatureKind
    name: str
    hours: tuple[ScheduleRule, ...] = ()   # reuses the resolver → "sauna open now?"
    surcharge_chf: Decimal | None = None   # "Eintritt Fr. 10.-"
    temp_c: Decimal | None = None
    note: str = ""

# Facility (additions)
    website: str | None = None                     # NEW  static (WFS www)
    features: tuple[Feature, ...] = ()             # NEW  static
    lockers: tuple[LockerOption, ...] = ()         # NEW  static
```

### `domain/lockers.py` (new) — orthogonal cost axes, honest to the rows

```python
class LockerCategory(Enum):
    WARDROBE = "wardrobe"      # Garderobenkasten
    VALUABLES = "valuables"    # Wertsachenfach
    LAUNDRY = "laundry"        # Wäschefach

class LockerMechanism(Enum):
    COIN = "coin"; KEY = "key"; TOKEN = "token"; WRISTBAND = "wristband"; OTHER = "other"

@dataclass(frozen=True, slots=True)
class LockerOption:            # static — pool page rows
    category: LockerCategory
    fee_chf: Decimal | None = None       # usage cost; None = free to use
    deposit_chf: Decimal | None = None   # refundable Pfand
    period: str | None = None            # "1 Jahr", "Saison" — free text, not parsed
    mechanism: LockerMechanism | None = None  # usually None (unstated)
    raw: str = ""                        # exact source row, for audit/reparse
```

Maps every real row: `gratis, plus Depot Fr. 5.–` → `(fee=None, deposit=5)`;
`Wäschefach (1 Jahr) Fr. 400.–` → `(fee=400, period="1 Jahr")`;
`Badetuch Fr. 3.–, plus Depot Fr. 20.–` → `(fee=3, deposit=20)`.

### `domain/access.py` — one new arm

```python
@dataclass(frozen=True, slots=True)
class AdultsOnly:              # school-pool public windows restricted to adults
    min_age: int = 18
    note: str = ""

type SessionAccess = (
    PublicSwim | LaneSwim | FamilyTime | WomenOnly | SeniorsOnly
    | SchoolReserved | ClubReserved | AdultsOnly       # <- NEW
)
```
School pools stay ordinary `Basin`s: `SchoolReserved` for school time, `PublicSwim`/
`AdultsOnly` scoped `SCHOOL_TERM`/`SCHOOL_HOLIDAY` for public windows. **No new resolver,
scope, or window type** — the existing `resolve_basin` + `eligibility` already handle it.

### `domain/query.py` — live occupancy as an explainable, query-time union

```python
@dataclass(frozen=True, slots=True)
class LiveOccupancy:
    reading: Occupancy                 # existing raw reading (people/percent/capacity)
    age: timedelta                     # now - reading.measured_at, computed at attach time
    @property
    def is_stale(self, limit: timedelta = timedelta(minutes=10)) -> bool:
        return self.age > limit

@dataclass(frozen=True, slots=True)
class OccupancyUnavailable:
    reason: str                        # "provider offline" | "no crowdmonitor key" | describe(err)

type OccupancyResult = LiveOccupancy | OccupancyUnavailable

# SwimOption.live_occupancy: OccupancyResult | None
#   None  = not requested (query.at is a future time, not ~now)
#   LiveOccupancy / OccupancyUnavailable = requested and resolved
```

Occupancy is **live-only**: it lives in `query.py`, is never imported into `models.py` or the
codec, and is attached only when `query.at ≈ now`, keyed by `identity.crowdmonitor_keys`.
Provider port (errors-as-values), added under `providers/` or `apps/web/services/ports.py`:

```python
class OccupancyProvider(Protocol):
    def read(self, keys: tuple[str, ...]) -> Result[Occupancy, ProviderError]: ...
```

`find_swim_options(..., occupancy: OccupancyProvider | None = None)`.

## Data-source & static/live map

| Fact | Source | Static (gold) / Live | Notes |
|------|--------|----------------------|-------|
| Basin kind, dimensions, lanes, nominal_temp_c | WFS `infrastruktur` prose | **static** | partial; `physical_source = PARSED_PROSE` |
| Features (sauna/steam/slide) + hours/surcharge | `infrastruktur` + pool page | **static** | |
| Lockers (fee/deposit/period/mechanism) | pool-page rows | **static** | mechanism usually unknown → `None` |
| `AdultsOnly`/public school windows | school-pool timetable | **static** | via existing schedule model |
| Water **nominal** temp | prose ("28°C") | **static** | a target, not a measurement |
| **Live occupancy** (people/percent) | CrowdMonitor service (websocket-ish, vendor countee) | **LIVE** | dedicated provider; ToS check first; **never** in gold |
| Website URL | WFS `www` | **static** | on `Facility` (catalog already has it too) |

## Serialization / codec impact (`boundary/curated_dto.py`, `boundary/mapping.py`, `storage/codec.py`)

- `BasinDTO`: add `kind: _BasinKind (Literal)`, `dimensions: DimensionsDTO | None`,
  `lanes: int | None`, `nominal_temp_c: Decimal | None`, `physical_source: _BasinSource`;
  **remove** `length_m` (migrated into `dimensions`). New `DimensionsDTO`. `Decimal` already
  round-trips as a JSON string, so temps/dims follow the price pattern.
- `StoredFacilityDTO`/`FacilityDTO`: add `website: str | None`, `features: list[FeatureDTO]`,
  `lockers: list[LockerOptionDTO]`. New `FeatureDTO`, `LockerOptionDTO` (`extra="forbid"`).
- `AccessDTO` discriminated union: add `AdultsOnlyDTO {type:"adults_only", min_age, note}`;
  extend `access_from_dto`/`access_to_dto` (both `assert_never`).
- **No DTO for `Occupancy`/`LiveOccupancy`/`OccupancyUnavailable`** — live-only.
- `mapping.py`: add `basin` field mappers, `feature_*`, `locker_*`, `dimensions_*`, and the
  `AdultsOnly` access arm.
- Extend the codec round-trip test to cover the new fields.

## Correctness traps (from critics — do not skip)

1. **`ACCESS_TYPES` silent gap.** Adding a `SessionAccess` arm is compile-enforced at the 4
   `match`/`assert_never` sites but **not** in the `ACCESS_TYPES` tuple. Add a test:
   `{type(a) for a in ACCESS_TYPES}` must equal all `SessionAccess` members.
2. **Occupancy staying out of gold is only structural.** Add a regression guard:
   `assert "occupancy" not in codec.dumps(facility)` (and never attach occupancy to
   `Facility`/`Basin`).
3. **`Dimensions` migration.** Convert the 3 curated pool YAMLs' `length_m: 50` → a
   `dimensions: {length_m: "50"}` (Decimal). Grep for any `basin.length_m ==` int comparison
   first (there are none in logic today — display only). No committed gold to regenerate.
4. **Prose parsing is partial.** Do not assert every basin has lanes/temp; leave `None`. Mark
   `physical_source = PARSED_PROSE` so a UI can caveat "auto-extracted".
5. **Reject `Fact[T]`** — do not reintroduce per-field tri-state/confidence.

## Query-surface & UI impact

- `SwimOption` gains `basin_kind: BasinKind`, `lanes: int | None`, `water_temp_c: Decimal |
  None` (from the basin), and `live_occupancy: OccupancyResult | None`.
- `AdultsOnly` flows through `eligibility` → `EligibilityResult` and the `/access-types` legend.
- Facility-level `website`, `features`, `lockers`, and per-basin physical belong on a
  **facility-detail** view (`/pools/{id}` or an expanded `/pools` row), **not** on every
  per-session `SwimOption` (avoid fanning static facility data across session rows).

## Out of scope

- Any UI work beyond the query surface (facility-detail rendering is a later plan).
- Per-field provenance/confidence (`Fact[T]`) — rejected, see Decisions #1/#7.
- CrowdMonitor scraping without a ToS check recorded in `data/sources.md` first.
- Re-scraping infrastructure beyond the new `infrastruktur` prose parser.

## Slices

### S1 — Physical basins (model + codec + YAML migration + prose parser)

- **Goal**: `Basin` carries kind/dimensions/lanes/nominal-temp/source, round-trips
  through the codec, and an `infrastruktur` prose parser extracts partial physicals.
- **Touches**: `domain/models.py` (`BasinKind`, `BasinSource`, `Dimensions`, `Basin`),
  `boundary/curated_dto.py` + `mapping.py` + `storage/codec.py`,
  `providers/infrastruktur.py` (new), `data/pools/*.yaml` (3 files, `length_m` →
  `dimensions`), `domain/query.py` (`SwimOption.basin_kind/lanes/water_temp_c`).
- **Acceptance**:
  - Codec round-trip test covers every new field; no `length_m` reference remains.
  - Parser test: the real sample prose ("Schwimmerbecken 50 x 15 m (6 Bahnen) 28°C,
    Nichtschwimmerbecken 10,5 x 7 m 30°C, …") yields the expected partial basins
    (fractional dims as `Decimal`, missing facts stay `None`,
    `physical_source=PARSED_PROSE`).
  - `make qa` green.
- **Depends on**: —

### S2 — Features + lockers (facility-level statics)

- **Goal**: `Facility` carries `website`, `features`, `lockers`; all three round-trip
  through the codec; curated YAML can express them.
- **Touches**: `domain/models.py` (`FeatureKind`, `Feature`), `domain/lockers.py` (new),
  DTO/mapping/codec, curated YAML schema (+ at least one real curated example),
  facility-detail query function (not UI).
- **Acceptance**: locker mapping test covers the three real-row shapes from the Design
  (free+deposit / fee+period / fee+deposit); feature hours reuse `ScheduleRule` and
  resolve via the existing resolver ("sauna open now?" test); codec round-trip extended;
  `make qa` green.
- **Depends on**: S1 (shares DTO/codec surface).

### S3 — AdultsOnly access arm + school-pool proof case

- **Goal**: `AdultsOnly` is a first-class `SessionAccess` arm flowing through
  eligibility, with a curated school-pool public-window proof case.
- **Touches**: `domain/access.py`, the 4 `match`/`assert_never` sites, `AccessDTO`
  union + mapping, one curated school-pool YAML entry.
- **Acceptance**: `ACCESS_TYPES` completeness test (`{type(a) for a in ACCESS_TYPES}` ==
  all `SessionAccess` members) — the trap from the critics; eligibility test: a child
  querying an `AdultsOnly` window is rejected with the right reason; `make qa` green.
- **Depends on**: — (independent of S1/S2).

### S4 — Live occupancy (provider port + query-time attach)

- **Goal**: `find_swim_options` can attach `LiveOccupancy | OccupancyUnavailable` from
  an `OccupancyProvider` port when querying ~now.
- **Touches**: `domain/query.py` (`LiveOccupancy`, `OccupancyUnavailable`,
  `OccupancyResult`, `SwimOption.live_occupancy`), provider port + fake in tests;
  real CrowdMonitor adapter ONLY if the ToS check recorded in `data/sources.md` allows.
- **Acceptance**: attach logic tested with a fake provider (now vs future query;
  provider error → `OccupancyUnavailable(reason=describe(err))`); the anti-leak guard
  (`"occupancy" not in codec.dumps(facility)`); staleness derived, not stored;
  `make qa` green.
- **Depends on**: S1 (SwimOption surface).

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|
| 2026-07-19 | S1 | done | parser shape (see Decisions); YAML migration also added `kind:` | depth-phrase misread risk; parser unwired; mapping-table parity untested | yes |
| 2026-07-19 | S2 | done | TOKEN→CHIP rename; resolve_hours extraction; FeatureStatus/FacilityDetail shapes (see Decisions) | facility_detail uncalled outside tests; Feature has no exceptions axis; coverage ratchet 91→93 possible (owner call) | no |
| 2026-07-19 | S3 | done | REPRESENTATIVE_ACCESS derivation (plan's literal test was impossible — see Decisions); test count-bumps 3→4 pools | aemtler timetable plausible-but-unverified (marked in file); eligibility/access_info CC 11 and rising per arm; duplicate-representative gap (one-line assert) | yes |

## Decisions & divergences

Substantive choices made during implementation, with the why. Each entry dated.

- **2026-07-19 / S1 — parser returns `ParsedBasinPhysical`, not `Basin`.**
  `parse_infrastruktur(text) -> tuple[ParsedBasinPhysical, ...]` (provider-local
  record) + `apply_physicals(basin, parsed)` which enriches a scheduled `Basin`
  and stamps `PARSED_PROSE`. Reason: `Basin` requires `basin_id` + schedule
  rules the prose cannot supply; fabricated schedule-less Basins could leak
  "always closed" rows into the resolver. Parser is total (returns a tuple,
  not `Result`) matching the `parse_notices` precedent. Critic reviewed and
  approved the divergence.
- **2026-07-19 / S1 — critic suggestions recorded as follow-ups** (tech debt,
  not blocking): (1) enum-parity test `set(_BASIN_KIND_TO) == set(BasinKind)`
  in `mapping.py` — closes the same trap class as the `ACCESS_TYPES` test;
  (2) depth-word guard (`Tiefe|tief`) + real-WFS fixture when the parser gets
  wired to the pipeline. Also discovered: `geo_sport._clean` strips `;` from
  descriptions — pipeline wiring must feed the parser the UNCLEANED
  `infrastruktur` field.
- **2026-07-19 / S2 — `LockerMechanism.TOKEN` renamed `CHIP = "chip"`.** Ruff
  S105 flags `TOKEN = "<string>"` as a hardcoded credential; noqa and lint-config
  edits are gate-weakening and forbidden. Critic reproduced the S105 firing
  experimentally and approved the rename. Wire value is `"chip"`.
- **2026-07-19 / S2 — `resolve_hours` extracted in resolver.py** (outside S2's
  touches, flagged): pure parameter-threading refactor so `Feature.hours`
  resolve through the SAME code path as basins (`resolve_basin` delegates,
  behavior unchanged — critic diff-verified). Facility closures shut features
  too, by construction.
- **2026-07-19 / S2 — facility-detail query shapes invented** (plan gave no
  signature): `FeatureStatus.open_at_query_time: bool | None` — tri-state,
  unknown-hours ≠ closed, per house rule. `FacilityDetail` mirrors `SwimOption`
  field style.
- **2026-07-19 / S2 — S1 debt repaid**: `test_token_tables_cover_their_enums`
  covers ALL mapping token tables including S1's `_BASIN_KIND_TO`/`_BASIN_SOURCE_TO`.
- **2026-07-19 / S3 — trap #1's literal test was impossible; closed better.**
  `ACCESS_TYPES` holds `AccessInfo` records, not access instances, so the
  plan's `{type(a) for a in ACCESS_TYPES}` could never work. Implemented:
  `REPRESENTATIVE_ACCESS: tuple[SessionAccess, ...]` with
  `ACCESS_TYPES = tuple(access_info(a) for a in REPRESENTATIVE_ACCESS)` (derived,
  no drift channel) + completeness test deriving union members from
  `get_args(SessionAccess.__value__)`. Critic CONFIRMED experimentally: a new
  union arm omitted from `REPRESENTATIVE_ACCESS` fails the test.
- **2026-07-19 / S3 — proof-case data honesty**: `aemtler.yaml` identity/geo
  from in-repo `catalog.json`; timetable marked CURATED/ILLUSTRATIVE, verify
  against stadt-zuerich.ch before relying; no basin physicals invented.

## Rejected (record so we don't relitigate)

- `Fact[T] = Present | Absent | Unknown` + `Confidence` on every parsed field — gold-plating;
  quadruples codec surface for a distinction the UI collapses. Kept only `BasinSource`.
- Sauna as a `BasinKind` — would leak non-swim rows into swim results.
- Lockers as a `Free | Deposit | Rental | Paid` tagged union — cannot represent
  free-usage-plus-deposit or a rental period simultaneously.
- Stored `freshness` enum + `age_s` on occupancy — derive from `measured_at` instead.
- `length_m: int → Decimal` as a standalone change — do it only bundled into `Dimensions`.

## Summary

Written when the plan reaches `done`; then distilled into
`docs/summaries/rich-pool-domain.md`.
