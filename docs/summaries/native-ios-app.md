---
type: summary
created: 2026-08-24
links: ["[[2026-08-23-native-ios-app-plan]]", "[[ios-resolved-export]]", "[[gold-store]]", "[[data-layer-architecture]]", "[[session-access]]"]
---

# Native iOS app

`apps/ios/` is a native SwiftUI app for iOS 26 that answers *"where can I swim in Zürich?"* entirely
offline, from a SQLite file it carries in its bundle. It is built from `SwimZHKit` (a Swift package
holding every rule, and the only thing the Swift CRAP gate scores) plus a deliberately thin app
target that contains **no state-to-string logic at all**.

## The architecture, in one sentence

**iOS runs no schedule logic.** `swimzh export-ios` pre-resolves every date in a fixed 400-day
horizon into a derived store ([[ios-resolved-export]]) — sessions, day statuses, notices, warnings,
lane plans, feature hours, prices — and Swift computes only what depends on the *user*: eligibility,
the price bracket, distance, and the wall clock. The correctness core stays in Python, in one copy.

The bet is proved, not asserted: a parity sweep compares every pool on every one of the 400 dates,
**unsampled**, against `find_swim_options` itself. Domain → export → Swift is closed by an
independent oracle, because the golden fixture is generated from the *domain* while Swift reads the
*projection*.

## What is here

| Layer | What it does |
|---|---|
| `src/swimzh/etl/ios_export.py` | the 12-table STRICT export + `manifest.json`; finishes `journal_mode=DELETE` + `VACUUM` + `ANALYZE` |
| `SwimZHKit/Store.swift` | a read-only SQLite **actor** (`immutable=1`, `NOMUTEX`, explicit `cache_size`) |
| `SwimZHKit/{Eligibility,Pricing,Geo,Clock}` | the four user-dependent ports of Python domain code |
| `SwimZHKit/{ListModel,DayState,Banners,Filters}` | the list screen's rules — tiers, five day states, banners |
| `SwimZHKit/{RibbonModel,TimeAxis,LanePlan}` | the ribbon, one time→x mapping, the lane derivations |
| `SwimZHKit/{FacilityDetail,PoolBrowser,AccessExplainer}` | the sheet, the roster browser, the legend |
| `SwimZHKit/{Localized,Format,Catalog.generated}` | five locales from the web catalogs; regional formatting |
| `SwimZHKit/{Live,Refresh}` | **the only two files in either target allowed to touch the network** |
| `scripts/{crap_swift,ios_budget,field_coverage,locales_to_xcstrings,xcstrings_plural_gate}` | the gates |

## The three defect shapes worth remembering

Fifteen defects were found across seven slices that a passing test suite could not see. They cluster:

**1. A claim true only at one instant, or only on today** — seven instances. "Open now · until 09:00"
about a date four months out; "Closed today" reachable on ninety future dates; "no lanes open to the
public" printed beside "Opens 06:00"; a lane count read at noon on a day nobody is standing in; a raw
`2026-12-25` in five languages. **`at:` is meaningless off today.** Ghost and closed rows are built
day-agnostically while session rows are not, so every new sentence must be checked against **both**.

**2. A gate that looked enforced and was not** — four instances. A leak canary against
`sqlite3_memory_used()`, which Apple ships with `SQLITE_CONFIG_MEMSTATUS` **off** (2,000 deliberately
leaked handles still report 0). CI tests that silently skipped for want of a build step. A staleness
check that **regenerated the file before checking it** — build, then check, is the only order that
can fail. And a coverage sweep that iterated its own evidence table, so an unlisted claim went
unchecked.

**3. A `rendered` claim outrunning its evidence** — four instances. The union/disjointness test proves
every field is *classified*; it can **never** prove a "rendered" claim is *true*. Five fields were
declared rendered that the phone structurally could not render.

## Platform facts that would each have shipped a wrong app

- **A WAL-mode SQLite cannot be read from an app bundle.** `sqlite3_open_v2` returns `SQLITE_OK` and
  the **first prepare** fails. A test that only opens proves nothing. The export ships DELETE mode and
  asserts header byte 18 — which proves *not WAL* (all four non-WAL modes write `01`).
- **`ANALYZE` always creates `sqlite_stat1`**, even on an empty database. Count rows, not existence.
- **`String(localized:)` never expands a plural** — it returns the raw `%#@value@` token. The
  **bundle** picks the language; `String(format:locale:)`'s `locale:` picks the plural rule. One
  without the other renders Polish words with English grammar.
- **SwiftPM does not compile `.xcstrings`** — `Bundle.module.localizations` reports only `["en"]`.
- **Xcode's memory readouts labelled "MB" are KiB × 1000.**
- **llvm-cov reports a function's start line as the body-brace line**, not the `func` line.
- **SwiftLint cannot be a CRAP source**: it counts from 0 not McCabe's 1, ignores `&&`/`||`/ternaries,
  and is `func`-only — blind to `var body`, which llvm-cov *does* emit as a function.
- **`xcodebuild test` copies ~8.8 MB of XCTest support into the .app**; a size gate inside that
  command must exclude it.
- **Apple's ICU renders fr-CH with a dot where node's uses a comma** — the phone and the browser
  differ for a French-Swiss reader, by measurement, and each side asserts its own truth.

## Deliberately not built

**The crowd/occupancy badge.** The source does not exist and its integration is deferred on legal
grounds (`data/sources.md`), so the client renders **no row** — a permanent "unavailable" would imply
a source that is merely down. **The refresh path** is complete and tested but **inert**: no manifest
URL is configured, because hosting was out of scope.

## Not verified

Everything needing human eyes or a physical device, all recorded as unverified rather than assumed:
truncation at the largest accessibility sizes, light/dark on a notched device, Instruments CPU and
per-body timing, device launch under 1 s, and the live-water row on screen in any state or language.

## Owed before a first release

1. Seed **2027** into `data/calendar/zurich.yaml` — 269 of the first export's 400 days already fall
   outside `known_years`, and ship warned.
2. Eyeball the `CA92.1` privacy reason in a browser (documentation-verified, not human-verified).
3. Host `manifest.json` + the store, and set `SWIMZHStoreManifestURL`.
4. Have a native speaker read the Polish and German catalogs.
5. Look at the app on a real device.
