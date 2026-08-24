---
type: plan
status: done             # draft -> approved -> in-progress -> done
created: 2026-08-23
feature: native-ios-app
branch: plan/native-ios-app
worktree: .claude/worktrees/plan-native-ios-app
base_branch: feat/ios
gates:
  qa: full               # THREE chains, each run only when a slice touches its tree:
                         #  python : ruff check -> ruff format --check -> mypy -> pytest -> crap.py
                         #  ts     : npm --prefix apps/web/static/js run qa
                         #  swift  : see `swift_chain` below
  swift_chain: "cd apps/ios && swift format lint --strict --recursive Sources Tests App && swift build && swift test --enable-code-coverage && uv run python ../../scripts/crap_swift.py && xcodebuild -project App/SwimZH.xcodeproj -scheme SwimZH -destination 'platform=iOS Simulator,name=iPhone 17' test"
  swift_chain_notes: |
    Runner is macos-latest. The existing .github/workflows/qa.yml job is ubuntu-latest and
    CANNOT build SwiftUI; S2 adds a separate `ios-qa` job pinned to macos-latest.
    `swift format` ships with Xcode 16 — no third-party linter is added.
    `-project App/SwimZH.xcodeproj` is REQUIRED: `xcodebuild` with no -project searches the
    cwd, which holds Package.swift and no .xcodeproj. The `SwimZH` scheme must be SHARED
    (Xcode > Manage Schemes > Shared) or xcodebuild cannot see it.
    Order is load-bearing, as in the other two chains: crap_swift reads the coverage that
    `swift test --enable-code-coverage` writes, so tests MUST run first.
    The final step is `test`, not `build`: `swift test` is SwiftPM-only and cannot import the
    app target, so the app-hosted metric test (S2b acc 3) has no other runner. Everything that
    CAN be a pure `SwimZHKit` test IS one — `xcodebuild test` exists for the metric target and
    the compile check, not as a licence to push logic into views.
    NOT in the chain: `xcodebuild -exportArchive`. It needs a signing identity and profile,
    which CI has not got; see S2b acc 4 for the unsigned size proxy used instead.
    The lint covers `App` too, not just `Sources Tests`: the app target is where S3a and S3b
    grow the view layer, and an unlinted target drifts silently (widened after S2's review).
    Destination is `iPhone 17`, not `iPhone 16`: the installed iOS 26.5 runtime ships the
    iPhone 17 family (17, 17 Pro, 17 Pro Max, 17e, Air) and has no iPhone 16. A CI runner with
    a different device set must adjust this one string.
  review: adversarial    # critic subagent must find no blocking issues
  max_rounds: 2          # revise/retry rounds per gate before a slice is blocked
pause_after: []          # the user explicitly waived human review; see Decisions 2026-08-23
links:
  - "[[ios-resolved-export]]"
  - "[[gold-store]]"
  - "[[data-layer-architecture]]"
  - "[[session-access]]"
---

# Native iOS app over a pre-resolved SQLite export

## Intent (verbatim)

The user's own words, unedited. No agent may paraphrase, summarize, or
"clean up" this block. It is the anchor every later artifact is measured
against.

**2026-08-23**

> I would like to have this app as native iOS app; using modern swift UI; and embed sqlite with the pool (and only sqlite); so that it can offer all features that current app has but in iOS; it should also work with offline mode with few concesions/degradations. I will be updating and releasing app every week to make it up to date. Ultrathink

Two design choices were then put to the user as a two-option question and answered:

> **Where should the schedule logic live for iOS?** → "Bake answers in Python (Recommended)"

> **How does the app get fresh data each week?** → "Bundle + optional download (Recommended)"

A third message, after the first adversarial review round, added the non-functional requirements:

> lunch second review related to apple ui/ux desing must be delightful, iOS native, follow best guidelines for iOS26; be well tested; follow crap metric; use small amount of memory and CPU; be fast and responsive, preferably launch under 1s; and size without sqlite should be below few MB (can go up to 30MB); ultrathink

## Context

`gold.sqlite` stores schedule *rules*, not answers: 57 pools, 26 of them carrying 224
`ScheduleRule`s across their basins, plus seasons, closures and the `calendar` singleton. Turning
those into "what is open on 4 September" is the job of `domain/resolver.py` (166 lines) driving
`domain/calendar.py` + `domain/holiday.py`, whose output is then shaped by `domain/query.py`
(841 lines), `domain/access.py`, `domain/pricing.py` and `domain/lane_plan.py` — 2,055 lines across
those seven modules, inside a 3,076-line `domain/` package that iOS cannot run. `CLAUDE.md` names
the resolver "the correctness core".

Rather than reimplement that core in Swift and maintain two copies of it, the build gains one more
derived artifact: an **iOS export** ([[ios-resolved-export]]) — a projection of the gold store in
which every date inside a fixed forward horizon is *already resolved*. This keeps the
single-source-of-truth rule intact (gold remains the only source; the export is derived from it as
`data/catalog.json` is derived from the WFS) and reduces the Swift side to what genuinely cannot be
baked because it depends on the user: **eligibility** (gender/age vs `SessionAccess`), the **price
bracket** (age vs the tariff), and **distance** (lat/lon vs the pool).

Two facts worth pinning so a later reviewer does not cut real features. First, `lane_day` is **not**
made inert by CLAUDE.md's flat-scrape limitation: 7 basins carry parsed lane plans and a single
week's `/swim` answers carry 55 options with a `lane_day_view` (hallenbad-city, blaesi, bungertwies,
leimbach, kaeferberg, oerlikon ×2). Second, the answer shape is wider than options + statuses:
`QueryResult` also carries **notices** (`query.py:600`, `notice.active_on(day)`) and **warnings**
(`query.py:581` calendar coverage, `query.py:688` unverified holiday hours) — over a 131-day
horizon, 8 days carry notices and 2 carry warnings. Both are date-resolved, so both must be baked.

## Design (signature altitude)

### The seam: what is baked, what is runtime

| Depends on | Baked in Python | Computed in Swift |
|---|---|---|
| the date | resolver, calendar, holidays, seasons, closures, statuses, notices, warnings, lane day views, feature hours | — |
| the clock (time-of-day only) | — | `open_at_query_time`, the lane-availability/timeline derivations at an instant |
| the person | — | `eligibility(access, person)`, `priceFor(prices, person)` |
| the place | — | `haversineKm`, radius filter, sort |
| the network | — | live occupancy + water temperature (degrade when absent) |

**Invariant E1 — no date-dependent RULE runs on the client.** Weekday scope, school-term scope,
seasons, holiday policy, exceptions and closures are all resolved in Python. Comparing the wall
clock against a *baked* time window is not a date rule and stays in Swift — that is exactly what
`open_at_query_time` and the lane derivations are (`query.py:501-540`), and baking them per minute
would be absurd. If Swift ever needs to ask whether a date is a school holiday, the seam is broken.

**Invariant E2 — the horizon matches the web's honesty, not a stricter one.**
`ZurichCalendar.covers()` is year-bounded (`calendar.py:83`, `known_years: [2026]`), but
`find_swim_options` does **not** withhold answers outside coverage: it appends a warning and serves
(`query.py:581-585` — 2027-01-05 returns 22 real options plus the warning). The export therefore
bakes a fixed **400-day** horizon from the build date regardless of calendar coverage, and carries
the identical coverage warning on every out-of-coverage date. The iOS client renders that warning;
it never substitutes a "we don't know" blank for answers the web would give.

Measured over a 400-day sweep from 2026-08-23: **0 exceptions**, 11,927 options, 16,924 statuses,
9 notices, 271 warnings. Unseeded 2027 dates degrade *upward*, not badly — 32.1 options/day vs 25.2
in 2026 — because school-holiday scope collapses to term-time when the year is unseeded, which is
precisely what the carried `calendar_coverage` warning names.

**Operational obligation, and it is overdue on day one, not prospective**: `known_years` is `[2026]`,
so **269 of the first export's 400 days (67%) already fall outside coverage**. Seeding 2027 in
`data/calendar/zurich.yaml` is a prerequisite for a credible first release, not a later chore. S1
acceptance 4 counts the warned days so the number is visible at every build.

### The export

New module `src/swimzh/etl/ios_export.py`, driven by a new CLI command (there is no
`[project.scripts]` entry in `pyproject.toml`; the module form is the real invocation):

```
uv run python -m swimzh.cli export-ios --db gold.sqlite --out ios.sqlite [--days 400]
```

```python
@dataclass(frozen=True, slots=True)
class ExportReport:
    horizon_start: date
    horizon_end: date
    pools: int
    sessions: int
    day_rows: int
    notices: int
    warnings: int
    bytes: int
    content_hash: str

def export_ios(
    conn: sqlite3.Connection, out: Path, *, today: date, days: int = 400
) -> Result[ExportReport, ProviderError]
```

It takes the **connection**, not a `GoldRepository`: the repo exposes only `load_all`/`get`/`count`
over `facility_doc` (`sqlite_repo.py:214-238`), while the export also needs `load_calendar`
(`:205`), `load_roster` (`:159`) and `load_alias_rows` (`:140`) — module functions over the
connection. Without the roster, `_schedule_less_statuses` (`query.py:678`) yields **0** rows instead
of 5,881 over a 131-day horizon, i.e. the `day` table would be empty for every schedule-less pool.
Returning `Result[..., ProviderError]` from a network-free ETL function matches existing peers
(`etl/silver.py:106`, `build/reconcile.py:159`). Written through `storage/atomic.py`'s
`atomic_swap`, like every other store this project emits.

Schema (`STRICT` throughout, mirroring gold's conventions):

```
meta(key TEXT PRIMARY KEY, value TEXT)
    -- schema_version, built_at, horizon_start, horizon_end, gold_valid_as_of, content_hash

pool(pool_id PK, name, kind, address, lat, lon, url, description, phone,
     freshness, admission_state, prices_doc TEXT, source TEXT, curated INT,
     valid_as_of, last_admission_before_s INT, operating_season TEXT)
    -- `operating_season` is NOT derivable from the day rows: 13 of 57 pools carry one
    --   (measured), and `FacilityDetailOut` renders it.
    -- `source`/`curated` live HERE, not on `session`: SwimOption.provenance is the
    --   facility's (`query.py:544`), so per-session copies would be ~10k duplicated
    --   cells and a second place to drift.

pool_basin(pool_id, basin_id PK, name, kind, length_m, width_m, lanes,
           nominal_temp_c, measured_temp_c, diving_platforms_m TEXT,
           physical_source, lane_plan_url)
    -- all 12 `BasinOut` fields (apps/web/api/pools/model.py:96-112), incl. the
    --   `physical_source` honesty caveat ("curated" vs "parsed_prose").
pool_locker(pool_id, ord INT, doc TEXT)
pool_rental(pool_id, ord INT, doc TEXT)
pool_feature(pool_id, feature_key, doc TEXT, PRIMARY KEY(pool_id, feature_key))
    -- `doc` carries the feature's own `hours` rules AND, when it has any, its resolved
    --   per-date windows + closed_reason. There is deliberately NO `feature_day` table:
    --   measured, all 9 features across all 57 pools have `hours=()`, so `_feature_status`
    --   (query.py:744) returns `schedule=None` for every one and a date-keyed table would
    --   ship 0 rows over a 400-day sweep. If a feature with hours ever appears, the export
    --   adds the per-date windows inside `doc` — same table, no schema change.

day(pool_id, date TEXT, status TEXT, detail_code TEXT, closure_code TEXT,
    detail_params TEXT, PRIMARY KEY(pool_id, date))
    -- the four-state StatusOut vocabulary: closed | awaiting_scrape | no_source |
    --   open_unscheduled. A pool-day with sessions has no `day` row.

session(pool_id, date TEXT, basin_id, basin_name, length_m, lanes,
        start TEXT, end TEXT, access_kind TEXT, access_params TEXT, weather TEXT)
    -- access_kind is the SessionAccess class name; access_params its fields
    --   (min_age, club, note) as JSON.

day_notice(pool_id, date TEXT, text TEXT)
day_warning(date TEXT, code TEXT, params TEXT)
    -- code ∈ {calendar_coverage, holiday_hours_unverified}; params carries the year or
    --   the pool-name list, so the client renders it in its own language.

lane_day(basin_id, weekday INT, lane_count INT, strips TEXT,
         unresolved_lanes TEXT, confidence TEXT, PRIMARY KEY(basin_id, weekday))
    -- `unresolved_lanes` + `confidence` are LOAD-BEARING, not decoration:
    --   `lane_availability_at` derives `partial` from `PlanCoverage.unresolved_lanes`
    --   (lane_plan.py:159, :56-68), and `partial` is a rendered field on both
    --   `LaneAvailabilityOut` (swim/model.py:16) and `LaneTimelineSegmentOut` (:28).
    --   Without them S3b acceptance 3 is unsatisfiable.
    -- keyed by WEEKDAY, not date: a Belegungsplan is a weekly plan. Keying it by date
    --   would multiply the largest payload by ~400 for no new information.

alias(pool_id, norm)          -- search, from load_alias_rows
INDEX session_by_date(date, pool_id);  INDEX day_by_date(date, pool_id)
```

`price` is **not** a table: the tariff bracket depends on the person, so the pool's whole tariff doc
rides as `prices_doc` JSON and Swift picks the bracket, mirroring `domain/pricing.price_for`
(`pricing.py:57`).

### The Swift side

`apps/ios/` — a Swift Package (`SwimZHKit`, testable headlessly by `swift test`) plus a thin Xcode
app target that owns only the SwiftUI views. `Localizable.xcstrings` lives **in the package**, not
the app target, so `swift test` can assert against it without `xcodebuild`.

```swift
// SwimZHKit — pure, no UIKit, fully unit-tested
struct Store { init(path: URL) throws }                       // read-only SQLite via libsqlite3
func answer(on: Date, at: Date, for: Person, near: GeoPoint?, radiusKm: Double?) throws -> Answer
func eligibility(_ access: SessionAccess, _ person: Person) -> EligibilityResult   // port of access.py
func priceFor(_ prices: PriceDoc, _ person: Person) -> Admission                   // port of pricing.py
func haversineKm(_ a: GeoPoint, _ b: GeoPoint) -> Double                           // port of geo.py:17
```

`Answer` mirrors the **domain** `QueryResult` (`options` / `statuses` / `warnings` / `notices`,
`query.py:355`) — not the pydantic `AnswerOut` — so the two clients answer the same question in the
same shape. SQLite access is `libsqlite3` directly: no third-party *runtime* dependency, matching
"only sqlite". (`swift format` is dev tooling and ships with Xcode; it is not a dependency.)

**Eligibility parity is enforced, not hoped for.** `apps/web/tests/test_eligibility_ui_contract.py`
generates `apps/web/tests/fixtures/eligibility_contract.json` (440 cases, regenerated with
`SWIMZH_REGENERATE_ELIGIBILITY_CONTRACT=1`) and `eligibility.test.js` replays it in the browser.
Swift replays the identical file. **Gap being closed in S2**: the fixture's cases carry only
`{access, gender, age, allowed, code, ui}` and are drawn from `REPRESENTATIVE_ACCESS`
(`access.py:205-218`), so the *parameterised* arms — `SeniorsOnly.min_age` (`:45`),
`AdultsOnly.min_age` (`:64`), `GenderDiverse.min_age` (`:82`) — are not pinned today, even though
live data exercises them (53 `AdultsOnly(min_age=18)` options in the next 60 days). S2 extends the
generator to emit `access_params` per case; the browser test gains the same coverage for free.

### Reading a bundled SQLite safely (the finding that would have shipped a broken app)

**A WAL-mode database cannot be read from the app bundle at all.** Verified empirically: with the
file mode `0444` in a `0555` directory and no sidecars, `sqlite3_open_v2` returns **SQLITE_OK** and
the *first prepare* fails with `SQLITE_CANTOPEN` (14). WAL needs `-wal`/`-shm` sidecars, a writable
directory, or `immutable=1`; an iOS bundle offers none, and iOS enforces bundle read-only at
runtime. SQLite's own guidance is to convert before burning onto read-only media.

The export therefore finishes with a fixed, asserted sequence:

The export runs it through Python's own `sqlite3` module and a 4-byte read — no `sqlite3(1)` or
`xxd` as build-environment dependencies:

```
PRAGMA journal_mode=DELETE; VACUUM; ANALYZE; PRAGMA integrity_check;
unlink ios.sqlite-wal, ios.sqlite-shm    # a stale -shm survives the conversion
assert bytes[18:20] != b"\x02\x02"       # header write/read version
```

**What byte 18 actually proves.** Measured across all five journal modes: `delete`, `truncate`,
`memory` and `off` all write `0101`; only `wal` writes `0202`. So the assertion proves **not WAL** —
which is exactly the property that matters — and the plan says "not WAL" rather than over-claiming
"DELETE".

The byte assertion is not belt-and-braces: `PRAGMA journal_mode` **can fail silently**, returning
the original mode. `ANALYZE` writes `sqlite_stat1` into the file, so the planner has real statistics
on the device's first query — a free launch win. `VACUUM` also shrinks the file before bundling.

Opening: `SQLITE_OPEN_READONLY | SQLITE_OPEN_NOMUTEX | SQLITE_OPEN_URI` with
`file:...?immutable=1` (percent-encoded — container paths carry spaces and UUIDs). `PRAGMA
query_only` is the wrong tool; it does not make the database truly read-only.

**Concurrency.** Apple's SQLite is built `SQLITE_THREADSAFE=2` (multi-thread), **not** upstream's
serialized default, so a connection is not internally mutex-protected; and `OpaquePointer`'s
`Sendable` conformance is explicitly unavailable in the stdlib, so it cannot be papered over. The
handle lives inside an **actor** (the actor is the mutex, hence `NOMUTEX`), every method is a single
non-suspending unit (actors are reentrant), and no `sqlite3_stmt*` ever escapes — methods return
decoded value types. Two footguns pinned by tests: `sqlite3_open_v2` returns a handle **even on
failure** (close it on the error path or leak), and `sqlite3_bind_text` with `SQLITE_STATIC` and a
bridged Swift `String` is a **use-after-free** — always `SQLITE_TRANSIENT`.

**Memory.** Apple's build sets `DEFAULT_CACHE_SIZE=2000` — a *positive* value, i.e. 2000 pages ≈
**8 MB**, four times upstream's `-2000` (2 MB). Set `cache_size` explicitly rather than inheriting
either. And prefer `mmap`: SQLite's heap page cache is **dirty** memory and counts fully against the
footprint, while mmap'd read-only pages are **clean** and are excluded from it.

### The iOS 26 surface

Deployment target **iOS 26.0**. iOS 27 is in beta; Apple states apps already using Liquid Glass get
its refinements *"automatically… without even needing to recompile"*, so targeting 26 is correct and
nothing here is bet on 27. Note several APIs that read as "new" are older and available anyway:
`Tab`, `matchedTransitionSource`, `navigationTransition(.zoom(sourceID:in:))` are **iOS 18**;
`sensoryFeedback` and `symbolEffect` are **iOS 17**; `Canvas` and `TimelineView` are **iOS 15** and
gained nothing in 26.

**Adopt (the system does the design work):**
- `.searchable` **inline with content** — the HIG explicitly blesses this for *filtering*, which is
  what this app's search is.
- The floating filter bar via **`safeAreaBar(edge:)`**, not `safeAreaInset` and not `overlay`: it is
  the only one that extends the scroll edge effect under the bar. Do **not** paint our own glass.
- **`List`**, not `LazyVStack` — not for speed (both are lazy; at n=57 it is noise) but for
  `.swipeActions` and system row/section styling.
- The **zoom navigation transition** for row → detail (`matchedTransitionSource(id:in:)` +
  `.navigationTransition(.zoom(sourceID:in:))`). Both halves are required; it is not automatic.
- **`ScrollPosition` + `.scrollTargetBehavior(.viewAligned)`** for the day strip (bidirectional, so
  the centred chip is readable back), in preference to `ScrollViewReader`.
- `.sensoryFeedback(.selection, trigger:)` on day-chip changes.
- Semantic colors from an **Asset Catalog** — Apple's stated answer to hardcoding, and they resolve
  correctly inside `Canvas` via `GraphicsContext.environment`.
- `\.accessibilityDifferentiateWithoutColor`: the ribbon's thickness encoding is already a
  non-colour channel; lane categories add hatching, and red/green are never the two primary states.

**Deliberately do NOT:** apply `.glassEffect()` to the 57 ribbon rows — the HIG says *"Don't use
Liquid Glass in the content layer"*, and *"glass can not sample other glass"* makes nested glass
render inconsistently; custom nav or tab bars; custom fonts; hardcoded hex colours; a scroll edge
effect on the horizontal day strip (`\.scrollEdgeEffectHidden(for: .horizontal)`) — Apple: *"Scroll
edge effects aren't decorative"*; `.refreshable` while the store is bundle-only (it would be a lie);
carrying over the web's row-height maths (iOS 26 rows are taller with larger section corner radii).

**Accessibility size is a designed state, not a fallback.** At `dynamicTypeSize.isAccessibilitySize`
the day strip shows **fewer chips and scrolls** rather than shrinking them, inline ribbon labels
collapse to a legend, and a pool name is never truncated. Strip height and ribbon thickness are
`@ScaledMetric`.

**Two structural traps, both load-bearing:**

1. **`Canvas` has zero VoiceOver accessibility.** Apple states it twice: *"A canvas doesn't offer
   interactivity or accessibility for individual elements."* `accessibilityChildren(children:)` is
   therefore an **acceptance criterion**, not a nicety — and Apple's own documentation example for
   it is a Canvas bar chart. `.accessibilityCustomContent` carries the secondary facts.
   Corollary: hit-testing is ours too, so the time→x mapping is **one pure function** shared by the
   renderer, the gesture handler and the `accessibilityChildren` layout — three consumers of one
   truth, and ideal CRAP-gated logic.
2. **`if expanded { GanttView() }` directly inside a `ForEach` element defeats `List` laziness for
   all 57 rows.** An element resolving to a *variable* number of views forces List to build every
   row's body just to learn the identifiers (WWDC23 10160). The row and its optional Gantt are
   wrapped in an explicit `VStack` so the element always resolves to exactly one view.

**Canvas for the 57 ribbons; Swift Charts for the expanded per-lane Gantt.** Charts gives per-mark
VoiceOver free and documents `BarMark(xStart:xEnd:y:height:)` for Gantt charts — but there are
credible reports of 100% CPU and 50–150 ms hangs at 500–2000 points, and 57 live charts inside a
`List` is exactly that shape. The Gantt is one at a time and off the hot scroll path, so it gets the
free accessibility; the ribbons stay Canvas and pay for theirs explicitly.

### Non-functional budgets

Each budget names how it is measured and which slice owns it. **The harness is built in S2, not
retrofitted**: budgets that arrive last are budgets that are negotiated away.

| Budget | Target | Measured by | Gate |
|---|---|---|---|
| Cold launch to *data on screen* | < 1 s (Apple's own first-frame budget is 400 ms) | `OSSignposter` interval + MetricKit `extendLaunchMeasurement(forTaskID:)` so the DB load **counts** | **Device**, at the S2 and S3b pauses — not CI |
| Peak memory, list of 57 pools | < 100 MB | `XCTMemoryMetric` in an **app-hosted unit test** | CI, generous ceiling |
| Per-row view body | < 500 µs (Instruments' orange line) | Instruments, Long View Body Updates | Human, at the S3b pause |
| Ribbon CPU while visible | < 10% on the reference device | Instruments Time Profiler | Human, at the S3b pause |
| App size **excluding** the sqlite | ratchet at 4 MB, hard ceiling 30 MB | **unsigned proxy**: binary `__TEXT` (`size -m`) + bundled resources, minus the sqlite | CI |
| SQLite file size | 8 MB (S1) | file size | CI, tracked **separately** so a data refresh never masks a code regression |
| CRAP | `cc > 5 AND crap > 30` fails | `scripts/crap_swift` | CI |

Three of these are honest about what CI cannot do. **Launch time is not CI-gateable on a
simulator**: Xcode stores performance baselines per device configuration precisely because they do
not travel, and no published simulator-variance figure could be found. It is a device check at a
pause gate, with CI carrying only a generous ceiling. `XCTMemoryMetric` reports a **delta, not a
peak**, and returns meaningless values against an `XCUIApplication` because it measures the test
runner — hence "app-hosted unit test", never a UI test. And UI tests stay **out** of the blocking
gate: they need a booted simulator, dominate wall-clock, and test-plan-driven retry is
Apple-confirmed broken in Xcode 26+ (the workaround is `-retry-tests-on-failure` on the command
line).

**Why the size budget is not at risk, and why the gate is a proxy.** Measured: a stripped
hello-world SwiftUI binary is ~71 KB, and a synthetic 2,771-line app with 50 screens and 50 SQLite
query functions is ~127 KB — about 21 bytes per line of marginal code. The Swift runtime is not
embedded (iOS 12.2+ ships it). The app minus the database lands at **1–3 MB**; 30 MB is not remotely
in play, which is why the ratchet sits at 4 MB.

The *right* number to gate is the thinned compressed download — Apple is blunt that the `.app`,
`.xcarchive` and `.ipa` carry files users never receive. But it comes from
`xcodebuild -exportArchive`, which needs a signing identity and profile that CI does not have, and
bringing signing in scope to police a 1–3 MB app against a 30 MB ceiling is not worth it. **Trade-off
taken deliberately**: CI gates an *unsigned proxy* — the binary's `__TEXT` size plus bundled
resources, minus the sqlite — which tracks code growth faithfully even though it is not the download
figure. The real thinned number is read once from App Store Connect at the first upload and recorded
in Decisions; if the proxy and the real number ever diverge materially, that is a finding, not a
gate failure.

### Testing and the CRAP gate

**Swift Testing (`@Test`) is the default for new tests; XCTest stays for what it cannot do.** They
coexist in one target and one `swift test` run collects coverage across both. XCTest is required for
the `XCTMetric` performance APIs (explicitly unsupported in Swift Testing) and for UI automation.
`@Test(arguments:)` fits the 5-locale × schedule matrix directly. One gotcha: a custom test entry
point silently disables Swift Testing.

**`scripts/crap_swift` — and why SwiftLint cannot be its complexity source.** Measured against probe
files, SwiftLint's `cyclomatic_complexity`:
- counts decision points **from 0, not McCabe from 1** — so straight-line code scores `cc = 0`, and
  `crap = 0² × (1−cov)³ + 0 = 0`: **completely untested code scores a perfect zero forever**;
- counts **neither `&&`/`||` nor ternaries** (`if a > 0 && b > 0` reports 1, McCabe 3) — a 9× swing
  in the squared term;
- is **`func`-only**: given a `var body` and a `func` with identical bodies, it reports only the
  `func`. Closure-valued properties are invisible too.
- and exposes the number only inside a prose string (`"currently complexity is 12"`); its JSON
  reporter has no numeric complexity field.

That last point is fatal for SwiftUI, because **llvm-cov *does* emit computed-property getters as
first-class functions** (`Model.label.getter`, with its own regions). Coverage and complexity would
disagree about what a function *is*, precisely where SwiftUI complexity lives. `lizard` shares the
blind spot.

**`scripts/crap_swift.py` is Python, and owns its own complexity count.** Python, so it sits beside
`scripts/crap.py` under one interpreter the repo already has, and so the gate needs no build of its
own before the chain can run it. It counts complexity with a **token scan** — `if`, `guard`, `for`,
`while`, `case`, `catch`, `&&`, `||`, `? :`, starting at 1 — walking `func`, `init`, `subscript` and
brace-matched accessor bodies including `var body`. Deliberately **not** a SwiftSyntax walker: that
would add `swiftlang/swift-syntax` to the build, pinned to the toolchain and recompiled on every
`swift build`/`swift test` in the chain, to police a package of one or two thousand lines. This is
the same stance `[tool.crap-ts]` already takes — **formula parity, not metric parity** — so the
count only has to be stable and honest, not identical to any other tool's.

Coverage comes from `swift test --enable-code-coverage` + `llvm-cov export -format=text` (which
**is** the full JSON). Three traps, all verified: `--summary-only` and `--skip-functions` each strip
the `functions` array entirely and must never be used; there is **no per-function `summary` and no
per-function percentage**, so the fraction is derived from code regions
(`kind == 0`, `covered/total`), validated against llvm-cov's own file-level arithmetic; and function
names are **mangled** (`xcrun swift-demangle --compact`). Swift emits no branch regions. The join key
between the two tools is the **function start line**, which matched exactly in testing.

Config is `[tool.crap-swift]` in `pyproject.toml`, its own ratchet at the same 30/5 bar — **formula
parity, not metric parity**, exactly the stance `crap_ts.mjs` already takes against `crap.py`.

**The gate scores the `SwimZHKit` package only; the thin app target is excluded.** This is
empirically forced, not stylistic: a 36-line SwiftUI file reported **48 executable lines** (line
inflation reproduced directly, and corroborated by long-standing unanswered Apple forum reports),
there is no first-party way to unit-test a view body, and calling `.body` headlessly crashes the
test process. It mirrors what `vitest.config.ts` already does — excluding the four browser
entrypoints while `appdata.ts` carries the measured rules. **`SwimZHKit` is this plan's `appdata.ts`:
every rule lives there, and the app target stays too thin to hide one.**

### Freshness: bundle floor + optional refresh

The app ships `ios.sqlite` in its bundle — the offline floor, working on first launch with no
network. On launch (and on foreground, at most hourly) it fetches
`{schema_version, built_at, horizon_end, url, sha256, bytes}`. If `schema_version` matches the app's
and `built_at` is newer than the store in use, it downloads to a temp file, verifies the hash, and
swaps atomically into Application Support. A failed, absent, or version-mismatched fetch is a
**no-op** — never an error banner: the bundled or previously-downloaded store keeps serving.

### Offline degradations (the "few concessions")

| Feature | Offline behaviour |
|---|---|
| schedules, prices, lane plans, features, pool browser, search, distance | full, no change |
| live crowd level (Baditicker) | badge absent, with an explicit "live data unavailable" state — never a stale number, never a fake zero |
| live water temperature | same — the existing `TempUnavailable` vocabulary |
| data newer than the bundle | serves the bundled store and shows its `built_at` |
| dates past `horizon_end` | explicit "beyond the published horizon"; distinct from "closed" |

## Out of scope

- Android, watchOS, App Clips, push notifications.
- Any change to `/swim`, `/pools`, `/access-types` response shapes. The only web-tree change in
  this plan is S2's extension of the eligibility-contract generator.
- Porting the resolver, calendar, holiday, season or closure logic to Swift (the rejected design;
  see E1).
- Hosting/CDN provisioning for the manifest. S5 makes the URL configurable and ships a `make`
  target producing the two files; where they are uploaded is the user's call.
- App Store submission proper: signing credentials, screenshots, store metadata, review replies.
  (A privacy manifest, launch screen and the UIScene lifecycle are **in** scope — they are app
  correctness, they are free to do now, and S2b acceptance 5 requires them.)
- Write features (accounts, favourites sync). Local-only favourites are allowed in S3a.
- **MapKit.** Map tiles are network-backed and would break the "fully offline" property this plan
  is built on. The radius filter uses coordinates and distance only, with no map view. (If a map is
  wanted later it is a separate decision, and `NSLocationWhenInUseUsageDescription` becomes
  mandatory — without it the app exits.)
- App Intents / Spotlight `IndexedEntity` / WidgetKit. All three are genuinely cheap on top of
  `SwimZHKit` and are the obvious next plan; none is needed for parity with the web app. Live
  Activities are ruled out on the merits — they are for in-progress user-started events, and a
  static schedule has none.
- iPad-specific layout. Not mandatory (guideline 2.4.1 says "should"), but note the decision has a
  shape: on iPad the detail **sheet** becomes a detail **column**, so revisiting it later is a
  navigation change, not a styling one.
- Swift 6 `@concurrent` background offload. The whole query is a single indexed SQLite read; adding
  concurrency before a measurement says it is needed is speculative.

## Slices

### S1 — the pre-resolved export, proved equal to the live query

- **Goal**: `swimzh export-ios` produces a store whose baked answers are provably identical to what
  `find_swim_options` returns today, for every pool on every date in the horizon.
- **Touches**: `src/swimzh/etl/ios_export.py` (new), `src/swimzh/cli.py` (`export-ios`),
  `src/swimzh/storage/atomic.py` (reuse), `tests/etl/test_ios_export.py` (new),
  `tests/fixtures/ios_parity/` (new — the golden fixture S2 consumes, regenerated with
  `SWIMZH_REGENERATE_IOS_PARITY=1`, the peer of `SWIMZH_REGENERATE_ELIGIBILITY_CONTRACT`),
  `docs/concepts/ios-resolved-export.md`.
- **Acceptance**:
  1. `uv run python -m swimzh.cli export-ios --db gold.sqlite --out /tmp/ios.sqlite` exits 0 with
     **no network** (the export reads gold only) and writes a `STRICT` store with the schema above.
  1b. **The store is bundle-readable.** A test asserts, on the produced file: byte offset 18 reads
     `0x01`, i.e. **not WAL** — measured, `delete`/`truncate`/`memory`/`off` all write `0101` and
     only `wal` writes `0202`, so this proves the property that matters rather than the exact mode.
     (`PRAGMA journal_mode` can fail *silently* and return the original mode, so the pragma's own
     return value is not sufficient evidence.) Also: no `-wal` or `-shm` sidecar
     exists beside it; `PRAGMA integrity_check` returns `ok`; and `sqlite_stat1` is populated
     (`ANALYZE` ran). A second test opens the file `SQLITE_OPEN_READONLY` from a **read-only
     directory** and successfully *prepares and steps* a query — not merely opens it. Opening a
     WAL-mode file succeeds and the first **prepare** fails with `SQLITE_CANTOPEN`; a test that only
     asserts `open` would pass against a database no device could read.
  2. **Parity sweep** — mechanically assertable, against the **domain** layer, not the DTOs. For
     every pool × every date in `[horizon_start, horizon_end]`, run
     `find_swim_options(query=SwimQuery(person=Person(gender=None, age=None), at=date@12:00,
     near=None, radius_km=None), facilities=facilities, calendar=calendar, roster=roster)`
     — note the real positional order is `(query, facilities, calendar, roster=())`
     (`query.py:564-570`), calendar BEFORE roster — and assert:
     - the multiset of `SwimOption` tuples `(facility_id, basin_id, session.time.start,
       session.time.end, type(session.access).__name__, dataclasses.asdict(session.access),
       session.weather)` equals the export's `session` rows;
     - the multiset of `FacilityStatus` tuples `(facility_id, status, code, closure, params)`
       equals the export's `day` rows. Those are the **domain** field names
       (`query.py:321-338`); the export's columns keep the client-facing `StatusOut` names, so
       the export phase applies the fixed mapping `code→detail_code`, `closure→closure_code`,
       `params→detail_params` and the test asserts through it;
     - `QueryResult.notices` equals `day_notice`, and `QueryResult.warnings` equals the rendering of
       `day_warning`.
     Zero diffs. Time-of-day-dependent fields (`open_at_query_time`, `lane_availability`,
     `lane_timeline`, `lane_best_public`) and person-dependent fields (`eligibility`, `price`) are
     **deliberately excluded** — E1 assigns them to the client, and S2 acceptance 3 covers them.
     Measured: a 400-date × 57-facility sweep runs in ~0.3 s and raises 0 exceptions, so it
     runs unsampled — no sampling, no marked-slow test.
  3. Every basin carrying a `LanePlan` has 7 `lane_day` rows, each carrying its plan's
     `unresolved_lanes` and `confidence`. `pool_basin` carries all 12 `BasinOut` fields and
     `pool.operating_season` is non-null for exactly the 13 pools that declare one.
  4. `meta.horizon_end == horizon_start + 399 days` regardless of calendar coverage, and the report
     logs how many horizon days fall outside `calendar.known_years` (the E2 reseed signal).
  5. A second run over unchanged gold produces an identical `meta.content_hash`.
  6. The exported file is **under 8 MB**; the test asserts the bound and prints the actual size
     so growth is visible. Measured row counts over a 400-day horizon: **11,927 sessions,
     16,924 day rows**, 271 warnings, 9 notices, 57 pools, 33 basins, 42 lockers, 85 rentals,
     9 features, 49 lane_day — ~29k rows total.
  7. Python QA chain green; coverage not below the current `fail_under`.
- **Depends on**: —

### S2 — SwiftUI walking skeleton: bundled store, real answers, parity-tested logic

- **Goal**: an app that launches with no network, opens the bundled export, and lists today's real
  options for a person — proving the Swift half is only eligibility, price, distance and the clock.
- **Touches**: `apps/ios/` (new: `Package.swift`,
  `Sources/SwimZHKit/{Store,Eligibility,Pricing,Geo,Clock,Answer}.swift`, `Tests/SwimZHKitTests/`),
  `apps/ios/App/` (one list screen + the Xcode project),
  `apps/web/tests/test_eligibility_ui_contract.py` (emit `access_params` per case),
  `apps/web/static/js/eligibility.test.js` (consume the widened case),
  `Makefile` (`make ios-export`, `make ios-qa`), `.github/workflows/qa.yml` (new `ios-qa` job on
  `macos-latest`).
- **Acceptance**:
  1. `swift test` in `apps/ios/` passes with **no network and no simulator** (SwiftPM only).
  2. The eligibility test replays every case in `eligibility_contract.json` with zero mismatches,
     and **fails** if the case count differs from the file's, rather than skipping. The regenerated
     fixture carries `access_params`, and the three parameterised arms (`SeniorsOnly`,
     `AdultsOnly`, `GenderDiverse`, each at `min_age ± 1`) appear in it. The Python and JS suites
     stay green against the widened fixture.
  3. A golden test over `tests/fixtures/ios_parity/` (produced by S1): for 3 pools × 5 dates × 3
     personas, `SwimZHKit.answer(...)` returns exactly the options, statuses, eligibility verdicts,
     prices and `open_at_query_time` values the fixture states.
  4. `haversineKm` matches `domain/geo.haversine_km` to 1e-6 on a coordinate-pair fixture.
  5. **Human-verified at the S2 pause**: the app runs in a simulator in Airplane Mode and shows a
     non-empty list for today. This is a pause-gate eyeball, deliberately not a machine criterion.
  6. Swift chain green, including the `xcodebuild` build step on `macos-latest`.
  7. **The store actor is correct under Swift 6 strict concurrency**, with tests for the two
     footguns: `sqlite3_open_v2` returning a handle on failure is closed (no leak), and every
     `sqlite3_bind_text` uses `SQLITE_TRANSIENT` (a `SQLITE_STATIC` bind of a bridged Swift `String`
     is a use-after-free). No `sqlite3_stmt*` escapes the actor — a compile-time fact, asserted by
     the API surface returning only value types. The package builds with `nonisolated` default
     isolation (SwiftPM's default, which is what the logic layer wants).
- **Depends on**: S1

### S2b — the quality and budget harness, before there is anything to negotiate away

- **Goal**: the CRAP gate, the budget ratchet and the app-correctness items exist while the app is
  still one screen — so every later slice is measured from birth rather than audited at the end.
- **Touches**: `scripts/crap_swift.py` (new), `pyproject.toml` (`[tool.crap-swift]`),
  `apps/ios/budgets.json` (new), `apps/ios/Tests/MetricTests/` (app-hosted XCTest target),
  `apps/ios/App/PrivacyInfo.xcprivacy`, the launch screen, the UIScene lifecycle,
  `Sources/SwimZHKit/LaunchSignpost.swift`, `.github/workflows/qa.yml` (extend `ios-qa`).
- **Acceptance**:
  1. **`scripts/crap_swift.py` gates.** It joins its own token-scan cyclomatic complexity
     (`if`/`guard`/`for`/`while`/`case`/`catch`/`&&`/`||`/`? :`, starting at 1, including
     brace-matched accessor bodies such as `var body`) to per-function region coverage derived from
     `llvm-cov export -format=text`, keyed on the function start line, names demangled via
     `swift-demangle --compact`. `[tool.crap-swift]` in `pyproject.toml`, same 30/5 bar, scoring
     `Sources/SwimZHKit/**` only.
  2. Tests pin the four verified traps: `--summary-only` / `--skip-functions` are never passed (each
     strips the `functions` array entirely); the fraction comes from `kind == 0` regions, because
     there is **no per-function `summary`**; a `var body` computed property **is** scored (the
     specific thing SwiftLint cannot see, which is why it is not the source); and a function with
     `cc == 0` is impossible by construction — a base-0 count would score untested straight-line
     code at CRAP 0 forever.
  3. **Peak memory is measured where the number means something**: `XCTMemoryMetric` in the
     **app-hosted** `MetricTests` target, run by `xcodebuild test` (never a UI test — it measures
     the test runner, and it reports a *delta*, not a peak, so it is a loose ratchet, not a tight
     gate). Ceiling recorded in `budgets.json`.
  4. **Size is two numbers, ratcheted separately** in `budgets.json`: `app_minus_sqlite` (the
     unsigned proxy — binary `__TEXT` via `size -m` plus bundled resources, minus the sqlite) and
     `sqlite`. A test fails on regression against either. A data refresh can therefore never mask a
     code regression, and no signing identity is needed.
  5. **App-correctness items that are cheap now and forced later**: a launch screen (a submission
     requirement from iOS 27), the UIScene lifecycle (without it *"your app won't launch"* on iOS
     27), `UIRequiresFullScreen` **never set** (ignored from the iOS 27 SDK), and a
     `PrivacyInfo.xcprivacy` declaring the `UserDefaults` required-reason API — `@AppStorage` **is**
     `UserDefaults`, and omitting it is an `ITMS-91055` upload rejection. Each reason code is
     verified **in a browser** against Apple's page before it is committed: that page renders
     client-side, and one automated read of it produced fabricated categories.
  6. **The launch signpost exists before there is a launch worth measuring.** An `OSSignposter`
     interval spans app start to *data on screen*, registered with MetricKit
     `extendLaunchMeasurement(forTaskID:)`. This is not optional: Apple measures launch as
     time-to-first-frame, so drawing an empty list shell and loading the store afterwards would make
     the official number excellent and false. Launch time is **not** a CI gate — see the budgets
     table — so this slice ships the instrument, and S3b reads it on a device.
  7. Swift chain green, including `crap_swift.py` and `xcodebuild test`.
- **Depends on**: S2

### S3a — the phone list: filters, day strip, ghost states

- **Goal**: the primary screen at parity — you can answer "where can I swim?" end to end.
- **Touches**: `apps/ios/App/` — filter bar (gender/age/date/radius/eligible-only/kind), the day
  strip (`blocks/phonebar.ts`), the pool list card without its canvas tail
  (`blocks/poollist.ts`), the four day states, the warning/notice banners, place typeahead
  (`components/placetypeahead.ts`), local-only favourites,
  `Sources/SwimZHKit/FieldCoverage.swift`, `scripts/field_coverage.py` (new),
  `apps/web/tests/test_field_coverage_contract.py` (new — the staleness gate).
- **Acceptance**:
  0. Every entry in `deliberatelyOmitted` is a `[String: String]` value whose reason string is
     non-empty — asserted by the test. Prose in the Decisions section is not a mechanism, which is
     the same finding round 1 raised against the markdown checklist.
  1. **Field coverage is a real test, not a checklist — and it has TWO halves.**
     `scripts/field_coverage.py` generates
     `apps/ios/Tests/SwimZHKitTests/fixtures/field_coverage.json` from the pydantic models
     (`OptionOut`, `StatusOut`, `PoolOut`, **and `FacilityDetailOut`** — the S3b detail sheet must
     be governed by the mechanism, not by prose). It imports the *model* modules only, never
     `apps.web.main`, which fails fast without `SWIMZH_GOLD_DB`.
     - **Python half (the staleness gate, without which the whole thing is decorative):**
       `test_field_coverage_contract.py` asserts the committed JSON still equals what the models
       generate, regenerated with `SWIMZH_REGENERATE_FIELD_COVERAGE=1` — exactly the teeth
       `test_eligibility_ui_contract.py:16-19` gives its fixture. Adding a field to `OptionOut`
       must fail this test.
     - **Swift half:** asserts `renderedFields ∪ deliberatelyOmitted == fields(json)` and that the
       two sets are disjoint. Every name in `deliberatelyOmitted` carries a one-line reason in the
       Decisions section. The lane quartet starts omitted and moves in S3b; the test enforces the
       move. `renderedFields` is a hand-maintained declaration: this proves **drift detection
       against the web models**, not that any pixel is drawn.
  2. The four day states (`closed`+`closure_code`, `awaiting_scrape`, `no_source`,
     `open_unscheduled`) render distinctly; a test asserts no state maps to the plain "closed"
     label. A date past `horizon_end` renders the E2 state, distinct from all four.
  3. Both `day_warning` codes and `day_notice` rows surface in the UI; a test drives a date with
     each and asserts a banner model is produced.
  4. **Accessibility size is the designed state — and the decision is a pure function.** The rule
     lives in `SwimZHKit` as `stripLayout(for: DynamicTypeSize, width: Double) -> StripLayout`
     (chip count, whether inline ribbon labels collapse to a legend, scaled strip height); a test
     asserts fewer chips and `labelsCollapsed == true` at every accessibility size, and that chip
     width never *shrinks* below the standard-size value. The view is a thin reader of it. What a
     test cannot see — actual truncation, `@ScaledMetric` rendering, the ≥ 44×44 pt tap targets via
     `.contentShape(Rectangle())` — is **human-verified at the S3a pause**, which is why S3a is now
     in `pause_after`.
  5. **`List` laziness is preserved, enforced structurally.** The row and its optional expanded
     content are wrapped in an explicit `VStack` so a `ForEach` element always resolves to exactly
     one view. This is a **lint**, not a runtime test: no `if` or `switch` producing a variable view
     count may appear directly inside the row `ForEach`'s element. SwiftUI exposes no API for "how
     many bodies did `List` build", and a counter in `body` would assert a framework scheduling
     decision — flaky, and about an implementation detail. The rule itself is decidable from source.
     Rationale: WWDC23 10160 — a variable-count element forces `List` to build every body just to
     learn the identifiers.
  6. **The system does the design work**: `.searchable` inline with content, the filter bar via
     `safeAreaBar(edge:)` (never `safeAreaInset`/`overlay`), `List` not `LazyVStack`,
     `ScrollPosition` + `.scrollTargetBehavior(.viewAligned)` on the day strip,
     `.sensoryFeedback(.selection,)` on chip changes, `.scrollEdgeEffectHidden(for: .horizontal)`
     on the strip. A lint asserts the app target contains **no hardcoded colour literal** — the
     banned tokens are named so the check is decidable: `#colorLiteral`, `Color(red:`,
     `Color(.sRGB`, `Color(hue:`, `UIColor(red:` — every colour resolves from the Asset Catalog;
     and no `.glassEffect()` outside the filter bar. The same lint carries S4's catalog rule from
     this slice on, so later slices cannot land unlocalised literals that S4 must retrofit.
  7. Swift chain green, and the S2b budget ratchet does not regress.
- **Depends on**: S2b

### S3b — the canvas: ribbon day tail, lane stack, facility detail

- **Goal**: the visual half — the ribbon encoding and the per-lane view the desktop board has.
- **Touches**: `Sources/SwimZHKit/RibbonModel.swift` (port of `blocks/ribbonmodel.ts`, 287 lines),
  the SwiftUI `Canvas` renderer (ports of `ribbonrender.ts` 497 + `daytail.ts` 215, incl. the hour
  ticks from the `mobile-daytail-time-axis` plan), the expanded per-lane stack (`gantt.ts` 371),
  the facility detail sheet (prices, features, lockers, rentals, source stamp — ports of
  `detailpanel.ts` 677), the all-pools browser with `kind` filter, the access-types explainer,
  `apps/web/static/js/blocks/ribbonmodel.test.ts` (emit a committed golden JSON).
- **Acceptance**:
  1. `ribbonmodel.test.ts` gains a regenerable golden artifact
     (`apps/web/static/js/blocks/fixtures/ribbon_golden.json`, `REGENERATE_RIBBON_GOLDEN=1`), and a
     Swift test asserts `RibbonModel` reproduces it exactly. Both suites stay green.
  2. The lane quartet (`lane_availability`, `lane_timeline`, `lane_day_view`, `lane_best_public`)
     moves from `deliberatelyOmitted` into `renderedFields`; S3a's coverage test enforces it.
  3. Lane derivations are computed in Swift from `lane_day` at the queried instant and match a
     Python-generated fixture, for all 7 lane-plan basins across 7 weekdays × 4 times of day. The
     port surface is **seven functions, ~150 lines** of `domain/lane_plan.py`:
     `_active_reservations`, `_public_run_end`, `lane_availability_at`,
     `lane_availability_timeline`, `lane_day_view`, `best_public_time`, `club_roster`. The fixture
     must include a basin with non-empty `unresolved_lanes` so `partial` is exercised, not assumed.
  4. `FacilityDetailOut`'s fields move from `deliberatelyOmitted` into `renderedFields` under
     S3a's coverage test: `features` (incl. `closed_reason`), `lockers`, `rentals`, `basins` (all
     12 `BasinOut` fields incl. `physical_source`), `operating_season`, `last_admission_before` and
     the provenance stamp. Prose does not govern this criterion — the generated fixture does.
  5. **The Canvas is accessible, and the assertable half is a pure function.** Apple states plainly
     that a Canvas offers *no* accessibility for individual elements, so
     `accessibilityChildren(children:)` supplies one element per session block with
     `.accessibilityCustomContent` for the secondary facts. `SwimZHKit` owns
     `a11yBlocks(for: DayRibbon, width: Double) -> [A11yBlock]` (frame + label + custom content),
     and a test asserts one block per rendered session with the right labels, for a fixture day.
     The view feeds exactly that array to `accessibilityChildren`, and a lint asserts every
     `Canvas` in the app target has an `accessibilityChildren` modifier — a ribbon without one
     fails outright.
  6. **One time→x function, three consumers.** The renderer, the tap/drag hit-test and the
     `accessibilityChildren` layout all call the same pure mapping in `SwimZHKit`; a test asserts a
     tap at the x of a block's midpoint selects that block, for every block of a fixture day. It is
     CRAP-gated like any other rule.
  7. **CPU guards are structural, not hoped for.** The static ribbon and the moving "now" cursor are
     **two overlapping Canvases**, because the whole Canvas redraws on every invalidation (published
     measurements: ~30% CPU for a full redraw at animation rate, ~6% when static and dynamic content
     are split — a ~5× win; third-party figures, motivating the structure, not asserted by it). The
     cursor's `TimelineView` is `.everyMinute` and is passed `paused:` from a pure
     `SwimZHKit` policy — `animationPaused(scenePhase:reduceMotion:) -> Bool` — which the test
     drives across all combinations, because whether `TimelineView` self-pauses off-screen or
     backgrounded is **undocumented and not relied on**. `drawingGroup()` is **not** applied to any
     Canvas (Canvas is already Metal-backed; it would add an offscreen pass) — a lint asserts its
     absence. The two-Canvas split itself is a structural lint plus the human CPU check at the pause.
  8. The expanded Gantt uses **Swift Charts** (`BarMark(xStart:xEnd:y:height:)`, which Apple
     documents for Gantt charts) for its free per-mark VoiceOver, and is built **one at a time**,
     never 57 in the list — there are credible reports of 100% CPU and 50–150 ms hangs at
     500–2000 points, which is what 57 live charts in a `List` would be.
  9. **The budgets hit their targets, now that the app is feature-complete**, measured on a real
     device at the pause: cold launch to *data on screen* under 1 s (via the signpost, not the
     first-frame number); per-row view body under 500 µs in Instruments' Long View Body Updates
     lane; ribbon CPU under 10% while scrolling; peak memory under 100 MB; `app_minus_sqlite`
     download size under the 4 MB ratchet.
 10. Swift chain green. Human-verified at the S3b pause: the ribbon reads correctly on a notched
     device, and in both light and dark appearance.
- **Depends on**: S3a

### S4 — five languages, natively

- **Goal**: pl / en / de / it / fr, with the same message keys and the same regional formatting the
  web UI pinned.
- **Touches**: `scripts/locales_to_xcstrings.mjs` (new — **node**, not Python: it imports the
  compiled `dist/locales/*.js` rather than hand-parsing TypeScript, the same way `scripts/crap_ts.mjs`
  reads TS-side artifacts), `apps/ios/Sources/SwimZHKit/Resources/Localizable.xcstrings`,
  `Sources/SwimZHKit/Format.swift`, tests for the converter.
- **Acceptance**:
  1. Every key in `locales/en.ts` exists in the `.xcstrings` for all five locales; a test fails on
     any missing key or locale-parity gap (the guarantee `locales/parity.test.ts` gives the web).
  2. **Not vacuous** — but stated so it does not ban the correct idiom. In SwiftUI a literal in a
     `LocalizedStringKey` position (`Text("board.hoursNotListed")`) **is** the catalog key, so
     "no string literals" would forbid the right code and miss the real failure. The lint asserts
     instead: (a) every string literal in a `LocalizedStringKey` position resolves to a key present
     in `Localizable.xcstrings`; (b) every `Text(verbatim:)` and every interpolated user-visible
     `String` appears in an allowlist file with a one-line reason. Without this, criterion 1 passes
     against a 92-key seed catalog and proves nothing — `locales/en.ts:9` says "SEED ONLY".
  3. **The `plurals.ts` compile-time guarantee is restored, because Xcode cannot provide it.** There
     is no build error and no documented build warning for a missing plural category: a missing
     Polish `many` silently falls back to `other` — the *decimal* form — producing exactly the broken
     grammar `plurals.ts` exists to prevent. A **Run Script build phase** walks the `.xcstrings`
     JSON (`strings.<key>.localizations.<lang>.variations.plural.<category>`) and emits `error:` for
     any category CLDR requires and the catalog lacks. Apple publishes no `.xcstrings` format spec,
     so a golden-file test pins the shape the script parses.
  3b. **The `.xcstrings` category sets equal what `plurals.ts` already pins.** The check is
     conformance, not a bug hunt: `PLURAL_CATEGORIES` (`plurals.ts:23-31`) declares
     `fr: [one, many, other]`, `it: [one, many, other]`, `pl: [one, few, many, other]`,
     `de`/`en`: `[one, other]`, and `plurals.test.ts:21-24` already asserts that against
     `Intl.PluralRules`. The Run Script asserts the `.xcstrings` carries exactly those sets, so the
     two runtimes cannot drift.
  3c. Plural tests use **`bundle:`** (or `.environment(\.locale,)`), not `String(localized:locale:)`:
     Apple documents that parameter as *"This doesn't change which locale the system uses to look up
     the localized string."* Whether it drives plural-rule *selection* is unverified, so the first
     task is a probe at n = 1, 2, 5, 22, 1.5 before the matrix is built on it.
  4. Formatting locales are regional exactly as `datefmt.ts` pins them: `en-GB`, `de-CH`, `fr-CH`,
     `it-CH`, `pl`. Tests pin the two counter-intuitive facts: Polish genitive lowercase month
     (`23 lipca`), and **de-CH and it-CH use a dot decimal separator** while fr-CH and pl use a
     comma. The web side already pins these (`datefmt.test.ts:85-93`) through `Intl.NumberFormat`;
     iOS must be asserted separately because Apple ships its own ICU snapshot, so a simulator test
     re-checks them rather than assuming parity. Also pin the **Swiss group separator, ASCII
     apostrophe U+0027** (not U+2019), which the iOS side has no equivalent guard for.
  4b. **iOS 26 no longer renders section headers in all capitals** regardless of the capitalization
     given. All five catalogs are audited for headers written to rely on the system shouting them.
  5. The `dayParts()` rule, made decidable: a grep bans `.split(` and `.components(separatedBy:`
     **anywhere inside `Format.swift`**, the one module allowed to format dates. (A grep cannot
     decide "applied to a `FormatStyle` result"; banning the operators in the only file that holds
     format results can be decided, and any future need for them is a reviewed exception.)
  6. Swift chain green.
- **Depends on**: S3b. (Not S3a: S3b lands the ribbon, detail sheet, browser and explainer, and
  if S4 ran first those would arrive afterwards carrying unlocalised literals for S4 to retrofit
  inside `max_rounds: 2`. S3a introduces the catalog lint so every slice between keeps it green.)

### S5 — live data with honest degradation, and the weekly refresh

- **Goal**: crowd level and water temperature when online, an explicit unavailable state when not;
  and a store that can update without an App Store release.
- **Touches**: `Sources/SwimZHKit/Live.swift` (Baditicker client, 2-minute in-process TTL like the
  web runtime), `Sources/SwimZHKit/Refresh.swift` (manifest fetch, sha256 verify, atomic swap into
  Application Support), `src/swimzh/etl/ios_export.py` (emit `manifest.json` beside the store),
  `Makefile` (`make ios-release`), `docs/concepts/ios-resolved-export.md`.
- **Acceptance**:
  0. **The offline lint is narrowed, not deleted.** `SourceLintTests.noNetwork` (shipped in S2)
     bans `URLSession`/`Network`/`NWConnection`/`CFSocket` in **both** targets, which S5 cannot
     satisfy. It becomes an allowlist of exactly `Live.swift` and `Refresh.swift`, with the lint
     still asserting every other file in both targets is clean, and a test proving the lint fails
     when a network call is added outside the seam. This is the S3a-surfaced conflict recorded in
     Decisions; do not discover it again.
  1. Airplane Mode: the app is fully usable; the crowd and temperature badges show the explicit
     unavailable state and never a stale or zero value. A test drives a failing transport and
     asserts that state.
  2. A store whose `schema_version` differs from the app's is **rejected** and the previous store
     keeps serving — asserted by a test, so a bad upload cannot brick installed apps.
  3. A download whose sha256 does not match is discarded, and the previous store keeps serving.
  4. The swap uses `FileManager.replaceItemAt` into **Application Support** (never `Caches` or
     `tmp` — both are system-purgeable and must never hold the only copy), with
     `isExcludedFromBackup` set. A test asserts that after a simulated failure mid-download, (a) the
     store in use is still readable and unchanged, and (b) no temp file is left behind.
  4b. **Every open connection is closed before the swap.** `replaceItemAt` exchanges the *file*
     while an open connection still holds an fd to the **old inode**, so a live reader would keep
     serving the previous data with no error to reveal it. A test asserts the actor's handle is
     closed and reopened across a refresh, and that a query after the swap returns the new
     `meta.built_at`. `replaceItemAt` also requires the same volume — the temp file is created in
     Application Support, not `tmp`.
  4c. A downloaded store is validated the same way the bundled one is: sha256, then **opened
     read-only and `PRAGMA integrity_check`**, then the DELETE-journal byte assertion from S1
     acceptance 1b — a WAL-mode file served by a mis-configured build would otherwise fail on the
     device at first prepare, after the swap.
  5. `make ios-release` produces `ios.sqlite` + `manifest.json` whose fields agree with the store's
     `meta`.
  6. Python and Swift chains green.
- **Depends on**: S2b (for the budget ratchet; otherwise independent of S3a/S3b/S4 and may be
  implemented earlier if preferred). **This is the slice to move into its own plan** if the seven
  here prove too many — see the Decisions note on the slice count.

### Pre-approval review, round 3 (2026-08-23, plan-critic, verdict: revise → addressed)

Round 3 attacked the non-functional material and returned 8 blocking findings. All 8 are taken.

**R3-1 — six new criteria asserted view behaviour that the plan itself says cannot be tested, with
no runner for it either.** The chain ended in `xcodebuild … build`, never `test`, and `swift test`
is SwiftPM-only and cannot import the app target. Both halves fixed, and the fix improved the
design: every such criterion now names a **pure `SwimZHKit` seam** the test actually drives —
`stripLayout(for:width:)`, `a11yBlocks(for:width:)`,
`animationPaused(scenePhase:reduceMotion:)` — with the genuinely visual half moved to a human pause
gate; and the chain ends in `xcodebuild test` so the app-hosted metric target has a runner at all.
Pushing the rules into the measured package is what `SwimZHKit`-as-`appdata.ts` was for.

**R3-2 — the "build counter proves `List` laziness" test was unimplementable.** SwiftUI exposes no
API for how many bodies `List` built; a counter in `body` asserts a framework scheduling decision.
Replaced with a **source lint** — no variable-view-count `if`/`switch` directly inside the row
`ForEach` element — which is decidable and is what the WWDC23 10160 rule actually says.

**R3-3 — the only CI-gated size number could never run.** `xcodebuild -exportArchive` needs a
signing identity and profile that CI has not got, while signing was out of scope. Rather than bring
signing in to police a 1–3 MB app against a 30 MB ceiling, CI now gates an **unsigned proxy**
(binary `__TEXT` + bundled resources, minus the sqlite), with the real thinned number read once from
App Store Connect at first upload. The trade-off is stated in the Design, not hidden.

**R3-4 — S2 required the privacy manifest that Out of scope forbade.** A verbatim
self-contradiction. Privacy manifest, launch screen and UIScene lifecycle are app *correctness*, are
free now, and are in scope (S2b acc 5); only submission proper — signing credentials, screenshots,
store metadata — stays out.

**R3-5 — S3a carried "human-verified at the pause" criteria but had no pause.** S3a added to
`pause_after`.

**R3-6 — S4 acceptance 3b hunted a bug the repo makes impossible.** I had claimed `it`/`fr` might be
missing the CLDR `many` category. Refuted and verified myself: `plurals.ts:23-31` declares
`fr: [one, many, other]` and `it: [one, many, other]`; `Plural<L> = Record<PluralCategory<L>, string>`
makes an omission a `tsc` error; `plurals.test.ts:21-24` asserts the table against
`Intl.PluralRules`; both catalogs carry 8 `many:` entries each; and `node` confirms the categories.
The criterion is restated as **conformance** — the `.xcstrings` must carry exactly the sets
`PLURAL_CATEGORIES` already pins — which is the useful check. The related insinuation that the web
side might have the Swiss separator wrong was also dropped: it formats through `Intl.NumberFormat`
and cannot.

**R3-7 — `crap_swift` was a gate command with no defined artifact, and its dependency was not
free.** Adding `swiftlang/swift-syntax` to the package would recompile it on every `swift build`
and `swift test` in the chain, toolchain-pinned, to police one or two thousand lines. It is now
`scripts/crap_swift.py` — Python, beside `scripts/crap.py`, needing no build of its own — counting
complexity with a token scan that includes brace-matched accessor bodies. Formula parity, not metric
parity, exactly as `[tool.crap-ts]` already does.

**R3-8 — S2 had become a dumping ground**: ten criteria and five deliverables under one gate at
`max_rounds: 2` — round 1's finding 10 in a new place. Split into **S2** (skeleton: package, SQLite
actor, parity tests, Xcode project, `ios-qa` job) and **S2b** (tooling: `crap_swift.py`,
`budgets.json`, the launch signpost, the app-correctness items). The plan's own principle — build
the harness early so budgets are not negotiated away at the end — is preserved by splitting, not by
deferring.

**Slice count: seven, against the format's 2-6 heuristic — a deliberate, flagged deviation.** The
critic's route back to six is to move S5 (live data + the weekly refresh) into its own plan. That is
a real option and S5 now says so, but it defers a capability **the user explicitly chose**
("Bundle + optional download"), so it is the user's call to make, not one to take quietly. The plan
ships at seven with the option stated.

**Round-3 verifications, recorded so they are not re-litigated.** Checked against this machine's
iOS 26.5 SDK `.swiftinterface` files and Apple's system SQLite: `safeAreaBar(edge:alignment:spacing:content:)`
exists at iOS 26.0; `accessibilityChildren(children:)` exists; `SearchToolbarBehavior.minimize`
exists (the `.minimized` spelling really is wrong, including in Apple's own doc sample);
`scrollEdgeEffectHidden(_:for:)` has defaulted parameters so `.scrollEdgeEffectHidden(for: .horizontal)`
compiles; `GraphicsContext.environment` exists, so asset-catalog colours resolve inside a Canvas;
`BarMark(xStart:xEnd:y:height:)` exists with `PlottableValue` bounds — the Gantt shape this plan
needs; `GlassEffectID` has **zero** hits, confirming the correction. Apple's SQLite reports
`THREADSAFE=2` and `DEFAULT_CACHE_SIZE=2000`, so the actor and the explicit `cache_size` are both
load-bearing. The WAL-in-a-read-only-directory failure reproduced exactly: open succeeds, the first
query fails. And measured across all five journal modes, byte 18 is `01` for `delete`, `truncate`,
`memory` and `off` and `02` only for `wal` — so the assertion is restated as **"not WAL"** rather
than the over-claim "DELETE".

**Claims still taken on faith, ranked by what breaks if they are wrong.** (1) That SwiftLint counts
from 0, is `func`-only, and exposes no numeric JSON field — if wrong, `crap_swift.py`'s own counter
is wasted work; **re-probe before S2b starts**. (2) That `XCTMemoryMetric` reports a delta, not a
peak — decides whether the memory budget means anything. (3) `@Observable` tracking inside a
`Canvas` renderer closure — already named the highest-risk unknown. (4) The iOS 27 launch-screen /
UIScene / `UIRequiresFullScreen` / `ITMS-91055` items — cheap to honour either way. (5) The Swift
Charts CPU reports and the two-Canvas percentages — motivation only, asserted by nothing.

### Approval (2026-08-23) — and two things it changes

The user approved the plan at **seven slices** (keeping S5 here rather than splitting it into a
follow-up plan) and waived human review: *"don't wait for my check, I have to go, so do all qa
youself - or delegate to sub-agent and then check subagent report; keep working untill everything
is done"*.

**`pause_after` is therefore `[]`.** The four pauses existed to catch what no test can see. Waiving
them does not make those criteria pass — it makes them **unverified**, and every one of them is
reported as such in the ledger rather than quietly marked done. The affected criteria are: S3a acc 4
(truncation, `@ScaledMetric`, 44×44 pt targets), S3a acc 7 and S3b acc 10 (visual/appearance), S3b
acc 7 and acc 9 (Instruments CPU, per-body µs, device launch under 1 s).

**A second, harder constraint, found at approval time.** The machine has Xcode 26.6, Swift 6.3.3 and
the iOS 26.5 **SDK**, but `xcrun simctl list runtimes` is **empty** — no simulator runtime and no
device is installed. So iOS code can be *compiled* but not *run*. Blocked until a runtime is
installed: the chain's closing `xcodebuild … test`, S2b acc 3 (`XCTMemoryMetric`, app-hosted), and
S4 acc 4's on-device ICU assertions. Unaffected and fully runnable: S1 entirely, the whole
`SwimZHKit` package under `swift test` on the macOS host, `swift format lint`, `crap_swift.py`, and
`xcodebuild build -sdk iphonesimulator26.5` as a compile check. Work proceeds on that basis, and any
slice criterion that needs a runtime is reported blocked, never assumed green.

### Implementation-time corrections

**2026-08-23 — simulator destination is `iPhone 17`, not `iPhone 16`.** At worktree setup the
machine had Xcode 26.6, Swift 6.3.3 and the iOS 26.5 SDK but **zero simulator runtimes**, so no iOS
code could be run. `xcodebuild -downloadPlatform iOS` installed the iOS 26.5 runtime, which ships
the iPhone 17 family (17, 17 Pro, 17 Pro Max, 17e, Air) and **no iPhone 16**. The gate's destination
string is corrected. This also lifts the approval-time blocker recorded above: the chain's closing
`xcodebuild … test`, S2b acc 3 (`XCTMemoryMetric`, app-hosted) and S4 acc 4's on-device ICU
assertions are now runnable. What remains genuinely unavailable is a **physical device**, so S3b
acc 9's device launch measurement and the Instruments-based CPU/per-body checks stay unverified —
they are reported as such, never assumed green.

### S1 (2026-08-23) — what the slice proved, and three plan claims it corrected

**Verified, not asserted.** The critic mutation-tested the suite with 8 injected defects and every
one was killed: dropping `closure_code`, corrupting a session `end`, losing a horizon day,
suppressing the holiday warning, flattening `feature_key`, faking `lane_day.confidence`, shifting
the resolved day by +1. Acceptance 1b is genuinely proved — a test copies the store into a `0555`
directory at `0444` and **prepares and steps** a query, with a positive control that builds a real
WAL file and asserts the guard rejects it. The parity sweep is unsampled (400 dates × the full
roster) and guarded against passing vacuously.

**Three claims in this plan were wrong and are corrected here.**

1. **`BasinOut` has 11 fields, not 12.** The plan's S1 acceptance 3 said twelve; the twelfth was the
   `pool_id` foreign key, which is not one of `BasinOut`'s own fields
   (`apps/web/api/pools/model.py:95-111`). The export carries all 11 plus the FK, as intended — only
   the plan's count was wrong.
2. **6 lane-plan basins on the recorded fixture store, not 7**, and **1 notice, not the 9** the
   Context claims. The earlier figures were measured against live gold; the offline fixture store's
   coverage is thinner. Consequence carried forward: **S2's Swift golden test must not hard-code
   those counts.**
3. **Measured export: 5.00 MB, 11,886 sessions, 16,916 day rows, 271 warnings** — against the
   plan's projected 11,927 / 16,924. Same order, comfortably inside the 8 MB budget.

**`ANALYZE` always creates `sqlite_stat1`, even on an empty database**, so "the table exists" is not
evidence it ran — the guard counts **rows**. This is carried into S5's downloaded-store validation.

**The calendar debt is now visible at every build.** 269 of the 400 horizon days fall outside
`known_years: [2026]`; the CLI prints the count on every run. Seeding 2027 in
`data/calendar/zurich.yaml` remains owed before a first release.

### S2 (2026-08-24) — a green test that proved nothing, and what replaced it

**The slice's most valuable output was a deletion.** `failedOpenLeaksNoSQLiteMemory` claimed to be
the runtime proof that `Store` closes the handle `sqlite3_open_v2` hands back even on failure. It
could not fail. Apple's system libsqlite3 is built with `SQLITE_CONFIG_MEMSTATUS` **off**, so
`sqlite3_memory_used()` is identically 0 — verified independently by the orchestrator by leaking
2,000 failed opens:

```
baseline memory_used: 0
after leaking 2000 failed opens: 0
highwater: 0
leaked non-nil handles: 2000
```

Its own guard (`#expect(before >= 0, "MEMSTATUS must be on for this canary to mean anything")`) was a
tautology, because the API returns 0 rather than a negative sentinel when memstatus is off. The test
is deleted and **acceptance 7's first footgun is now documented as a structural (grep-only)
guarantee** — an honest weak proof beats a green test that proves nothing. Three metrics were tried
and all are dead ends on this platform, each named in `StoreTests`' header: file-descriptor counts
(a missing file allocates a connection and **no** descriptor), `sqlite3_memory_used` (memstatus
off), and `malloc_zone_statistics` (Swift Testing parallelises suites, so a process-wide delta is
other tests' noise). The grep was tightened to compensate: the close must be on the error path, a
second must exist for the deinit, and there must be **exactly one** `sqlite3_open_v2` call, so a
future second open path cannot ride on the first one's close. Residual tech debt, recorded: an
`if false { sqlite3_close_v2(candidate) }` would still satisfy a grep.

**The ghost-state hole was real.** Nothing pinned CLAUDE.md's load-bearing invariant on the client.
The critic mutated `Store.statuses` to `WHERE status = 'closed'` and the golden test **still
passed** — only the newly added `ghostStatusesSurvive` / `ghostStatesAreNeverDrawnAsClosed` caught
it. The committed store carries 2,520 `no_source` and 507 `open_unscheduled` day rows that the
golden fixture's three pools never exercise, so ghost coverage has to come from the store, not the
fixture. `TodayView.statusLabel` became a `static func` over `(status, closureCode)` so the
four-state mapping is drivable from a test.

**The golden test is not circular**, which was the main thing worth checking about a port. The
fixture is generated from `swimzh.domain.query.find_swim_options` — the *domain* — while Swift reads
the SQLite projection, so domain → export → Swift is closed by an independent oracle. Non-vacuity is
real: 75 `open_at_query_time=true` / 21 `false`, 10 distinct `(eligible, reason_code)` pairs, both
price brackets.

**Two client-side honesty rules with no Python counterpart**, both deliberate and both tested.
`SessionAccess.unknown` (→ "check with the pool", never "welcome") and `DayWarning.rendered`'s
default arm exist because the client reads a **store that can be newer than the binary** — which S5
makes routine by downloading one. `SeniorsOnly`/`AdultsOnly` now decode a missing `min_age` to
`.unknown` rather than falling back to `access.py`'s dataclass defaults: a domain default is not a
client assumption.

**Toolchain facts learned here, carried forward.** `isolated deinit` (Swift 6.2, macOS 15.4+) is
mandatory for any actor holding a C handle under strict concurrency — a nonisolated deinit cannot
touch a non-Sendable `OpaquePointer` at all, which is why the package platform is `macOS "15.4"` and
not `.v15`. The repo's `.gitignore` blanket-ignores `*.sqlite`, so a committed store needs an
explicit negation — **S5's downloaded-store work hits this same rule.**

**Unverified, and reported rather than assumed:** acceptance 5 (the app usable in Airplane Mode) is
a human check the user waived. The substitute is `SourceLintTests.noNetwork`, now recursive over
both targets and mutation-checked, proving neither target references `URLSession`, `Network`,
`NWConnection` or `CFSocket` at all. That is a strong structural claim, but it is not the criterion.

### S2b (2026-08-24) — a critic finding refuted on Apple's own evidence

**The dispute, and how it was settled.** The reviewer raised as *blocking* that
`PrivacyInfo.xcprivacy`'s `CA92.1` was the App Group reason and must become `54BD.1`. The
orchestrator fetched Apple's machine-readable payload directly
(`.../NSPrivacyAccessedAPITypeReasons.json`, retrieved 2026-08-24) rather than adjudicate on
recall. It says the opposite:

| code | meaning |
|---|---|
| **`CA92.1`** | "information that is **only accessible to the app itself**" — what this app does |
| `1C8F.1` | members of the same **App Group** |
| `C56D.1` | third-party **SDK wrapper** only |
| `AC6B.1` | **MDM** managed configuration |

`54BD.1` is not a User Defaults reason at all. **The finding was refuted and the code was not
changed** — applying it would have introduced the exact App Store defect the criterion exists to
prevent. Only the citation moved, from the rendered page to the JSON payload plus its retrieval
date. The lesson is sharper than the outcome: the reviewer cited the *same* JSON URL it recommended
because rendered Apple pages are unreliable, and still inverted two of the four codes. Per-code
quotations get re-read, never recalled. The plan's acceptance 5 requirement to verify in a browser
stands, and the manifest still asks for that check before the first upload.

**A real finding, taken.** The new Python tests were macOS-only but land in the **ubuntu** `qa` job
(`pyproject.toml:84` `testpaths` collects `tests/scripts/`; `qa.yml:9,29` runs `uv run pytest` on
`ubuntu-latest`) — the next push would have gone red. The trigger is subtle and worth recording:
`/bin/echo` on Linux is an **ELF** binary, and `ios_budget.is_macho` tests only Mach-O magics, so it
is counted as a *resource*, not code. Split into platform-independent arithmetic tests that still
run everywhere and macOS-only bundle tests behind a skip.

**Three measurements that change what later slices can assume.**

1. **`XCTMemoryMetric` is half-useless on Xcode 26.** It emits two sub-metrics:
   `XCTMetric_Memory.physical` (the delta) read **0.000 kB across all five iterations**, while
   `physical_peak` read 51.3 MB. The plan predicted "a delta, not a peak" — correct, and the useless
   half is the one it named. The gate is therefore a hard `task_vm_info.phys_footprint` assertion,
   with `XCTMemoryMetric` kept only as a loose ratchet.
2. **Half the memory budget is already spent.** One full 57-pool answer peaks at ~51 MB of the
   100 MB ceiling **before any UI exists**. S3a and S3b have far less headroom than the number
   suggests — exactly the kind of fact that is worthless discovered at the end.
3. **Size is a non-issue and the ratchet was a ceiling.** `app_minus_sqlite` measures **299,090 B**
   — 7% of the plan's 4 MB and 1% of the 30 MB the user set. The ratchet was tightened to **1 MB**
   (the plan's 4 MB kept as `plan_ratchet_bytes`), because a limit at 14× the measurement does not
   bite until the app is finished, which is the audit-at-the-end failure this slice exists to
   prevent.

**Toolchain facts that would silently break future tooling.** llvm-cov reports a function's start
line as the **body-brace line**, not the `func` line (`Store.answer` is declared at 143 and reported
at 149) — any join on the declaration line misses every multi-line signature. A Debug build puts the
real code in `SwimZH.debug.dylib` behind a 40 KB stub, so `size -m` on the executable alone measures
nothing; the proxy sums every Mach-O in the bundle. And `xcodebuild … test` copies ~8.8 MB of XCTest
support **into the .app**, so a size gate running inside the test command must exclude it — measured,
it put the proxy at 2.15× the whole ratchet.

**Divergence worth naming:** the app-hosted metric tests landed in the existing
`apps/ios/App/SwimZHTests/`, not the plan's `apps/ios/Tests/MetricTests/`. A SwiftPM test target
cannot import the app target, so the plan's path would have measured the test runner — the precise
mismeasurement acceptance 3 forbids.

### S5 must deliberately narrow the offline lint (found during S3a, 2026-08-24)

**A conflict between two slices, surfaced early rather than mid-implementation.** S2 shipped
`SourceLintTests.noNetwork`, which asserts that **neither** iOS target references `URLSession`,
`Network`, `NWConnection` or `CFSocket`. It is the structural substitute for S2's waived Airplane
Mode check and, as it stands, the strongest evidence the app is genuinely offline.

S5 cannot be implemented against it. S5's Touches name `Sources/SwimZHKit/Live.swift` (a Baditicker
client) and `Refresh.swift` (a manifest fetch), and its acceptance 1 requires the crowd and
temperature badges to render an explicit unavailable state — which presumes a network read that can
fail. The same conflict already shows in S3a's field coverage:
`FacilityDetailOut.live_water_temp` had to be omitted because no target may contain networking.

**Resolution, decided here so S5 does not discover it mid-slice.** S5 narrows the lint rather than
deleting it: networking is permitted **only** in `Live.swift` and `Refresh.swift`, and the lint
asserts that every other file in both targets is still clean — the seam becomes named and testable
instead of absent. S5's acceptance gains this explicitly, and any later file wanting a network call
must change the lint's allowlist deliberately, which is the point. If the user would rather keep the
absolute ban, the alternative is dropping live data from the plan; that is a scope decision, not one
to take quietly.

### S3a (2026-08-24) — one bug class, found twice, by grepping for a word

**The wall clock leaked across days, and no test could express it.** `listModel` took a
time-of-day but no reference day, while the strip offers the whole 400-day horizon. At 07:30,
selecting 2026-12-20 rendered **"Open now · until 09:00"** and counted the pool in "N open to you";
at 22:00 every future day read **"Done for today"**. The web had already solved this —
`api.ts:90` pins `DAY_MOMENT = "T12:00"` for any non-today date — and the Swift port simply had no
notion of "today". The tell was that the failing case **could not be written**: the function took no
argument that would let a test state it.

**The orchestrator's first fix instruction was wrong, and the implementer said so.** Substituting the
web's fixed 12:00 moment is *not* sufficient: at 12:00 a 06:00–09:00 session still tiers `.past`
("Done for today") and an 11:00–13:00 one still tiers `.now` ("Open now") — both false for a future
date. The correct fix removes clock tiering entirely off-today (a sixth tier `scheduled`, "Open that
day", with `openToYou` forced false), and keeps the 12:00 moment only for the *store query* so
`openAtQueryTime` still matches the web. Recorded because the rebuttal was right and the reasoning is
the reusable part.

**Then the same bug turned up one layer down, from the same technique.** A grep of the *app* target
for temporal wording found `"+2 more today"` rendering on `.scheduled` rows. The implementer ran the
same grep over the *kit* and found `dayStateLabel(.closed(.noSessions))` returning **"Closed
today"** — and ghost/closed rows are built with no reference to which day is today, so the string
was reachable on ninety-odd future dates in the committed store. Now "Closed — no sessions", which
is what the closure code actually says and is true on whatever day the row belongs to.
`stateLabelsAreDayAgnostic` pins the whole family. **The exposure is structural and S3b/S4 inherit
it**: session rows are day-aware, ghost and closed rows are not, so any new sentence must be checked
against both.

**Two more defects nothing else would have caught.** `today` was captured once at load, so an app
left open across midnight kept treating yesterday as today — the "Today" chip pointed at the day
before and clock tiers resumed on a stale day. And `TodayView.statusLabel`, a pass-through shipped in
S2, had drifted from the row's own path on the `unmapped` arm: it said "reason not classified" while
the list quoted the pool's own words. It was **deleted**, not repaired — a second path to one mapping
is what produced the drift, and after the deletion the app target contains no state-to-string logic
at all. **S3b should preserve that condition as it adds the canvas.**

**A hole in the field-coverage mechanism, used at introduction.** The union/disjointness test proves
every field is *classified*; it can never prove a `rendered` claim is *true*. Five fields were
declared rendered that the phone structurally cannot render — `SwimOption` carries no `source`,
`curated` or `validAsOf` at all — and one omission reason then rested on that false claim. Four moved
to `deliberatelyOmitted`; `detail_params` was made genuinely rendered instead, so the comment
promising the pool's own words is now true. Three fields are pinned by name in
`renderedClaimsAreNotAspirational` because **no general mechanism exists**. S3b moves five more
fields into `renderedFields` and carries exactly the same exposure.

### S3b (2026-08-24) — the eighth defect, found twice, and two reviewer findings overturned

**The bug class reached a derived value, not just a label.** `lane_availability` is the split at the
**queried instant**, so at 04:00 a session opening at 06:00 rendered "no lanes open to the public"
beside "Opens 06:00" — two true statements composing a false impression. Found on a simulator
screenshot, not by a test.

**Then the fix was found to be half a fix.** It branched on `openAtQueryTime`, which is pure
time-of-day containment — but `TodayModel` queries the store at a fixed **12:00** for every non-today
day, so off-today that flag means *"covers midday"*, true for essentially every long session. Traced:
`hallenbad-city`/`city-50m` on 2026-09-07 runs 06:00–22:00 with **5 of 6** public lanes at 12:00 and
**6 of 6** at its 06:00 opening — a row two weeks out printed the wrong number. The tell was that
`a11yFacts` already used the opening split, so **the spoken fact and the printed line disagreed on
the same row**. `laneSummary` now takes `isToday`, and the test derives `openAtQueryTime` from the
same `time` it reads availability at, so the coupling cannot be decoupled by a literal again.
**Carry-forward: `at:` is meaningless off today.** A full sweep found one latent instance left
(`LanePlan.swift:471`, reachable only for a zero-length session, of which the store has none).

**Two reviewer findings were overturned on the code, and the reviewer conceded both.**

1. The proposed store-backed weekday assertion was a **tautology**: `Store.laneDays` never reads the
   `weekday` column — it passes the queried weekday *into* `LaneDay.decode` — so
   `laneDayView?.weekday == weekday(of: day)` compares a value with itself. Reviewer's words: *"My
   finding named the right gap and the wrong instrument."* The replacement is independent: a
   `DateFormatter` oracle over 366 days, an eight-day table covering the Sunday→Monday wrap, and a
   store-backed comparison of the served **strips**. It has teeth because `city-50m`'s seven weekday
   strip blobs are pairwise distinct, so a ±1 shift changes the answer on every day.
2. "Delete the unreachable `drawLanes`" was refused with cause: `RibbonCanvas.draw` has
   `default: drawUnpublished`, so deleting the `lanes` arm routes a `lane_count = 0` row — which the
   export schema permits — to **"split not published"** for a basin that did publish one. The exact
   lie the ribbon vocabulary exists to prevent. Reviewer: *"my finding failed its own 'name a cost
   that disappears' test on this branch."*

**A test that could not fail, again.** `tapAtMidpointOnARealDay` asserted `hit.width <= expected.width`
— but `block(at:)` returns the *narrowest* containing block and a block contains its own midpoint, so
it was a theorem, not a test. Now asserts exact identity, restricted to blocks whose `(x, width)`
frame is unique in the row, with the count floor on the filtered set. **1-D hit-testing genuinely
cannot distinguish two basins with identical hours** — a product limitation, now stated rather than
hidden behind a passing assertion.

**Measurement correction worth keeping.** Xcode's memory readouts labelled "MB" are **KiB scaled by
1000**: its "63.55 MB" is 65,077,750 B = 62.1 MiB. Both `budgets.json` entries recorded the
mislabelled figure. Real headroom against the 100 MB ceiling is **38%**, not 36%.

**Two generated contracts had no staleness gate** — editing `domain.access.ACCESS_TYPES` would have
left the fixture stale, the Swift test passing, and the two copies drifting together, which is
precisely what the module header said it prevented. `test_ios_fixture_contracts.py` now gates both,
and the reviewer probed it with six independent mutations rather than reading it.

**`lane_plans.json`'s "49 cases over 7 basins" is really two distinct plans.** All six real basins
share byte-identical strips (one recorded cassette); the seventh is synthetic, and is the only source
of `partial == true` anywhere. Also: the plan's Context says 7 lane-plan basins; the store has **6**.

### S4 (2026-08-24) — a gate that regenerated what it was about to check

**The parity gate could not fail, in two independent ways.** All four teeth-bearing tests carried
`@needs_dist`, `apps/web/static/dist/` is git-ignored, and neither CI job that runs them builds it —
so in CI they **skipped**. Locally it was worse: `make ios-qa` ran the *writing* target first, so the
staleness check compared the generator's output against the generator's output. A contributor could
edit a sentence in `en.ts` — the declared single source of truth — and ship a phone catalog saying
the old thing with all three chains green.

Verified fixed by mutation, not by reading: changing `tier.scheduled` in `en.ts` without
regenerating now yields `stale, regenerate with …` and exit 1; restored, `up to date (409 keys)`.
The writing target is now invoked by **no chain and no CI step**. The gate's rule is worth keeping:
**a step that regenerates a file before checking whether it is stale makes that check unfalsifiable
— build, then check.** That is the third gate in this plan that looked enforced and was not.

**Six raw ISO dates reached readers in five languages, found over three rounds.** `2026-08-24` where
the web renders `24 sierpnia 2026`. Rounds one and two found three, then two more on the facility
sheet (live on all 21 priced pools). The sixth is the instructive one: `DayWarning`'s `{date}` param,
missed because the first sweep **sampled** days at offsets 0/45/120 and the store's only
`holiday_hours_unverified` warning is Christmas Day — three days outside every sample. Both sweeps
now walk the **whole horizon** in all five languages, and the tests say in-comment why: *a sample is
a guess about where the bug is.* The counts in the comments were dropped rather than corrected —
they went stale twice in two rounds.

**The plural guarantee is restored by a build phase, because Xcode cannot provide it.** There is no
build error and no documented warning for a missing plural category: a missing Polish `many` falls
back to `other`, the *decimal* form — exactly the broken grammar `plurals.ts` exists to prevent.
`scripts/xcstrings_plural_gate.py` runs as the app target's **first** phase, walks all 409 keys × 5
locales, requires category-set **equality** with CLDR, and was proven by deleting Polish `many` and
watching `** BUILD FAILED **`.

**Four Apple facts that would each have shipped a wrong app.**
1. `String(localized:)` **never expands a plural** — it returns the raw `%#@value@` token. Only
   `String(format:)` expands it.
2. `String(format:locale:)`'s `locale:` drives **plural-rule selection**; the **bundle** drives the
   language. Setting one without the other renders Polish words with English grammar. (The plan
   flagged this as unverified and load-bearing; it is now measured.)
3. **SwiftPM does not compile `.xcstrings`** — `swift build` copies raw JSON and
   `Bundle.module.localizations` reports only `["en"]`. Xcode does. The package tests compile it with
   `xcstringstool` themselves.
4. A `zero` key in a compiled `.stringsdict` is Apple's **literal-zero special case**, not a CLDR
   category — returned for n=0 in every language. The catalog deliberately does not use it.

**An honest platform divergence, recorded in five places.** Apple's ICU renders fr-CH with a **dot**
where node's uses a **comma** (measured on both). So a French-Swiss reader sees `2.5 km` on the phone
and `2,5 km` in the browser. The tests assert each platform's own truth rather than hand-formatting
around it; `CLAUDE.md`'s i18n section, both file headers and both test suites now say so, with an
explicit *do not hand-format either side*.

**Three source bugs fixed in passing**, none of them in the acceptance criteria: `Format.length`
lacked `usage: .asProvided`, so en-GB rendered a 12.5 m basin as **"41 ft"**; `featureHours`
interpolated a clause **key**, rendering "Closed — closureClause.out_of_season"; and the six raw
dates above.

### S5 (2026-08-24) — a brick that had not happened yet, and a claim nothing was checking

**The most serious defect of the plan is one that could not fire today.** `StoreHost.store()`
adopted an *installed* store after probing `metadata()` — which reads only the `meta` table and so
**always succeeds for a well-formed store of any version**. Acceptance 2's version guard was enforced
on the *download* path only. Not reachable with today's binaries, because no released build has ever
written an installed store — but this slice **bumped the schema 1→2**, so it goes live at the next
bump: a phone carrying a downloaded v2 store updates to a v3 binary, adopts a store the code cannot
read, and every detail read throws `no such column`. `TodayModel:116` swallows it with `try?`, so the
user gets a **spinner that never resolves, with nothing logged** — permanently, while offline. That is
exactly the brick `appStoreSchemaVersion` exists to prevent. Fixed by gating adoption on the version
and proven by neutering the guard: the test fails with precisely that mechanism.

**A `rendered` claim outran its evidence for the fourth time — and this time the hole was general.**
`live_water_temp` moved into `renderedFields` citing a `rowEvidence` entry that **did not exist**.
The mutation check is the finding: deleting the entry left the suite **green**, because the sweep
iterates `rowEvidence`, so any claimed field missing from it was silently unchecked. Three other
fields could have drifted the same way. `everyClaimedSheetFieldHasEvidence` now forces "this field
has no row evidence" to be something a human writes down.

**A scope reduction that is correct and must not be undone.** The crowd/occupancy badge is
**unbuilt**, and the reason is an owner decision recorded twice in the tree, not a missing adapter:
`data/sources.md:18` defers CrowdMonitor as *"Commercial; ToS unclear … Deferred until vendor terms
verified"* with an open action at `:70`, and `docs/2026-08-02-gold-coverage-gaps.md:474-481`
explicitly dropped deriving the crowdmonitor uids because the registry keys are display names rather
than protocol uids — building for them *"would quietly advance an integration deferred on legal
grounds."* The client therefore renders **no row at all**: a permanent "unavailable" row would imply a
source that does not exist. Water temperature (Baditicker, OGD, no ToS gate) is implemented in full
and was proved against the **live feed fetched that day**, not only the cassette.

**The offline guarantee survived contact with a network client.** `noNetwork` became a **path-keyed
allowlist of exactly `Live.swift` and `Refresh.swift`** — so `App/Live.swift` and
`SwimZHKit/Sub/Live.swift` both fall outside — with the lint still asserting every other file in both
targets is clean, and a mutation test covering a view fetch, a kit fetch and a name-squat. Narrowing
the lint rather than deleting it is what keeps "this app works offline" checkable.

**"Opening is not reading", one layer up.** A test caught `StoreHost` adopting an installed store
that merely *opened*: `sqlite3_open_v2` is lazy, so junk and WAL files pass and fail on the first
query — the same trap S1 recorded for the bundled store.

**An honest refusal.** The reviewer's suggestion to fix `baditicker.py:120` (which reads any
unrecognised open/closed wording as **closed**, against its own docstring) was declined with cause:
it changes what the **web** reports for wording that has never appeared in the feed, and wants its own
review. Instead the shared assumption is pinned by a vocabulary test beside the Python code, which
fails the day that input becomes real. The divergence — Swift answers *unknown*, Python answers
*closed* — is documented in three places.

## Accepted drift

Findings the user has knowingly blessed, so `/dev:present` folds them into a
count instead of re-listing them every run. See [[accepted-drift]]. Ships empty:
rows are added by the human, or pasted from what `/dev:present` prints — never
by the command itself.

**Append-only, like the ledger.** Rows are added, never edited or deleted; a row
that stops applying is reported as stale, not removed.

`kind` is the bare word — `DROP`, `SUB`, `INV` — never the rendered symbol
(`− DROP`). `key` is `intent:+<n>`, an offset counted from the
`## Intent (verbatim)` heading line (offset 0), never a file line number.
`+ ADD` findings have no Intent phrase to anchor and cannot be accepted.

| kind | key | why | date |
|------|-----|-----|------|

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|
| 2026-08-23 | S1 | done | `feature_key` gains a deterministic `#n` suffix on a repeated kind (a bare `kind` violates the plan's own PK); `ExportReport.uncovered_days` additive; `days < 1` returns `Err` not a raise; gate destination iPhone 16→17 (orchestrator, machine has no iPhone 16) | `day_warning` re-resolves every facility per date — a second resolver pass beside `find_swim_options`, ~2× sweep cost (0.5 s total); `render_warning` has no unknown-code arm and would `KeyError` on missing params | **yes — 3 unverified plan claims corrected, see Decisions** |
| 2026-08-24 | S2 | done | `Store` is an actor not a struct; `priceFor` returns `PriceEntry?` (the plan's `Admission` was the wrong type); `eligibility(person, access)` argument order; added `SessionAccess.unknown`; strict `min_age` decoding; extra files beyond Touches (committed 1.75 MB store, `scripts/ios_fixtures.py`, app-hosted test target); acc 7's open-failure proof is **structural only** | no runtime proof of the open-failure close (grep only — no metric on Apple's SQLite can observe it); committed store is a **140-day** horizon, not 400; the store is not byte-reproducible (`gold_valid_as_of` moves with the wall clock); `DayWarning.rendered` duplicates Python's renderer; `/swim` still omits `min_age` | **yes — acc 5 (Airplane Mode) UNVERIFIED, human check waived** |
| 2026-08-24 | S2b | done | metric tests landed in the existing `App/SwimZHTests/`, not the plan's `Tests/MetricTests/` (a SwiftPM target cannot import the app — the plan's path would measure the runner); size ratchet enforced by a Run Script build phase, not a test (the `.app` exists only inside `xcodebuild`); `app_minus_sqlite` ratcheted to **1 MB**, tighter than the plan's 4 MB; `scripts/ios_budget.py` + `tests/scripts/**` required by acc 4 but absent from Touches | size proxy is the **Debug** build, not the release/thinned figure; `escaped_bodies` reports but does not score a closure-valued property (refactor to a `func`, do **not** edit the `escaped == []` assertion); `MemoryMetricTests` restates the 100 MB ceiling (joined by a string-match pytest, not a generated constant); no `XCTMemoryMetric` baseline (baselines do not travel across device configurations) | **yes — `CA92.1` documentation-verified but still not browser-eyeballed before first upload** |
| 2026-08-24 | S3a | done | `stripLayout` takes a kit-local `TypeSize`, not SwiftUI's `DynamicTypeSize` (the kit may not import SwiftUI — an existing lint forbids it), bridged by rank and pinned case-by-case; a **sixth tier `scheduled`** and a **fifth day state** added so an off-today answer makes no wall-clock claim; `.closed(.noSessions)` reworded from "Closed today"; `TodayView.statusLabel` (shipped in S2) **deleted** rather than repaired; many files beyond Touches, all forced by "logic goes in SwimZHKit" | `app_minus_sqlite` 299,090 → 686,442 B (headroom 3.5× → 1.5×; `budgets.json` untouched as gate configuration — S3b will likely need it raised deliberately); every filter change, search keystroke included, re-queries the store; `Tier.scheduled`'s verdict shows the day's outer span only, so a long midday gap reads as continuous; `renderedFields` proves drift detection, not that a pixel is drawn | **yes — acc 4's visual half and acc 7's appearance check UNVERIFIED (waived human checks); nothing has looked at a screen** |
| 2026-08-24 | S3b | done | `laneSummary` is a **function taking `isToday`**, not a computed property; `ribbonmodel.ts` (the **production** module, not just its test) gained `NO_SPLIT_LABEL_KEY` + `label_key`; size ratchet raised **1 MB → 2 MB** deliberately (measured 1,339,498 B, still half the plan's 4 MB); files well beyond Touches (`PoolBrowser`, `AccessExplainer`, `FacilityDetail`, 20 colorsets) forced by "every rule lives in SwimZHKit" | `RibbonCanvas.drawLanes` is unreachable against today's export and kept **with a recorded reason** (deleting it would render a `lane_count = 0` basin as "split not published"); `Ribbon.segments` always nil in the shipped app, so its a11y fact is dead in production; `noDomainTokenComparisonsInTheApp` enumerates six tokens **by hand** with no mechanism keeping the list honest; per-basin lane panel still inert for scraped pools (CLAUDE.md's flat-scrape limitation); `LanePlan.swift:471` is a latent off-today instant claim for a zero-length session (no such row exists today) | **yes — acc 9's device budgets and acc 10's notched/light-dark check UNVERIFIED (no physical device; waived)** |
| 2026-08-24 | S4 | done | five web catalogs gained 198 keys each (409 total) — the web stays the single source for every sentence, iOS included; `DayWarning.message` now takes a `Format`; an absent stamp is **no row**, not a labelled blank; `UIMark.voiceOverLabel` moved into the kit; `panel.clubSlot` split into two non-plural keys (xcstringstool refuses a plural whose forms do not interpolate the number); CI workflow edited (`setup-node` + `npm ci` + the locale check on `ios-qa`); files far beyond Touches | `app_minus_sqlite` **1,908,758 B of the 2 MB limit — 91% used, 188 KB headroom**; S5 will need the deliberate step to 4 MB. `Format.swift:153` uses `Date.AttributedStyle`, deprecated in macOS 15. `ZurichClock.instant` **rolls over** out-of-range components (`2026-13-45` → 14 Feb 2027), so a corrupt store shows a plausible wrong date. `Localized` is `@unchecked Sendable` around a `Bundle`. Polish plural `other` forms are fraction-genitives not reviewed by a native speaker. `noSentencesInTheApp` needs ≥2 words, so a one-word literal plus a hand-written allowlist entry passes both lints | **yes — Polish/German wording unreviewed by native speakers; fr-CH renders differently on phone vs web** |
| 2026-08-24 | S5 | done | **NO crowd/occupancy client — the source does not exist** (`data/sources.md:18,70` defers CrowdMonitor pending vendor terms; `docs/2026-08-02-gold-coverage-gaps.md:474-481` dropped the uid derivation as it would advance a legally-deferred integration). Half of acc 1 is **unbuilt, not degraded**, and renders no row rather than a false "unavailable". Export `SCHEMA_VERSION` bumped 1→2; `Store.close()` added (the Design had none — `replaceItemAt` with an open fd serves the old inode silently); `DetailRow.muted` added; size ratchet raised **2 MB → 4 MB** (measured 2,088,982 B, 99.6% of the old limit) | refresh path is **INERT in the shipped build** — no `SWIMZHStoreManifestURL`, hosting out of scope; `make ios-release` unexercised end to end; `LiveClient` caches a FAILURE for the same 2 min as a success; `baditicker.py:120` reads any unrecognised open/closed wording as **CLOSED**, against its own docstring (Swift answers UNKNOWN — the honest side; pinned by a vocabulary test, Python bug real and unfixed); `builtAt` compared as a **string**, mis-sorts across a DST offset change (fails safe); `TodayModel:116`'s `try?` silently swallows any future store error | **yes — nobody has SEEN the live-water row on screen in any state or language; the new muting is a flag and a lint, not a pixel** |

## Decisions & divergences

Substantive choices made during implementation, with the why. Each entry dated.

**2026-08-23 — bake, don't port (chosen by the user).** The resolver is the correctness core. The
seven modules that answer "what is open on date X" total 2,055 lines inside a 3,076-line `domain/`
package. Porting them to Swift would create two copies that must agree on every weekly data change.
Baking every in-horizon date in Python keeps one source of truth and leaves Swift with the
person/place/clock logic, whose parity is enforced by generated fixtures.

**2026-08-23 — bundle + optional refresh (chosen by the user).** App Store review lag and users who
do not auto-update would otherwise serve month-old hours with no remedy. The bundle stays the
offline floor; the manifest is a strictly optional improvement whose every failure mode is a no-op.

**2026-08-23 — `lane_day` is keyed by weekday, not date.** A Belegungsplan is a weekly plan; keying
it by date would multiply the largest payload in the export by ~400 for no new information.

**2026-08-23 — no `price` table.** The tariff bracket depends on the person, so the pool's whole
tariff doc rides as JSON and `priceFor` picks the bracket in Swift, mirroring `pricing.price_for`.

### Pre-approval review (2026-08-23, plan-critic, verdict: revise → addressed)

The adversarial review returned 10 blocking findings; all 10 are taken. Each changed the plan:

1. **`notices` / `warnings` had no home in the schema** while `Answer` claimed to mirror the full
   result shape — and both are date-resolved (`query.py:600`, `:581`, `:688`; 8 notice-days and
   2 warning-days in a 131-day horizon). Added `day_notice` and `day_warning` tables, added them to
   S1's parity criterion, and gave S3a an acceptance criterion that both surface in the UI.
2. **S3's facility detail was unservable** from the schema — `FacilityDetail` carries features
   (whose hours are date-resolved by `_feature_status`, `query.py:744`), lockers, rentals, basins.
   Added `pool_basin` / `pool_locker` / `pool_rental` / `pool_feature` / `feature_day`.
   (`feature_day` was cut again in round 2 — see R2-4; the rest stand and were widened.)
3. **The binding signature could not reach what it needed.** `GoldRepository` exposes only
   `load_all`/`get`/`count`; the calendar, roster and aliases are module functions over the
   connection, and without the roster the `day` table would be empty for every schedule-less pool.
   `export_ios` now takes `sqlite3.Connection`. `ExportReport` is now defined, not just named.
4. **S1's parity criterion named a surface that does not exist.** `find_swim_options` returns domain
   `SwimOption`/`FacilityStatus`, not the pydantic `OptionOut`/`StatusOut`, and `OptionOut` has no
   `access_params` (the API flattens access to a class name, `swim/service.py:129`). The criterion
   now names the domain layer, the exact `SwimQuery`, the exact field tuples, and states which
   fields are deliberately excluded and where they are covered instead.
5. **A false claim about the fixture.** The 440 cases carry only `{access, gender, age, allowed,
   code, ui}` and are drawn from a fixed `REPRESENTATIVE_ACCESS` list (`access.py:205-218`), so the
   parameterised arms were never pinned — although live data carries 53 `AdultsOnly(min_age=18)`
   options in 60 days. The claim is corrected and S2 now widens the generator to emit
   `access_params`, which also improves the existing browser test.
6. **E2 was stricter than the web and had a year-end cliff.** The web serves 22 real options for
   2027-01-05 with a warning; withholding them on iOS would be a regression dressed as honesty.
   E2 now bakes a fixed 400-day horizon and carries the identical warning, with the calendar-reseed
   obligation made visible by S1 acceptance 4.
7. **The gate could not run half the criteria.** `swift test` covers the package only, S2's
   "no simulator" and "in a simulator" criteria contradicted each other, and the only CI runner is
   `ubuntu-latest` (`qa.yml:9`), where SwiftUI cannot build. The gate now names the `xcodebuild`
   destination and a `macos-latest` job; `.xcstrings` moved into the package; the simulator check
   is explicitly a human pause-gate eyeball. `swiftlint` is dropped for Xcode's own `swift format`,
   removing the "no third-party dependency" contradiction (runtime vs dev tooling now stated).
8. **S3's "checklist test" was aspirational** — no test parses a markdown table. Replaced with a
   generated `field_coverage.json` and a Swift `renderedFields` / `deliberatelyOmitted` pair the
   test asserts against, which also mechanically enforces the S3a→S3b handover of the lane fields.
9. **Two criteria depended on fixtures no slice produced.** S1 now lists the parity fixture path and
   its `SWIMZH_REGENERATE_IOS_PARITY` command; S3b now makes `ribbonmodel.test.ts` emit a committed
   golden.
10. **S3 was the whole UI (2,898 lines of TypeScript) under one gate at `max_rounds: 2`.** Split
    into S3a (list, filters, states — observable alone) and S3b (canvas, lane stack, detail).

Suggestions also taken: the parity sweep runs **unsampled** (measured 0.09 s, so sampling would be
premature); the size budget tightened from a vacuous 20 MB to 8 MB with the actual size printed;
`session.source`/`session.curated` dropped in favour of the facility-level columns; the locales
converter is node rather than a Python TypeScript parser; S4 gained the anti-vacuity literal lint;
S4's inspection criterion became a grep; S5's mid-write-kill criterion became a contract +
cleanup assertion; the CLI is written in its real `python -m swimzh.cli` form; and the overstated
line counts ("the resolver … is 3,000 lines" — it is 166) are corrected throughout.

### Pre-approval review, round 2 (2026-08-23, plan-critic, verdict: revise → addressed)

Round 2 confirmed 7 of the round-1 fixes and found 7 new blocking findings. All 7 are taken; the
plan is handed to the user at `gates.max_rounds: 2` without a third round.

**R2-1 — the parity criterion reintroduced the very defect it was written to remove, twice.**
`FacilityStatus`'s fields are `code` / `closure` / `params` (`query.py:321-338`), not the pydantic
`detail_code` / `closure_code` / `detail_params`; and the real signature is
`find_swim_options(query, facilities, calendar, roster=(), *, occupancy=None)` (`query.py:564-570`)
— the criterion had roster and calendar transposed, which would pass a roster where a calendar is
expected. Both corrected, and the export's column-name mapping is now stated explicitly.
(Verified fine and recorded so it is not re-checked: `dataclasses.asdict(session.access)` succeeds
on all 11 arms of the frozen/slots union.)

**R2-2 — `lane_day` could not reproduce `partial`.** `lane_availability_at` derives it from
`PlanCoverage.unresolved_lanes` (`lane_plan.py:159`, `:56-68`), which the table did not carry, while
`partial` is a rendered field on `LaneAvailabilityOut` and `LaneTimelineSegmentOut`. Added
`unresolved_lanes` + `confidence`, and S3b's fixture must now exercise a basin that has them.

**R2-3 — the facility detail was still unservable.** `pool_basin` supplied 6 of `BasinOut`'s 12
fields; `operating_season` had no column at all though 13 of 57 pools declare one (measured); and
`FacilityDetailOut` sat outside the coverage mechanism, governed by prose. All three closed.

**R2-4 — `feature_day` was new gold-plating that ships empty.** Measured: all 9 features across all
57 pools have `hours=()`, so `_feature_status` (`query.py:744`) returns `schedule=None` for every
one and a 400-day × 57-pool sweep produces **0** rows. The table is cut; feature hours ride inside
`pool_feature.doc`, which needs no schema change if a feature with hours ever appears.

**R2-5 — the coverage fixture had no staleness gate.** The `eligibility_contract.json` pattern's
teeth are a *pytest* asserting the committed file still matches the models
(`test_eligibility_ui_contract.py:16-19`); S3a listed only a Swift test, so adding a field to
`OptionOut` would have failed nothing. Added `test_field_coverage_contract.py` and
`SWIMZH_REGENERATE_FIELD_COVERAGE=1`.

**R2-6 — S4's lint would have banned the correct SwiftUI idiom.** A literal in a
`LocalizedStringKey` position *is* the key, so "no user-visible literals" forbids right code and
misses the real failure mode. Restated as a key-resolution check plus a `Text(verbatim:)`
allowlist; acceptance 5's undecidable grep became a decidable ban inside `Format.swift`.

**R2-7 — the gate's `xcodebuild` could not run.** With the project at `apps/ios/App/`, `xcodebuild`
with no `-project` searches a cwd holding only `Package.swift`. Added
`-project App/SwimZH.xcodeproj` and the requirement that the scheme be **shared**. The gate's
folded-scalar comments (which `yaml.safe_load` swallowed into the command string) moved into a
separate `swift_chain_notes` key.

Round-2 suggestions also taken: the measured row counts replace the invented ones (11,927 sessions
and 16,924 day rows, not "~10k and ~23k"); the sweep-cost citation is restated for 400 dates
(~0.3 s, still unsampled); the E2 measurement is recorded in the Design so it is not re-litigated,
including that the calendar reseed is **overdue on day one** (269 of 400 days already warned), not a
future chore; `renderedFields` is labelled drift-detection rather than a rendering proof; the S3b
port surface is named (seven functions, ~150 lines of `lane_plan.py`) since it is more than the
"person/place/clock logic" the Decisions row implies; and the concept stub's stale
"calendar's known horizon" sentence is corrected.

Confirmed fine, recorded so it is not re-litigated: `scripts/field_coverage.py` importing the
pydantic models creates no import-direction problem (`apps/` is a package and `apps/web/tests/**`
already imports it; the model modules import pydantic only) — with the one caveat, now written into
S3a, that it must never import `apps.web.main`. `swift format lint --strict --recursive Sources
Tests` is a correct invocation. The 8 MB budget is comfortable at ~29k rows.

Suggestion **not** taken across both rounds: none.

### Non-functional requirements round (2026-08-23, grounded research)

The user added delight/native-iOS-26, testing, CRAP, memory, CPU, sub-1s launch and a size ceiling.
Rather than assert iOS 26 API names from memory, they were verified against the installed SDK's
`.swiftinterface` files, Apple documentation and WWDC sessions, and several claims were measured
locally. Four findings changed the design; several corrected things this plan or the prompt had
wrong.

**N1 — a WAL-mode SQLite cannot be read from the app bundle, and it fails LATE.** Verified
empirically: `sqlite3_open_v2` returns **SQLITE_OK** and the first *prepare* fails with
`SQLITE_CANTOPEN`. WAL needs sidecars, a writable directory or `immutable=1`; a bundle offers none.
Without this the app would have shipped and failed on every device at first query while every
"does it open?" test passed. S1 acceptance 1b now asserts the DELETE journal byte, the absent
sidecars, and a *prepare-and-step* from a read-only directory.

**N2 — SwiftLint is disqualified as the CRAP complexity source.** Measured on probe files: it counts
from **0** rather than McCabe's 1 (so untested straight-line code scores `crap = 0` forever), counts
neither `&&`/`||` nor ternaries (a 9× swing in the squared term), is **`func`-only** so it cannot
see a `var body`, and exposes the number only inside a prose string. Meanwhile llvm-cov *does* emit
computed-property getters as functions — the two tools would disagree about what a function is,
exactly where SwiftUI complexity lives. The complexity source is a SwiftSyntax walker in a dev-only
tools target. This also reverses round 1's "swiftlint dropped" line for a better reason than the one
given then: it is not merely an unwanted dependency, it is the wrong measurement.

**N3 — `Canvas` has zero VoiceOver accessibility, by Apple's explicit statement.** Promoted from an
unstated assumption to an S3b acceptance criterion (`accessibilityChildren`), with the time→x
mapping factored into one pure function shared by renderer, hit-test and a11y layout.

**N4 — `if expanded { … }` inside a `ForEach` element defeats `List` laziness for all 57 rows**
(WWDC23 10160: a variable number of views forces List to build every body just to learn the
identifiers). The obvious implementation of the expandable Gantt is the anti-pattern. S3a now
asserts it with a build counter.

**Corrections to names this plan or its prompt had wrong**, recorded so they are not reintroduced:
`GlassEffectID` **does not exist** (use `@Namespace`); the search behaviour member is **`.minimize`**,
not `.minimized` (Apple's own doc sample uses the wrong spelling); `Tab`, `matchedTransitionSource`
and `.zoom(sourceID:in:)` are **iOS 18**, `sensoryFeedback`/`symbolEffect` **iOS 17**, and
`Canvas`/`TimelineView` **iOS 15** — none is new in 26, so none justifies the deployment target;
the glass family lives in **`SwiftUICore`** and is unavailable on visionOS; `drawingGroup()` on a
Canvas is **harmful**, not an optimisation; `XCTMemoryMetric` reports a **delta, not a peak** and is
meaningless against an `XCUIApplication`; and the App Store executable limit is **80 MB of `__TEXT`**,
not the 500 MB figure in circulation.

**Deployment target is iOS 26.0, not 27.** iOS 27 is in beta; Apple states Liquid Glass apps get its
refinements *"automatically… without even needing to recompile"*. Nothing in this plan is bet on 27,
though four of its forced changes (launch screen, UIScene lifecycle, `UIRequiresFullScreen` ignored,
ODR deprecated) are free to honour now and are folded into S2 acceptance 10.

**Budgets are honest about what CI cannot measure.** Launch time is a **device** check at a pause
gate: Xcode stores performance baselines per device configuration precisely because they do not
travel, and no published simulator-variance figure could be found. The size budget is measured on
the **thinned compressed download** parsed from `app-thinning.plist`, never the `.app`/`.ipa`, and
tracked as two numbers so a data refresh cannot mask a code regression. Measured context for why the
30 MB ceiling is not in play: a stripped hello-world SwiftUI binary is ~71 KB and a 2,771-line
synthetic app ~127 KB, so the ratchet is set at 4 MB rather than the ceiling.

**Known-unknowns, carried deliberately rather than guessed.** Each is a first-week probe, not an
assumption the design rests on: whether `@Observable` tracking reaches inside a `Canvas` renderer
closure (if it does not, the ribbons will not redraw on model change — the single highest-risk
unknown); whether `TimelineView` self-pauses when backgrounded or off-screen (so `paused:` is passed
explicitly regardless); whether `String(localized:locale:)` drives plural *selection* or only number
formatting; the `.xcstrings` JSON format (no Apple spec — pinned by a golden file); the de-CH/it-CH
separators *on iOS* (CLDR-verified only, so asserted in a simulator test); and whether UI-test
coverage collection works from the CLI (reports of 0% where Xcode reports fine — to be verified
empirically, which is a further reason UI tests stay out of the blocking gate).

**Two App Review facts worth knowing before, not after.** Guideline **4.2 Minimum Functionality**
is the real risk for an app over public data — *"beyond a repackaged website"* — which the offline
store, eligibility filtering and radius query answer directly. Guideline **5.2.2** requires being
specifically permitted to use the source data: `data/sources.md` is exactly the artifact to have
ready, and the app must not use the city crest or a name resembling an official one.

 The critic's "verified, no action needed" list is recorded here so
it is not re-litigated — `storage/atomic.py`, `domain/geo.haversine_km`, `domain/pricing.price_for`,
`apps/web/static/js/locales/*`, `datefmt.ts`, `blocks/ribbonmodel.ts` and `eligibility.test.js` all
exist as claimed, "57 pools, 26 carrying 224 rules" is exact, and `lane_day` is not inert.

## Summary

**What exists now.** `apps/ios/` is a native SwiftUI app for iOS 26 that answers "where can I swim
in Zürich?" entirely offline, from a SQLite file it carries. Seven slices, all seven green, three
QA chains (Python, TypeScript, Swift) and three CRAP gates.

The architecture that made it small: **iOS runs no schedule logic at all.** `swimzh export-ios`
pre-resolves every date in a fixed 400-day horizon into a derived store — sessions, day statuses,
notices, warnings, lane plans, feature hours, prices — and `SwimZHKit` computes only what depends on
the *user*: eligibility, the price bracket, distance, and the wall clock. The correctness core stayed
in Python, in one copy. The parity sweep proves it: every pool on every one of 400 dates, unsampled,
against `find_swim_options` itself.

**Fifteen defects were found that a passing test suite could not see.** They cluster into three
shapes, and the shapes are the reusable knowledge:

1. **A claim true only at one instant, or only on today** — seven instances, the last in five
   languages at once and one in a *derived value* rather than a label. "Open now · until 09:00" about
   a date four months out; "Closed today" reachable on ninety future dates; "no lanes open to the
   public" beside "Opens 06:00"; a lane count read at noon on a day nobody is standing in. The rule
   that emerged: **`at:` is meaningless off today**, and ghost/closed rows are day-agnostic while
   session rows are not, so every new sentence must be checked against both.
2. **A gate that looked enforced and was not** — four instances. A leak canary against
   `sqlite3_memory_used()`, which Apple ships with statistics **off** (2,000 deliberately leaked
   handles still report 0). CI tests that silently skipped because a build step was missing. A
   staleness check that **regenerated the file before checking it**. And a coverage sweep that
   iterated its own evidence table, so any unlisted claim went unchecked.
3. **A `rendered` claim outrunning its evidence** — four instances. The union/disjointness test proves
   every field is *classified*; it can never prove a "rendered" claim is *true*. Five fields were
   declared rendered that the phone structurally could not render.

**Three findings were overturned on evidence**, twice against the reviewer and twice against the
orchestrator's own instructions — a privacy code that would have caused the rejection it claimed to
prevent, a proposed assertion that was a tautology, a deletion that would have introduced a false
"split not published", and a fix instruction that was insufficient because a fixed midday moment
still mis-tiers a morning session.

**What is NOT built, deliberately.** The crowd/occupancy badge: the source does not exist and its
integration is deferred on legal grounds, so the client renders **no row** rather than a permanent
"unavailable" implying otherwise. The refresh path is complete and tested but **inert** — no manifest
URL is configured, because hosting was out of scope.

**What is NOT verified.** Every criterion needing human eyes or a physical device: truncation at the
largest accessibility sizes, light/dark on a notched device, Instruments CPU and per-body timing,
device launch under 1 s, and the live-water row on screen in any state or language. The user waived
these; they are recorded as unverified in the ledger, never marked done.

**Numbers as shipped.** App minus the store: **2,088,982 B** against a 4 MB ratchet and the user's
30 MB ceiling. Store: 1.79 MB (140-day fixture; a release build is 400 days, ~5 MB). Peak memory
62.1% of the 100 MB budget. 301 Swift kit tests, 20 simulator tests, 71 gate self-tests, 1,086 Python
tests at 96.20%, 498 TypeScript tests.

**Owed before a first release**, in order: seed **2027** into `data/calendar/zurich.yaml` — 269 of the
first export's 400 days already fall outside `known_years`; eyeball `CA92.1` in a browser; host the
manifest and set `SWIMZHStoreManifestURL`; have a native speaker read the Polish and German catalogs;
and look at the app on a real device.

Distilled into `docs/summaries/native-ios-app.md`.
