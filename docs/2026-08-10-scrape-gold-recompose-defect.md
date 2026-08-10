# `scrape-gold` refreshes nothing a pool already has (2026-08-10)

Not a plan — a defect report with an end-to-end reproduction. Found while tracing the data flow for
[[2026-08-09-lane-stack-board-plan]]; independent of it.

**Severity: high, and silent.** The command exits `0`, prints `scraped N source extracts`, and
changes nothing that the store already holds. `scrape-gold`'s documented purpose is to refresh
against an already-built store — which is precisely the condition under which it refreshes nothing.

> **Revision 2 (2026-08-10, post-review).** Revision 1 scoped this to *basins only* and claimed
> prices, closures, notices, lockers, rentals and geo still refreshed. **That was wrong, and it
> understated the bug**: every aspect goes through the same feedback. Revision 1 also quoted the
> `… kept from curated` notes as evidence the aspect merge was benign — those notes are the log of
> the fresh scrape being discarded. Both corrected below, in §2 and §4.

---

## 1. The contract it breaks

`src/swimzh/cli.py:14-18` states it plainly:

> `scrape-gold`/`scrape-lanes` remain as **THIN RE-LAYER** commands: each re-runs only its own phase
> against an already-built store (seeded temp + swap), so an operator can **refresh schedules** or
> lane plans on their own cadence without a full WFS+curated rebuild.

An operator refreshing seasonal hours without a full rebuild gets a no-op with a success exit code.

`README.md:44-49` documents the broken sequence as the happy path — it presents `build` as offline
and step 2 as the one supplying "real scraped schedules". Since `build` became the atomic pipeline it
already scrapes, so the documented two-step is exactly the case that fails. **The README needs fixing
alongside the code.**

## 2. Reproduction (end to end, offline clients)

A repro that re-serves the *same* fixture proves nothing — identical output is also what correct
idempotence looks like. The fixture must be **mutated**, and paired with a pre-scrape control.

Mutations applied to the City page/tariff fixtures: `6–22 Uhr` → `7–21 Uhr`, notice text changed,
`Fr. 8.–` → `Fr. 13.–`.

| target store | rules | notice | adult price | compose note |
|---|---|---|---|---|
| **pre-scrape** (`build_store` / `_offline_base`) | `07:00–21:00` ✅ | new ✅ | `13.00` ✅ | `basins: scraped schedule + 1 curated lane binding(s)` |
| **already built** (the re-layer) | `06:00–22:00` ❌ | old ❌ | `8.00` ❌ | *(no `basins:` note)* |

Both runs exit `0` and print `scraped 1 source extracts`.

**Two tells, and one is a trap.** The missing `basins:` line is the honest signal. The other notes —
`admission kept from curated`, `closures kept from curated`, `notices kept from curated` — look like
routine merge chatter but are the opposite: `kept from curated` on a re-layer means *the freshly
scraped value was thrown away*, because "curated" is the store's own previous output.

## 3. Mechanism

`scrape_gold` (`cli.py:338-347`) re-composes over its own previous output:

```python
curated = GoldRepository(conn).load_all()      # <- already-composed blobs
composition = compose(curated, outcome.resolved)
write_schedules(conn, ...)
```

Everything downstream treats that stored blob as the authoritative *curated* tier.

**Basins.** `_merge_basins` (`compose.py:192`) branches on whether the curated side has a schedule:

```python
if _has_schedule(curated_basins):
    return curated_basins, None, False        # curated-wins wholesale — scraped basins DISCARDED
if _has_schedule(scraped_basins):
    merged = _carry_bindings(scraped_basins, curated_basins)
```

`_has_schedule` (`compose.py:103`) is `any(basin.rules for basin in basins)`. On a first composition
inside `build`, the curated tier carries no schedules (since `delete-curated-schedule-tier`), so the
scraped branch wins and `_carry_bindings` runs. On a re-layer the stored `Hauptbecken` already has
rules, so the fresh scrape is discarded.

**Every other aspect.** `_ASPECTS` (`compose.py:125-136`) has ten entries and **all ten are
`CURATED_WINS`** (`compose.py:90`) — admission, closures, notices, geo, features, lockers, rentals,
`public_holiday_policy`, `last_admission_before`, `operating_season`. `_fold` takes the first source
whose value is `present()`, and on a re-layer that is always the stored side. So an aspect can only
transition **absent → present**; it can never go **present → different**.

**Identity too.** `base` (`compose.py:230`) is `by_source.get(Source.CURATED) or …`, i.e. the stored
facility, so name/address/identity are likewise fixed. And provenance adoption (`compose.py:259`) is
gated on `scraped_schedule`, which is `False` on the dead branch — so `valid_as_of` does not advance
either.

**Root cause, stated generally: gold stores the *result* of a fold, and that result is then fed back
in as an *input* to the same fold.** The blob does not record which tier supplied each part of it, so
the fold cannot tell "curated states this" from "we scraped this last Tuesday". See
[[data-sourcing-rule]].

## 4. Blast radius — the re-layer is inert on anything already populated

Correcting revision 1, which listed most of this column as "yes".

| On a `scrape-gold` re-layer | refreshes? |
|---|---|
| Schedule rules / sessions (basins) | **no** |
| admission / prices | **no** |
| closures, notices | **no** |
| geo, features, lockers, rentals | **no** |
| `public_holiday_policy`, `last_admission_before`, `operating_season` | **no** |
| `provenance` (`valid_as_of`, `curated`) | **no** |
| Lane bindings carried onto lane basins (`_carry_bindings`) | **no** |
| Identity / name / address (`base`) | **no** |
| Any of the above where the store currently holds **nothing** | yes (absent → present only) |

`scrape-lanes` is **not affected**: it never calls `compose` (the only call is `cli.py:346`, inside
`_compose_schedules`); it calls `attach_lane_plans` and writes back (`cli.py:481-493`).

**Present-day impact is bounded by usage, not by design.** Nothing automates the command —
`grep -rn "scrape-gold" .github Makefile scripts` returns no matches; it is invoked by hand per
`README.md:46-49`. So the store is not silently rotting today. But it is **unobservable** when it
does: `ScheduleFreshness` (`domain/catalog.py:45-54`) still reports `SCRAPED` for a frozen schedule,
so there is no read-path signal at all.

## 5. Why no test catches it

`tests/test_cli.py:211-229` (`test_scrape_gold_composes_onto_built_store`) **does** exercise this path
— it calls `build(...)` (atomic, already-scraped) then `scrape_gold(...)`. Its assertions are about
row identity only:

```python
assert len(facilities) == 57
assert sum(1 for f in facilities if str(f.identity.facility_id) == "hallenbad-city") == 1
```

No assertion that anything changed. The test was written for the id-unification concern (no duplicate
long-slug row) and is correct for that; it is simply silent on refresh.

## 6. Candidate fixes (options, not a decision)

1. **Make the fold's input a source, not a snapshot.** Store per-source facts attributed to their
   producer and compose at read, so re-running a phase replaces only that producer's rows. Aligns
   with [[data-sourcing-rule]] rule 3. Largest change; removes the whole class of bug, basins and
   aspects alike.
2. **Re-layer from sources rather than from the store.** `scrape-gold` rebuilds the curated tier from
   `data/` and composes that with the fresh scrape, instead of loading the composed blob. **The only
   listed option short of #1 that fixes both basins and aspects.** Unnamed cost: `scrape_gold`
   (`cli.py:571-573`) takes no `data_dir`, so this adds a parameter and a curated-assemble hop inside
   a command whose whole point is being thin.
3. **Discriminate the tier in the blob** — record which source supplied a basin's rules and branch
   `_merge_basins` on that. **Basins only.** It does nothing for the ten `_ASPECTS`, which flow
   through `_fold`, so prices and notices would stay frozen. A partial fix, not a cheap one — it
   addresses roughly one item of the §4 table. Precedent exists either way: `Basin.physical_source`
   (`domain/models.py:176`) is already a tag of exactly this shape.
4. **Minimum viable, regardless of the above:** assert the refresh. Extend `test_cli.py:211-229` to
   mutate a fixture and pin that a re-layer changes the stored value — and pin **a non-basin aspect
   too** (a price or a notice), or the guard passes while prices stay frozen.

Option 1 is the most correct and option 2 the most contained. Revision 1 ranked option 3 "cheapest";
that ranking was wrong, because it scoped the bug to basins.

## 7. Relation to the lane-stack plan

[[2026-08-09-lane-stack-board-plan]] S1 edits `_carry_bindings`. Its acceptance runs against the
`gold_db` fixture (`apps/web/tests/conftest.py:37-47`), which is a **fresh atomic `build`** — the
branch where `_carry_bindings` does run — so S1 is testable as written and is **not blocked** by this
defect. The consequence to record is narrower: S1's change, like everything else, will not reach a
store that is only ever re-layered. Naming `build` as the phase that exercises it belongs in S1's
acceptance.
