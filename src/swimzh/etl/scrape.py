"""Scrape each declared source's official page into an identity-free ``(SourceRef, aspects)``
extract.

A **declared source** is a roster entry that both plausibly has a timetable and owns the page it
points at — see `declared_sources` for the predicate. Today that is 26 pools: the 7 indoor/thermal
city pools, the 4 Schulschwimmanlagen that publish public swimming on their own page, and the 15
outdoor/lake/river pools whose seasonal `Zeitraum` table the scraper reads (seasonal-hours S3).

Per pool we scrape: the timetable (→ rules and the page's last-admission rule), notices/alerts
(→ `Notice`s, and closure-type notices → `ClosureRange`s), and the pool's ``Admission``
(`admission_for`: `Tariff` when the page LINKS the city tariff — the Schulschwimmanlage rate for
a `SCHOOL` pool, the general rate otherwise; `Free` when the page states its own gratis sentence;
`Unknown` — plus one ``ScrapeReport.notes`` line — when it states neither). The result is a
``ScrapedAspects`` payload paired with a ``Name``
``SourceRef`` (the WFS display name) — **never a canonical id**. ``build.reconcile.resolve_all``
turns each ``Name`` into a ``PoolId`` by lookup, and ``build.compose`` folds the aspects onto the
matching pool.

**Fail-fast (S4):** a declared source whose page fails to fetch or parse is **NOT skipped**. Its
typed ``ProviderError`` is preserved in ``ScrapeReport.failures`` so the ``scrape-gold`` command
aborts the whole run non-zero carrying that cause (owner decision 2026-07-28: no
green-exit-with-a-hole). The best-effort skip-and-report
posture is gone; the typed error *value* stays.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple

from swimzh.build.compose import ScrapedAspects
from swimzh.build.reconcile import Name, SourceRef
from swimzh.core.errors import ProviderError
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok
from swimzh.domain.admission import Admission, Free, Tariff, Unknown
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.models import Basin, BasinId, Notice, PoolKind
from swimzh.domain.schedule import ClosureRange
from swimzh.providers.operator_pages import parse_maintenance_closures
from swimzh.providers.price_scraper import (
    CityTariffs,
    states_city_tariff,
    states_free_admission,
)
from swimzh.providers.schedule_scraper import (
    ScrapedSchedule,
    fetch_page,
    parse_notices,
    parse_schedule,
)

_CLOSURE_WORDS = ("geschlossen", "revision", "gesperrt", "betriebsferien")

#: The kinds whose pages this module's parsers understand. `THERMAL` is a WFS-`indoor` Wärmebad
#: with a registry display-override; `SCHOOL` joined in 2026-08-05 (school-access-vocabulary S2);
#: `OUTDOOR`/`LAKE`/`RIVER` in 2026-08-06, once the `Zeitraum` parser (seasonal-hours S2) could
#: read the seasonal tables those pages publish.
#: NOTE: `domain.catalog.freshness_of` deliberately does NOT include `SCHOOL`, nor these three —
#: only 4 of the 18 Schulschwimmanlagen are declared sources, and the two `flussbad-unterer-letten`
#: entries share one URL, so a rule-less pool of those kinds is `NO_SOURCE`, not `AWAITING_SCRAPE`.
#: `Facility` carries no URL, so it cannot apply the conjunction below.
_SCRAPEABLE_KINDS = (
    PoolKind.INDOOR,
    PoolKind.THERMAL,
    PoolKind.SCHOOL,
    PoolKind.OUTDOOR,
    PoolKind.LAKE,
    PoolKind.RIVER,
)

#: The two pools the kind gate admits but no parser here understands — excluded BY ID, with the
#: reason, rather than left to fail the build. Both hold *unshared* URLs on a private operator's
#: site, so neither the kind test nor the shared-URL test excludes them, and both return
#: `ParseError('no HTML schedule table')` — which under fail-fast aborts the whole run.
#:
#: * `seebad-enge` (tonttu.ch) publishes a guaranteed core window nested inside a conditional one;
#: * `freibad-dolder` (doldersports.com) publishes date-range exceptions.
#:
#: Neither shape exists in the domain model yet (2026-08-06 Gap 7), so admitting them would mean
#: inventing facts. Keyed by `pool_id` — the identity spine — for the same reason
#: `_OPERATOR_CLOSURES` is: dolder's operator has already changed domain once without notice.
_UNPARSEABLE_OPERATOR_PAGES = frozenset({"seebad-enge", "freibad-dolder"})

#: Per-pool extra closure extractors for pools whose page is a **private operator's**, not the
#: city's. Keyed by `pool_id` — deliberately NOT by host: `freibad-dolder`'s operator changed
#: domain (doldersports.com → doldereisundbad.ch) without notice, and a host-keyed table would
#: have fallen through silently. `pool_id` is the identity spine and is the only stable key.
#:
#: This is a dispatch, not another entry in `schedule_scraper._PARSERS`: that chain is
#: format-sniffing and pool-blind (first `Ok` wins, tried against all 57 pages), which on these
#: sites is a wrong-answer generator rather than a fallback.
_OPERATOR_CLOSURES: Mapping[str, Callable[[str], tuple[ClosureRange, ...]]] = {
    "hallenbad-altstetten": parse_maintenance_closures,
}

# One scrape extract: a reference the reconcile seam resolves to a PoolId, plus its payload.
Extract = tuple[SourceRef, ScrapedAspects]


class DeclaredSource(NamedTuple):
    """A roster entry that owns a scrapeable page, paired with that page's URL — non-optional,
    because `declared_sources` has already established it."""

    entry: PoolCatalogEntry
    url: str


@dataclass(frozen=True, slots=True)
class ScrapeFailure:
    """A declared source (see `declared_sources`) whose page failed to fetch or parse, keyed to
    its **typed** ``ProviderError`` cause. Not a swallowed skip: ``scrape-gold`` aborts the whole
    run on any of these, surfacing the cause (S4 fail-fast)."""

    name: str
    url: str
    cause: ProviderError


@dataclass(frozen=True, slots=True)
class ScrapeReport:
    extracts: tuple[Extract, ...]  # (SourceRef, ScrapedAspects) — no canonical id minted here
    failures: tuple[ScrapeFailure, ...]  # declared sources that failed (typed cause preserved)
    #: Non-fatal build notes: one per declared source whose page states NEITHER the city tariff
    #: nor free admission (`Unknown`). Not a failure — the privately run `hallenbad-altstetten`
    #: is the honest example — but not silence either: the live build reads `fetch_roster`, not
    #: the committed `catalog.json`, so a WFS URL drift that silently unprices a pool would
    #: otherwise leave no trace. A `Free` pool needs no note any more: its free-ness is recorded
    #: as data (`Admission`), no longer only in stderr. A page that states BOTH (tariff link wins)
    #: also gets a note naming the contradiction — a page bug to surface, not a build failure.
    notes: tuple[str, ...] = ()


def _closures_from_notices(notices: tuple[Notice, ...]) -> tuple[ClosureRange, ...]:
    return tuple(
        ClosureRange(start=n.active_from, end=n.active_to, reason=n.text)
        for n in notices
        if n.active_from is not None
        and n.active_to is not None
        and any(word in n.text.lower() for word in _CLOSURE_WORDS)
    )


def _aspects(
    entry: PoolCatalogEntry,
    schedule: ScrapedSchedule,
    notices: tuple[Notice, ...],
    closures: tuple[ClosureRange, ...],
    admission: Admission,
    fetched_at: datetime,
) -> ScrapedAspects:
    return ScrapedAspects(
        name=entry.name,
        kind=entry.kind,
        address=entry.address,
        geo=entry.geo,
        basins=(
            Basin(
                basin_id=BasinId(f"{entry.pool_id}-main"), name="Hauptbecken", rules=schedule.rules
            ),
        ),
        closures=closures,
        notices=notices,
        admission=admission,
        fetched_at=fetched_at,
        public_holiday_policy=schedule.holiday_policy,
        last_admission_before=schedule.last_admission_before,
    )


def declared_sources(catalog: tuple[PoolCatalogEntry, ...]) -> tuple[DeclaredSource, ...]:
    """The roster entries whose own page we scrape — a **conjunction** of four tests:

    * the kind is one this module's parsers understand: `INDOOR`, its `THERMAL` display-override
      (a WFS-`indoor` Wärmebad like Käferberg), a `SCHOOL` pool, or an `OUTDOOR`/`LAKE`/`RIVER`
      pool (whose seasonal `Zeitraum` table the scraper reads since seasonal-hours S2);
    * the pool is not one of the two whose operator page no parser here understands
      (`_UNPARSEABLE_OPERATOR_PAGES`);
    * the entry carries a page URL at all;
    * **no other roster entry carries the same URL.** A shared URL is an *overview* page, not this
      pool's page: 14 entries (the 13 Schulschwimmanlagen *"ohne öffentliches Schwimmen"* plus
      `schulschwimmanlage-borrweg`) all point at the generic `hallenbaeder.html`, which states no
      pool's timetable. Under fail-fast, scraping it would turn one unparseable overview into 14
      build-aborting failures.

    The kind gate stays load-bearing even now: the unshared-URL test *alone* selects 28 entries,
    17 of them outdoor/lake/river, and the 2 the kind gate can no longer exclude are named
    explicitly above. Pinned on the committed WFS snapshot by `tests/etl/test_scrape.py` (== 26).
    The URL is returned alongside the entry rather than re-read from it, so the not-`None` test is
    done once here instead of being re-asserted at every use.
    """
    seen = Counter(e.url for e in catalog if e.url)
    return tuple(
        DeclaredSource(entry=e, url=e.url)
        for e in catalog
        if e.kind in _SCRAPEABLE_KINDS
        and e.pool_id not in _UNPARSEABLE_OPERATOR_PAGES
        and e.url is not None
        and seen[e.url] == 1
    )


def admission_for(source: DeclaredSource, page_html: str, tariffs: CityTariffs) -> Admission:
    """This pool's ``Admission``, decided by page-stated facts only — never a hostname:

    * **Tariff** — the pool's own page links the city tariff page
      (`price_scraper.states_city_tariff`): 21 of the 26 declared sources. Which rate: the city
      prints a separate `Eintritte Schulschwimmanlagen` rate (Fr. 5.– / 5.– / 2.50) that a
      Schulschwimmanlage charges instead of the Hallenbad rate; the kind is the discriminator,
      from the WFS roster (with the registry's display overrides). Checked FIRST: if a page ever
      stated both, the tariff link wins and the caller notes the contradiction — a page bug to
      surface, not a build failure.
    * **Free** — the page states its own gratis sentence
      (`price_scraper.states_free_admission`): the 3 pools printing *"Der Eintritt … ist gratis"*
      plus the Männerbad's *"ein Gratisbad"*. The old host test would have invented a Fr. 8.00
      charge at all four.
    * **Unknown** — neither (e.g. `hallenbad-altstetten`, a private operator whose tariff we do
      not know). The honest default, and the arm the build note rides on.
    """
    if states_city_tariff(page_html):
        table = tariffs.school if source.entry.kind is PoolKind.SCHOOL else tariffs.general
        return Tariff(table)
    if states_free_admission(page_html):
        return Free()
    return Unknown()


def scrape_declared_sources(
    client: HttpClient,
    catalog: tuple[PoolCatalogEntry, ...],
    fetched_at: datetime,
    *,
    tariffs: CityTariffs,
) -> ScrapeReport:
    """Fetch and parse every declared source, deciding each pool's ``Admission`` as it goes.

    ``tariffs`` is REQUIRED: a failed city-tariff scrape is the *caller's* fatal abort
    (`cli._compose_schedules`), so the "scrape failed but we continued" state is unrepresentable
    here — there is no ``None`` to degrade to. A pool whose page states neither the tariff nor
    free admission is still the per-pool honest ``Unknown`` (plus a note), never a failure.
    """
    extracts: list[Extract] = []
    failures: list[ScrapeFailure] = []
    notes: list[str] = []
    for source in declared_sources(catalog):
        entry, url = source
        match fetch_page(client, url):
            case Err(cause):
                failures.append(ScrapeFailure(name=entry.name, url=url, cause=cause))
                continue
            case Ok(raw):
                page = raw.decode("utf-8", "replace")

        schedule = parse_schedule(page)
        if isinstance(schedule, Err):
            failures.append(ScrapeFailure(name=entry.name, url=url, cause=schedule.error))
            continue
        notices = parse_notices(page)
        admission = admission_for(source, page, tariffs)
        if isinstance(admission, Unknown):
            # A page-stated absence, not a failure: the pool ships unpriced on purpose —
            # its page states neither the city tariff nor free admission.
            notes.append(f"no city tariff stated: {entry.pool_id} ({url})")
        elif isinstance(admission, Tariff) and states_free_admission(page):
            # Both facts on one page: the tariff link won, but the contradiction is a page
            # bug worth surfacing — never a silent pick and never a build failure.
            notes.append(
                f"contradiction: {entry.pool_id} ({url}) links the city tariff "
                "but also states free admission"
            )
        # City notices carry their own dates; an operator page states its shutdown in prose,
        # so the two closure sources are additive, not alternatives.
        operator = _OPERATOR_CLOSURES.get(entry.pool_id)
        closures = _closures_from_notices(notices)
        if operator is not None:
            closures = closures + operator(page)
        aspects = _aspects(
            entry,
            schedule.value,
            notices,
            closures,
            admission,
            fetched_at,
        )
        extracts.append((Name(entry.name), aspects))
    return ScrapeReport(extracts=tuple(extracts), failures=tuple(failures), notes=tuple(notes))
