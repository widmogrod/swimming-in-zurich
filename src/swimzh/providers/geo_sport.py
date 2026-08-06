"""The geo_sport provider: pool locations + facility metadata from the Stadt Zürich WFS.

The reference network adapter — the whole `provider/core` contract against a real, open
(CC0) source. Covers every swimming-facility category the geoportal publishes (indoor,
outdoor, river, lake, school, paddling); each layer maps to a `PoolKind`. Note the WFS
carries locations/metadata/links but NOT opening hours (that field is `n.a.`), so schedules
come from elsewhere.

Error mapping specific to this provider:
  * transport / non-2xx / timeout  -> already a ProviderError from HttpClient
  * body is not valid JSON          -> ParseError
  * JSON valid but wrong shape      -> SchemaMismatch
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError

from swimzh.boundary.geo_sport_dto import FeatureCollectionDTO, FeatureDTO
from swimzh.core.errors import ParseError, ProviderError, SchemaMismatch
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import PoolKind

_SOURCE = "geo_sport"

WFS_URL = "https://www.ogd.stadt-zuerich.ch/wfs/geoportal/Sport"

# WFS feature-type -> the kind of pool it lists.
POOL_LAYERS: dict[str, PoolKind] = {
    "poi_hallenbad_view": PoolKind.INDOOR,
    "poi_freibad_view": PoolKind.OUTDOOR,
    "poi_flussbad_view": PoolKind.RIVER,
    "poi_seebad_view": PoolKind.LAKE,
    "poi_schulschwimmanlage_view": PoolKind.SCHOOL,
    "poi_planschbecken_view": PoolKind.PADDLING,
}

INDOOR_LAYER = "poi_hallenbad_view"


def _params(typename: str) -> dict[str, str]:
    return {
        "SERVICE": "WFS",
        "REQUEST": "GetFeature",
        "VERSION": "1.1.0",
        "TYPENAME": typename,
        "OUTPUTFORMAT": "application/json",
    }


@dataclass(frozen=True, slots=True)
class GeoPool:
    """A pool location + metadata as published by geo_sport. Reconciled to a canonical id by
    the registry downstream (lookup, not fuzzy match)."""

    source_id: str  # WFS feature id, e.g. "poi_hallenbad_view.2"
    poi_id: str | None
    name: str
    kind: PoolKind
    address: str
    geo: GeoPoint
    url: str | None
    category: str | None
    description: str | None  # from `infrastruktur` (basin sizes/temps, sauna, ...)
    phone: str | None


def _address(feature: FeatureDTO) -> str:
    p = feature.properties
    street = " ".join(part for part in (p.strasse, p.hausnummer) if part)
    town = " ".join(part for part in (p.plz, p.ort) if part)
    return ", ".join(part for part in (street, town) if part)


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = " ".join(text.replace(";", " ").split()).strip()
    return cleaned or None


# The WFS publishes `https://www.sportamt.ch/<slug>` for 17 of the 19 outdoor/river/lake pools,
# but that host has NO TLS listener: it accepts TCP on 443 and then sends nothing (clean EOF at
# ~5.1s — verified 2026-08-01 across TLS 1.0-1.3, ±SNI, ±ALPN, by-IP, and independently by SSL
# Labs). Port 80 is healthy and 302s to the real `www.stadt-zuerich.ch/<slug>` page, so we repair
# the SCHEME on the way in and let `follow_redirects` traverse the city's own live slug mapping.
# Rewriting the HOST instead would hardcode a copy of that mapping behind a user-visible
# "Official" link. Targeted repair of one known-broken host — NOT a general scheme policy.
_BROKEN_TLS_HOSTS = frozenset({"sportamt.ch", "www.sportamt.ch"})

# ONE sportamt slug is also dead, and the scheme repair alone cannot reach it: `/freibad-
# zwischen-hoelzern` 302s to `www.stadt-zuerich.ch/freibad-zwischen-hoelzern`, which **404s** —
# the city's live slug carries `-den-` (verified 2026-08-06: the `-den-` form answers 200, and so
# does the pool's own id, `freibad-zwischen-den-hoelzern`). Harmless while the pool was never
# fetched; once `OUTDOOR` entered `etl.scrape._SCRAPEABLE_KINDS` (seasonal-hours S3) the entry
# became a declared source, and a declared source that 404s aborts the whole build.
#
# Keyed by the sportamt PATH and applied only on that host, so this stays one row of data rather
# than a copy of the city's slug map: the 302 still does the host mapping, we only hand it a slug
# that resolves. A general redirect-follower cannot fix it — the 404 IS the redirect target.
_SPORTAMT_SLUG_REPAIRS: Mapping[str, str] = {
    "/freibad-zwischen-hoelzern": "/freibad-zwischen-den-hoelzern",
}


def _normalize_roster_url(raw: str | None) -> str | None:
    """Repair a roster URL on the known-broken `sportamt.ch` host — its unusable `https` SCHEME
    and, for one entry, its dead PATH. Every other URL is returned byte-identical (an unparseable
    value included), as is a sportamt URL that needs neither repair."""
    if raw is None:
        return None
    try:
        parts = urlsplit(raw)
        host = parts.hostname
    except ValueError:
        return raw
    if host is None or host.lower() not in _BROKEN_TLS_HOSTS:
        return raw
    scheme = "http" if parts.scheme == "https" else parts.scheme
    path = _SPORTAMT_SLUG_REPAIRS.get(parts.path, parts.path)
    if (scheme, path) == (parts.scheme, parts.path):
        return raw
    return urlunsplit((scheme, parts.netloc, path, parts.query, parts.fragment))


def _to_geo_pool(feature: FeatureDTO, kind: PoolKind) -> GeoPool:
    lon, lat = feature.geometry.coordinates[0], feature.geometry.coordinates[1]
    name = feature.properties.name
    if feature.properties.namenzus:
        name = f"{name} {feature.properties.namenzus}"
    return GeoPool(
        source_id=feature.id,
        poi_id=feature.properties.poi_id,
        name=name,
        kind=kind,
        address=_address(feature),
        geo=GeoPoint(lat=lat, lon=lon),
        url=_normalize_roster_url(feature.properties.www),
        category=feature.properties.kategorie,
        description=_clean(feature.properties.infrastruktur),
        phone=feature.properties.tel,
    )


def fetch_raw(client: HttpClient, typename: str) -> Result[bytes, ProviderError]:
    """The raw stage: fetch a layer's GeoJSON bytes (transport/status errors as values)."""
    match client.get(WFS_URL, params=_params(typename)):
        case Err(error):
            return Err(error)
        case Ok(resp):
            return Ok(resp.content)


def parse_pools(raw: bytes, kind: PoolKind) -> Result[list[GeoPool], ProviderError]:
    """The parse stage: bytes -> typed pools. Malformed body -> ParseError; valid JSON of
    the wrong shape -> SchemaMismatch."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        snippet = raw[:200].decode("utf-8", "replace")
        return Err(ParseError(source=_SOURCE, detail=str(exc), raw_snippet=snippet))
    try:
        collection = FeatureCollectionDTO.model_validate(payload)
    except ValidationError as exc:
        return Err(SchemaMismatch(source=_SOURCE, detail=str(exc)))
    return Ok([_to_geo_pool(f, kind) for f in collection.features])


def fetch_layer(
    client: HttpClient, typename: str, kind: PoolKind
) -> Result[list[GeoPool], ProviderError]:
    match fetch_raw(client, typename):
        case Err(error):
            return Err(error)
        case Ok(raw):
            return parse_pools(raw, kind)


def fetch_indoor_pools(client: HttpClient) -> Result[list[GeoPool], ProviderError]:
    """Fetch just the indoor pools (used by the schedule pipeline's geo-merge)."""
    return fetch_layer(client, INDOOR_LAYER, PoolKind.INDOOR)


def fetch_all_pools(client: HttpClient) -> Result[list[GeoPool], ProviderError]:
    """Fetch every published swimming-facility category. Fails fast on the first layer
    error (a partial catalog would silently hide missing categories)."""
    pools: list[GeoPool] = []
    for typename, kind in POOL_LAYERS.items():
        match fetch_layer(client, typename, kind):
            case Err(error):
                return Err(error)
            case Ok(layer_pools):
                pools.extend(layer_pools)
    return Ok(pools)
