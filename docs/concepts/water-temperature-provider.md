---
type: concept
name: water-temperature-provider
status: implemented
updated: 2026-07-26
links: ["[[2026-07-25-water-temperature-provider-plan]]", "[[data-layer-architecture]]", "[[fastapi-service-integration]]", "[[basin]]"]
---

# Water-temperature provider (Baditicker) — and the static-vs-live decision

> Sketch feeding a future `/dev:plan`. Prompted by "why does Freibad Heuried show no
> temperature?" and the scope correction that **all** Zürich pools (indoor + outdoor) are in
> scope, not indoor-only. See [[project scope]] and `data/sources.md`.

## The gap

`Basin.measured_temp_c` is plumbed end-to-end — DTO (`curated_dto`), mapping, gold codec,
`/pools/{id}` API, and the UI honesty-note (`detailpanel.js` renders "measured" vs "nominal
(design)") — but **nothing writes it**. It is a wired socket with no plug. `nominal_temp_c`
(the design target parsed from WFS prose) is separate and stays static.

## The source — facts

`GET https://www.stadt-zuerich.ch/stzh/bathdatadownload` (Baditicker, OGD, **open, no usage
restrictions** — unlike CrowdMonitor, no ToS gate). One call returns all ~27 city baths. Per
bath (XML → record):

```
{ title, temperatureWater, poiid, dateModified, openClosedTextPlain, urlPage, pathPage }
```

- `temperatureWater` — number, or **empty** when not measured (off-season / before opening).
- `poiid` — stable external id (Freibad Heuried = `fb012`) → a natural `pool_xref` key.
- `dateModified` — the reading's timestamp ("Sa., 25.07.2026 20:39"); parse to tz-aware
  `Europe/Zurich`. **This is the crux: the value carries its own age.**
- `openClosedTextPlain` — live "offen"/"geschlossen".
- **Covers indoor Hallenbäder too** (City, Oerlikon, Bläsi, Bungertwies, Leimbach,
  Käferberg) — so one feed fills `measured_temp_c` for the *whole* curated roster, not just
  outdoor. Verified live 2026-07-25: Heuried `fb012` = 23 °C, `geschlossen`.
- Caveat: hand-measured by lifeguards during operation (~May–Sept). Off-season → empty.

## Decision: live attach, NOT a static gold column

Two options:

- **A — static column.** A `refresh-temp` command re-stamps `measured_temp_c` into gold
  (like `scrape-gold`/`scrape-lanes` layering). Simplest, field already exists, zero
  request-time cost. **But** it bakes in staleness with *no freshness signal*: a gold value
  has no timestamp, so the UI cannot distinguish "measured 5 min ago" from "a frozen July
  temp shown in December". To be honest you'd have to add `measured_at` + staleness reasoning
  to gold — i.e. re-implement the live model in the wrong layer.
- **B — live attach (recommended).** A `TemperatureProvider` **port**, read at request time
  when `at ≈ now`, returning a freshness-bearing `LiveTemp(reading, age)` exactly mirroring
  `LiveOccupancy(reading, age)` in `domain/query.py`. Gold stores only the `baditicker`
  **keys** (`pool_xref` namespace `baditicker`), never the reading — same discipline as the
  "occupancy readings never persisted" regression guard.

**Granularity (refined in [[2026-07-25-water-temperature-provider-plan]]).** Baditicker is
**facility-granular** (one `temperatureWater` per bath) but `Basin.measured_temp_c` is
**per-basin**. So the live reading surfaces as a **facility-level** `live_water_temp` field on
the pool detail — it does NOT overwrite each basin's `measured_temp_c`. Per-basin
`nominal_temp_c` (design target) stays; the live facility temp is additive and labelled.

**Why B.** The decisive fact is that the reading is *timestamped and seasonal*. A "current
water temperature" without a freshness signal is a lie waiting to happen — the exact reason
the project already refuses to persist occupancy. B reuses machinery the codebase already
committed to and guards, and keeps gold deterministic/rebuildable (no time-varying data in
it). The `measured_temp_c` gold column stays only for a genuinely-curated/authored measured
value (rare); the *live* reading flows through the port.

### Shape (mirrors the occupancy scaffold in `query.py`)

```python
# domain/query.py  (live-only; never imported into models.py or the gold codec)
@dataclass(frozen=True, slots=True)
class TempReading:                 # adapter NEVER constructs a PoolId — keyed by poiid
    measured_at: datetime          # tz-aware Europe/Zurich (guard in __post_init__)
    celsius: Decimal | None        # None when the feed cell is empty (measured nothing yet)
    is_open: bool                  # from openClosedTextPlain
    source: str                    # "baditicker"

@dataclass(frozen=True, slots=True)
class LiveTemp:
    reading: TempReading
    age: timedelta                 # now - measured_at, computed at attach
    def is_stale(self, limit=timedelta(hours=6)) -> bool: ...   # coarser than occupancy's 10 min

TempResult = LiveTemp | TempUnavailable            # TempUnavailable(reason=...)

class TemperatureProvider(Protocol):
    def read(self, poiid: str) -> Result[TempReading, ProviderError]: ...

# read_temperature(provider, identity, now): no key -> TempUnavailable("no baditicker key");
# empty cell -> LiveTemp(celsius=None); Err -> TempUnavailable(describe(err)). The PoolId
# comes from `identity`, never from the adapter.
```

`find_swim_options(..., occupancy=None, temperature=None)` gains a second optional port; the
same `at ≈ now` gate applies (a *future* date's water temp is unknowable, so no attach — same
rule as occupancy). `SwimOption`/the `/pools` basin view surface `LiveTemp | TempUnavailable`.

### Pipeline touch-points (per [[data-layer-architecture]] junior playbook)

1. `providers/baditicker.py`: `fetch(client) -> Result[bytes, ...]` + `parse(bytes) ->
   Result[tuple[Extract,...], ProviderError]`, each `Extract = (Xref("baditicker", poiid) |
   Name(title), TempReading-payload)`. **Never constructs a PoolId.** Empty `temperatureWater`
   → `celsius=None`, not an error. Unreadable feed → `SchemaMismatch`/`ParseError`.
2. Crosswalk: add `baditicker` `pool_xref` rows (`fb012 → freibad-heuried`, …). Unmatched
   poiids = loud Err / inspectable list, never guessed.
3. **No compose/materialize/gold change** for the reading (it is never stored) — only the
   xref keys land in gold at build time.
4. Composition root wires a real `BaditickerProvider` (network) into `app.state`; a fake in
   tests. Fail-open: provider error → `TempUnavailable`, never an exception (errors-as-values).

## Deliberately out of scope (flagged, not built)

- **Unifying the two live ports.** Occupancy + temp + live open/closed are all "`~now`
  facility readings keyed by `pool_xref`". A single live-readings seam is cleaner but a bigger
  refactor; ship a parallel `TemperatureProvider` first, consolidate later.
- **Live open/closed override.** The feed's `openClosedTextPlain` could cross-check the
  schedule resolver ("schedule says open, badi reports geschlossen"). Interesting, but scope
  creep — the resolver already answers open/closed from the curated schedule.
- **Occupancy** stays blocked on the countee.ch/ASE ToS check (`data/sources.md`); temp does
  **not** (Baditicker is OGD-open), which is why temp is the cleaner first slice.
