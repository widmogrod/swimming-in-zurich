# Plan — Rich pool domain model (lanes, basins, temps, lockers, occupancy, notices, website)

Status: **Design approved-for-implementation pending owner sign-off.** Not yet implemented.
Produced by: 2 design sub-agents (purist + pragmatic) → 2 critic agents (YAGNI/complexity +
type-rigor/serialization) → this synthesis.

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

## Final model (synthesized)

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

## Implementation phases (suggested)

1. **Physical basins** — `BasinKind`, `Dimensions`, `lanes`, `nominal_temp_c`, `BasinSource`
   + `infrastruktur` prose parser (new `providers/infrastruktur.py`, returns partial data) +
   codec + curated-YAML migration. Surface temp/lanes/kind in `SwimOption`.
2. **Features + lockers** — `Feature`, `LockerOption` + pool-page scrapers + facility-detail
   API/UI.
3. **`AdultsOnly` + school public windows** — access arm (+ `ACCESS_TYPES` test) + curate/scrape
   a school pool's public hours as the proof case.
4. **Live occupancy** — investigate the CrowdMonitor endpoint (ToS check in `data/sources.md`
   first), build `OccupancyProvider`, `LiveOccupancy`/`OccupancyUnavailable`, attach at query
   time, `dumps` guard. Real-time, out of gold.

## Rejected (record so we don't relitigate)

- `Fact[T] = Present | Absent | Unknown` + `Confidence` on every parsed field — gold-plating;
  quadruples codec surface for a distinction the UI collapses. Kept only `BasinSource`.
- Sauna as a `BasinKind` — would leak non-swim rows into swim results.
- Lockers as a `Free | Deposit | Rental | Paid` tagged union — cannot represent
  free-usage-plus-deposit or a rental period simultaneously.
- Stored `freshness` enum + `age_s` on occupancy — derive from `measured_at` instead.
- `length_m: int → Decimal` as a standalone change — do it only bundled into `Dimensions`.
