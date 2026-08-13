---
type: entity
name: admission
created: 2026-08-08
links: ["[[2026-08-08-admission-union-plan]]", "[[city-tariff]]", "[[session-access]]"]
---

# Admission

The closed union answering *what does entry cost here* — `Free | Tariff(PriceTable) | Unknown` —
replacing `Facility.prices: PriceTable | None`, whose `None` compressed two different facts into
one null: *the city publishes this pool as free* and *nobody has priced this pool*.

Each arm is a **page-stated fact**, never an inference:

- **`Tariff`** — the pool's own page links the city tariff page ([[city-tariff]]'s
  `states_city_tariff`); the table is the published one, school or general by kind.
- **`Free`** — the pool's own page states the sentence: *"Der Eintritt … ist gratis"* or
  *"Gratisbad"*. The match must be the tight sentence — bare `gratis` appears on ~22 of the 26
  declared pages inside the Kombi6 boilerplate *"(1 x gratis)"*. Never inferred from a missing
  tariff link: `hallenbad-altstetten` has no link either, and it is a private operator whose
  prices we simply do not know.
- **`Unknown`** — the page states neither. The honest default, and what every pre-union blob
  decodes to.

Serialized additively: `Tariff` and `Unknown` blobs are byte-identical to the pre-union format
(the existing `prices` key, table or null); only `Free` adds `admission_state: "free"`. That is
what lets the re-layer commands load old blobs across the change.

The union also splits failure from absence: one pool stating nothing is `Unknown` plus a build
note; the whole tariff *scrape* failing is a provider failure and aborts the build. Before the
union those collapsed into the same silent `None`.
