---
type: summary
created: 2026-08-08
links: ["[[2026-08-08-admission-union-plan]]", "[[admission]]", "[[city-tariff]]", "[[facility-field-sourcing]]"]
---

# Admission union

Free admission is a fact the city publishes, not a missing price. See
[[admission]] for the entity.

## What exists

- **The union** — `domain/admission.py`: `Admission = Free | Tariff(table) |
  Unknown`, closed and `assert_never`-matched everywhere;
  `Facility.admission` replaces the deleted `prices` field (a
  `dataclasses.fields` test pins that the compressed field cannot return).
- **The producer** — `providers/price_scraper.states_free_admission` reads
  the pool page's own sentence: `Der Eintritt … ist gratis` or the
  predication-anchored `ist (es) ein Gratisbad`. Exactly 4 free pools match
  across all 26 declared fixtures; the locker-row `gratis` bait on 21 pages
  stays False (pinned on hallenbad_city). Free is never inferred from a
  missing tariff link, hostname, or kind.
- **Precedence** — `etl/scrape.admission_for`: a stated tariff link wins;
  tariff + stray gratis sentence yields the tariff plus a contradiction
  note; neither fact → `Unknown` + note.
- **The store** — 21 Tariff / 4 Free / 32 Unknown after rebuild
  (literal-SQL pin). Serialization additive: the union rides the existing
  `prices` key; `admission_state: "free"` appears on exactly the 4 free
  blobs; pre-union blobs load as `Unknown`.
- **Fail-fast** — `scrape_prices -> Err` aborts the build (and scrape-gold)
  with the typed cause named; the prior gold store is content-unchanged.
  `scrape_declared_sources(…, tariffs: CityTariffs)` is required — the
  degraded continue-without-tariffs state is unrepresentable. A pool whose
  page states neither fact remains exit-0 `Unknown` + noted.
- **The API** — `/pools/{id}` carries `admission: "free" | "tariff" |
  "unknown"`; `/swim` is byte-unchanged for Tariff and Unknown pools; a
  Free pool's option still carries `price: null` (rendering deferred).

## Known limits

Free-ness is data-only — no UI renders it yet. `flussbad-unterer-letten`'s
page states free-ness but is not a declared source (shared URL); its fact
stays compressed until the SharedSource plan decides the pair's identity.
