---
type: summary
feature: calendar-pyright-surface
status: done
created: 2026-07-20
links: ["[[techdebt-remediation-roadmap]]", "[[gold-store]]"]
---

# Calendar pyright surface — public accessors, 12 findings cleared

**What & why.** Roadmap debt #8: `storage/calendar_codec.py` + its tests read `ZurichCalendar`'s
private attrs (`_public`/`_school`/`_known_years`) → 12 pyright `reportPrivateUsage` findings. This
gives the calendar a public read surface so the encapsulation break is gone. mypy strict (the enforced
gate) was and stays green; pyright is NOT promoted to a gate.

## What exists now

- `ZurichCalendar` (`domain/calendar.py`) has read-only accessors: `public_holidays` (a
  `MappingProxyType` view), `school_holidays` (tuple of frozen `HolidayRange`), `known_years`
  (frozenset), plus a value-based `__eq__`.
- `storage/calendar_codec.to_dto` and its tests read the accessors, not the privates. The
  `dumps`/`loads` round-trip is unchanged (byte-identical; only the read source moved).
- **pyright `reportPrivateUsage`: 42 → 30** — the 12 calendar findings are cleared; the remaining 30
  (`catalog_json.py`, `test_belegungsplan.py`) are the still-deferred pyright backlog, out of scope.

## Note

`ZurichCalendar` is now unhashable (a value `__eq__` on a plain class implicitly sets `__hash__=None`).
Verified nothing uses it as a dict key / set member, so this is safe — and correct, since one field is
a `Mapping`.

Last item of the **A → B → C → D → E** remediation program. See
[[2026-07-20-calendar-pyright-surface-plan]] for the ledger.
