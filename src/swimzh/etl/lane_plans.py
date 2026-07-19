"""Fetch + parse the per-basin Belegungsplan PDFs for the city indoor pools.

Best-effort, mirroring `scrape.py`: each URL is fetched and parsed independently; a PDF
whose fetch or parse fails is skipped and reported, never fatal. Successfully parsed plans
carry only a `basin_hint` — the silver stage (`attach_lane_plans`) reconciles that to a
`Basin`. The URL→basin binding is intentionally *not* made here (decision #8): this module
only knows where the PDFs live.
"""

from __future__ import annotations

from dataclasses import dataclass

from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok
from swimzh.providers.belegungsplan import ParsedPlan, scrape_belegungsplan

# The city indoor pools publish per-basin Belegungspläne under a shared
# `.../belegungsplaene/<slug>[-<basin>].pdf` path. Best-effort and UNVERIFIED — a wrong or
# stale URL is skipped + reported, and the parsed header's basin_hint (not the URL) drives
# reconciliation, so a bad entry can never mis-attach. Verify against the live pool pages.
_BELEGUNGSPLAENE = (
    "https://www.stadt-zuerich.ch/content/dam/web/de/stadtleben/sport-und-erholung/"
    "dokumente/badeanlagen/belegungsplaene"
)

# Verified per-basin Belegungsplan PDFs for the curated city indoor pools. Hints that don't
# reconcile to a curated basin (e.g. the Variobecken, uncurated pools) are reported, not fatal.
CITY_BELEGUNGSPLAN_URLS: tuple[str, ...] = (
    f"{_BELEGUNGSPLAENE}/city-schwimmerbecken.pdf",
    f"{_BELEGUNGSPLAENE}/city-variobecken.pdf",
    f"{_BELEGUNGSPLAENE}/oerlikon-schwimmerbecken.pdf",
    f"{_BELEGUNGSPLAENE}/oerlikon-nichtschwimmer-sprungbecken.pdf",
    f"{_BELEGUNGSPLAENE}/bungertwies.pdf",
)


@dataclass(frozen=True, slots=True)
class LanePlanReport:
    plans: tuple[ParsedPlan, ...]
    skipped: tuple[str, ...]  # URLs whose PDF could not be fetched/parsed


def scrape_lane_plans(client: HttpClient, urls: tuple[str, ...]) -> LanePlanReport:
    plans: list[ParsedPlan] = []
    skipped: list[str] = []
    for url in urls:
        match scrape_belegungsplan(client, url):
            case Ok(parsed):
                plans.append(parsed)
            case Err(_):
                skipped.append(url)
    return LanePlanReport(plans=tuple(plans), skipped=tuple(skipped))
