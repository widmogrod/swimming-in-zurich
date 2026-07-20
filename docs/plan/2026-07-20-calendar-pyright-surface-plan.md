---
type: plan
status: in-progress      # /dev:implement executing on main (worktree retired)
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
| —    | —     | —      | —          | —         | —             |

## Decisions & divergences

## Summary

Written at `done`; distilled into `docs/summaries/calendar-pyright-surface.md`.
