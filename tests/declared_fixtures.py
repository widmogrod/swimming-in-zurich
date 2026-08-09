"""The declared sources' committed page fixtures — the ONE shared owner of the
pool-id → fixture mapping and the locker noun scan.

This lives at the tests root beside `tests/pipeline_clients.py` for the same reason that
module does: several suites need it (`tests/etl/test_scrape.py` pins the mapping complete
against the production `declared_sources` predicate; `tests/providers/test_mietobjekt.py`
sweeps the whole corpus; `apps/web/tests/test_gold_store.py` derives the store-level
locker acceptance set), and a shared helper module beats cross-imports between test
modules. Not a test module itself — pytest never collects it.
"""

from __future__ import annotations

import re
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent / "providers" / "fixtures"

#: `pool_id` → its committed page fixture — one per declared source, asserted COMPLETE
#: against the production `declared_sources` predicate by
#: `tests/etl/test_scrape.py::test_states_city_tariff_over_every_declared_sources_committed_page`.
#: Two fixtures are named for the pool's short name rather than its roster id
#: (`maennerbad.html`, `frauenbad.html`), so the mapping cannot be derived.
PAGE_FIXTURES: dict[str, str] = {
    "hallenbad-city": "hallenbad_city.html",
    "hallenbad-oerlikon": "hallenbad_oerlikon.html",
    "hallenbad-bungertwies": "hallenbad_bungertwies.html",
    "hallenbad-blaesi": "hallenbad_blaesi.html",
    "hallenbad-leimbach": "hallenbad_leimbach.html",
    "hallenbad-altstetten": "hallenbad_altstetten.html",
    "waermebad-kaeferberg": "waermebad_kaeferberg.html",
    "schulschwimmanlage-aemtler": "schulschwimmanlage_aemtler.html",
    "schulschwimmanlage-altweg": "schulschwimmanlage_altweg.html",
    "schulschwimmanlage-riedtli": "schulschwimmanlage_riedtli.html",
    "schulschwimmanlage-tannenrauch": "schulschwimmanlage_tannenrauch.html",
    "freibad-allenmoos": "freibad_allenmoos.html",
    "freibad-auhof": "freibad_auhof.html",
    "freibad-heuried": "freibad_heuried.html",
    "freibad-letzigraben": "freibad_letzigraben.html",
    "freibad-seebach": "freibad_seebach.html",
    "freibad-zwischen-den-hoelzern": "freibad_zwischen_den_hoelzern.html",
    "seebad-katzensee": "seebad_katzensee.html",
    "seebad-utoquai": "seebad_utoquai.html",
    "strandbad-mythenquai": "strandbad_mythenquai.html",
    "strandbad-tiefenbrunnen": "strandbad_tiefenbrunnen.html",
    "strandbad-wollishofen": "strandbad_wollishofen.html",
    "flussbad-au-hoengg": "flussbad_au_hoengg.html",
    "flussbad-oberer-letten": "flussbad_oberer_letten.html",
    "frauenbad-stadthausquai": "frauenbad.html",
    "maennerbad-schanzengraben": "maennerbad.html",
}

#: The plain, PARSER-INDEPENDENT locker noun scan (mietobjekt-extraction S1 acceptance):
#: a compound `…kasten`, `Wertsachenfach`, or `Wäschefach` anywhere on the raw page. The
#: expected locker-carrying set is derived from the fixtures with this — never from the
#: parser's own routing — so the acceptance cannot collapse into comparing the parser
#: with itself. Measured: 20 of the 26 declared fixtures match.
LOCKER_NOUN = re.compile(r"\wkasten|Wertsachenfach|Wäschefach")

#: The same parser-independent posture for the S2 rental acceptance sets (each measured
#: over the declared fixtures; the counts are pinned by `tests/providers/test_mietobjekt.py`
#: and `apps/web/tests/test_gold_store.py`):
#:
#: * `MIETOBJEKT_NOUN` — the word `Mietobjekt` appears on a declared page ONLY as the
#:   anchoring column header of the one table, so its presence derives the table-carrying
#:   (== rentals-carrying, every table has ≥1 non-locker row) set. Measured: 20.
#: * `SUNLOUNGER_NOUN` / `PARASOL_NOUN` — the EXACT label word, `(?!\w)` so a compound like
#:   `Liegestuhlsaisonfach` (a compartment FOR a lounger, not renting one) never counts.
#:   Measured: 9 / 8.
#: * `RENTAL_WEAR_NOUN` — the towel/swimwear/goggles row nouns. Measured: 11.
#: * `CABIN_NOUN` — a compound `…kabine` (Tages-/Saisonkabine). Measured: 11.
MIETOBJEKT_NOUN = re.compile(r"Mietobjekt")
SUNLOUNGER_NOUN = re.compile(r"Liegestuhl(?!\w)")
PARASOL_NOUN = re.compile(r"Sonnenschirm(?!\w)")
RENTAL_WEAR_NOUN = re.compile(r"Badetuch|Badebekleidung|Badehosen|Schwimmbrille")
CABIN_NOUN = re.compile(r"\wkabine")


def page_of(pool_id: str) -> str:
    """The committed page fixture text for one declared source."""
    return (FIXTURES_DIR / PAGE_FIXTURES[pool_id]).read_text(encoding="utf-8")
