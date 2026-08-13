"""Discover a pool's sub-resource links from its official page — the DISCOVERY HOP.

A pool page carries not just facts (schedule rows, notices — parsed elsewhere) but *links to
sub-resources*: the per-basin Belegungsplan PDFs. This provider extracts those links and stamps
each with the **owning ``PoolId``** so the downstream fetch-set and join stay deterministic
(id + URL keyed, never a fuzzy content match). The discovered links become the fetch-set of the
lane provider (``etl/lane_plans.py``) — replacing the hand-authored ``lane_plan_source`` URL as
the *thing that drives extraction*. Because the links are re-derived from the live page every
run, they cannot rot or acquire an unknown origin: the origin IS this extraction.

Scope (S2): this module discovers the **Belegungsplan** sub-resource class only — the links that
live under ``.../dokumente/badeanlagen/belegungsplaene/*.pdf``. Other sub-resource classes (a
price page, a reservation endpoint) are additional predicates a later slice adds here; the shape
(``DiscoveredLink`` stamped with its ``PoolId``) is the same.

Discovery is best-effort against a brittle page format: a page that can't be fetched is a typed
``ProviderError`` (recorded as a ``PageMiss``, never swallowed); a page with no Belegungsplan
link simply yields none. The binding of a discovered URL back to a specific *basin* is NOT made
here — that stays a deterministic URL-keyed join in ``etl/silver.py`` against the basin's
declared source; this provider only discovers and stamps the parent ``PoolId``.
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urljoin

from swimzh.core.errors import ProviderError
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.models import PoolId

# A Belegungsplan link: an ``href`` (single- or double-quoted) whose path sits under the
# ``belegungsplaene`` document folder and ends in ``.pdf``. Relative (``/content/dam/...``) or
# absolute — resolved against the page URL below. Anchored on the folder segment so an unrelated
# PDF elsewhere on the page is not mistaken for a lane plan.
_BELEGUNGSPLAN_HREF = re.compile(
    r"""href\s*=\s*["']([^"']*belegungsplaene/[^"']+?\.pdf)["']""",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DiscoveredLink:
    """A sub-resource link discovered on a pool page, stamped with the owning ``PoolId``.

    The ``PoolId`` is the parent's stable identity carried across the discovery hop, so provider
    N+1 (the lane provider) joins its result back deterministically — never a fuzzy content
    match. ``url`` is absolute (relative page hrefs are resolved against the page URL)."""

    pool_id: PoolId
    url: str


@dataclass(frozen=True, slots=True)
class PageDoc:
    """What a pool's official page yields to the discovery hop.

    S2 populates ``discovered_links`` (the Belegungsplan sub-resources). The fuller page document
    the design calls for — facility ``schedule_rows`` + ``notices`` folded in from the schedule
    provider — is assembled in a later slice; this carries the discovery output only."""

    pool_id: PoolId
    discovered_links: tuple[DiscoveredLink, ...]


@dataclass(frozen=True, slots=True)
class PageMiss:
    """A pool page whose fetch FAILED — the real typed cause, kept for the operator audit. The
    page's sub-resources simply aren't discovered this run (best-effort; a later slice hardens
    this to a whole-build abort)."""

    pool_id: PoolId
    page_url: str
    cause: ProviderError


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    """The outcome of discovering across a set of pool pages: every discovered link (stamped with
    its parent ``PoolId``) and every page that failed to fetch (typed cause)."""

    links: tuple[DiscoveredLink, ...]
    page_misses: tuple[PageMiss, ...]


def discover_links(page_html: str, pool_id: PoolId, page_url: str) -> tuple[DiscoveredLink, ...]:
    """Extract the Belegungsplan sub-resource links from one page's HTML, each stamped with
    ``pool_id`` and resolved to an absolute URL against ``page_url``.

    Deterministic and deduped: distinct absolute URLs in first-seen order. A relative href
    (``/content/dam/...``) resolves against the page URL; an already-absolute href is left as-is.
    A page with no Belegungsplan link yields an empty tuple (not an error — absence is not
    failure)."""
    seen: dict[str, None] = {}
    for href in _BELEGUNGSPLAN_HREF.findall(html.unescape(page_html)):
        seen.setdefault(urljoin(page_url, href.strip()), None)
    return tuple(DiscoveredLink(pool_id=pool_id, url=url) for url in seen)


def fetch_page_doc(
    client: HttpClient, pool_id: PoolId, page_url: str
) -> Result[PageDoc, ProviderError]:
    """Fetch a pool page and discover its sub-resource links. A transport/status error is
    returned as a typed value (never raised)."""
    match client.get(page_url):
        case Err(error):
            return Err(error)
        case Ok(resp):
            page_html = resp.content.decode("utf-8", "replace")
            return Ok(PageDoc(pool_id, discover_links(page_html, pool_id, page_url)))


def discover_pages(client: HttpClient, pages: Sequence[tuple[PoolId, str]]) -> DiscoveryReport:
    """Run the discovery hop across many pool pages: fetch each ``(pool_id, page_url)`` and
    collect the discovered links, recording each un-fetchable page as a typed ``PageMiss``.

    The returned ``links`` ARE the lane provider's fetch-set — a projection of what the pages
    advertise, not of any hand-authored list."""
    links: list[DiscoveredLink] = []
    misses: list[PageMiss] = []
    for pool_id, page_url in pages:
        match fetch_page_doc(client, pool_id, page_url):
            case Ok(doc):
                links.extend(doc.discovered_links)
            case Err(cause):
                misses.append(PageMiss(pool_id=pool_id, page_url=page_url, cause=cause))
    return DiscoveryReport(links=tuple(links), page_misses=tuple(misses))
