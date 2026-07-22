---
type: plan
status: done             # single slice on main 2026-07-20; see Summary
created: 2026-07-20
feature: calendar-pyright-surface
gates:
  qa: full               # ruff, format, mypy strict, pytest+coverage floor (95), CRAP
  review: adversarial
pause_after: []
links: ["[[techdebt-remediation-roadmap]]", "[[gold-store]]"]
---

# Plan E — Calendar pyright surface

## Context

Roadmap debt **#8**: `storage/calendar_codec.py` (and its tests) read `ZurichCalendar`'s private attrs
(`_public`/`_school`/`_known_years`) → +12 pyright `reportPrivateUsage`. mypy strict (the enforced gate)
is green; this clears the calendar findings by giving `ZurichCalendar` a public read surface. **NOT** a
new gate — pyright stays non-enforced per CLAUDE.md; this just stops the encapsulation break.

## Design (signature altitude)

- Add read-only public accessors to `ZurichCalendar` — `public_holidays`, `school_holidays`,
  `known_years` (properties or a small read API) — and an `__eq__` (needed by codec round-trip tests).
- **Hashability caveat:** if a field is a `Mapping`, a frozen dataclass with a custom `__eq__` may become
  unhashable — confirm nothing uses a `ZurichCalendar` as a dict key / set member before adding `__eq__`
  (adjust with `eq=False` + explicit `__eq__`, or keep frozen semantics intact).
- Rewrite `storage/calendar_codec.to_dto` (and its two tests) to read the public surface, not `_public`
  etc.

## Out of scope

- Clearing the OTHER deferred pyright debt (`catalog_json.py`, `test_belegungsplan.py`) — calendar only.
- Promoting pyright to a second enforced CI gate.

## Slices

- **E1 — Public read surface + codec off privates.** *(S)* Add the read accessors + `__eq__` to
  `ZurichCalendar` (`domain/calendar.py`); rewrite `calendar_codec.to_dto` + its two tests to use them;
  remove the private-attr reads.
  **Acceptance:** `calendar_codec` + its tests no longer read `ZurichCalendar._public/_school/
  _known_years`; the calendar round-trip (`dumps`/`loads`) is unchanged (still inverse); `pyright`'s
  `reportPrivateUsage` count drops by the 12 calendar findings (report before/after); mypy strict + full
  QA green.
  **Depends on:** —

## Ledger

| date | slice | status | divergence | tech debt | human review? |
|------|-------|--------|------------|-----------|---------------|
| 2026-07-20 | E1 | done | fixed a THIRD file (`tests/storage/test_gold_store_catalog_calendar.py`) beyond the plan's "two tests" — it held 3 of the 12 calendar findings, so the acceptance (12→0) required it | none. Non-blocking (critic): `__eq__`'s value-discrimination isn't directly asserted (a "different-data → unequal" case would make it falsifiable — but the round-trip accessor asserts independently guard data preservation); the unhashable intent could be made executable (a `hash(cal)` → `TypeError` test) | no |

## Decisions & divergences

- **2026-07-20 — Hashability.** `ZurichCalendar` is a plain class; defining a value `__eq__` implicitly
  sets `__hash__ = None` (unhashable). Grep confirmed nothing uses a `ZurichCalendar` as a dict key/set
  member, so unhashable is safe (and correct — one field is a `Mapping`, so value-hashing would be
  unsound). Relied on the implicit `__hash__ = None` rather than an explicit assignment (which mypy
  strict rejects), documented by a comment.

## Summary

**Done — the calendar codec reads a public surface; the 12 calendar pyright findings are cleared.**
Single slice on `main`; 349 tests, 95.68% coverage, mypy strict + CRAP green.

- `ZurichCalendar` (`domain/calendar.py`) gained read-only accessors `public_holidays`
  (`MappingProxyType` view), `school_holidays` (tuple), `known_years` (frozenset), and a value `__eq__`.
- `storage/calendar_codec.to_dto` + its tests read the accessors instead of `_public/_school/
  _known_years`. The `dumps`/`loads` round-trip is byte-identical (only the read source changed).
- **pyright `reportPrivateUsage`: 42 → 30** (the 12 calendar findings → 0). mypy strict (the enforced
  gate) stays green; pyright is NOT promoted to a gate. The remaining 30 (`catalog_json.py`,
  `test_belegungsplan.py`) are out of scope — the still-deferred pyright backlog.

This is the last item of the **A → B → C → D → E** remediation program.
