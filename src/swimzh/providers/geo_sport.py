"""The geo_sport provider: pool locations + facility metadata from the Stadt Zürich WFS.

This is the reference network adapter — it demonstrates the whole `provider/core` contract
against a real, open (CC0) source: fetch via the value-returning `HttpClient`, then parse
into typed DTOs, mapping each failure mode to a `ProviderError` value. Consumers get
`Result[list[GeoPool], ProviderError]` and never an exception.

Error mapping specific to this provider:
  * transport / non-2xx / timeout  -> already a ProviderError from HttpClient
  * body is not valid JSON          -> ParseError
  * JSON valid but wrong shape      -> SchemaMismatch
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError

from swimzh.boundary.geo_sport_dto import FeatureCollectionDTO, FeatureDTO
from swimzh.core.errors import ParseError, ProviderError, SchemaMismatch
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok, Result, bind
from swimzh.domain.geo import GeoPoint

_SOURCE = "geo_sport"

WFS_URL = "https://www.ogd.stadt-zuerich.ch/wfs/geoportal/Sport"
INDOOR_POOL_PARAMS: dict[str, str] = {
    "SERVICE": "WFS",
    "REQUEST": "GetFeature",
    "VERSION": "1.1.0",
    "TYPENAME": "poi_hallenbad_view",
    "OUTPUTFORMAT": "application/json",
}


@dataclass(frozen=True, slots=True)
class GeoPool:
    """A pool location as published by geo_sport. Reconciled to a canonical facility id by
    the registry downstream (lookup, not fuzzy match)."""

    source_id: str  # WFS feature id, e.g. "poi_hallenbad_view.2"
    poi_id: str | None
    name: str
    address: str
    geo: GeoPoint
    url: str | None
    category: str | None


def _address(feature: FeatureDTO) -> str:
    p = feature.properties
    street = " ".join(part for part in (p.strasse, p.hausnummer) if part)
    town = " ".join(part for part in (p.plz, p.ort) if part)
    return ", ".join(part for part in (street, town) if part)


def _to_geo_pool(feature: FeatureDTO) -> GeoPool:
    lon, lat = feature.geometry.coordinates[0], feature.geometry.coordinates[1]
    name = feature.properties.name
    if feature.properties.namenzus:
        name = f"{name} {feature.properties.namenzus}"
    return GeoPool(
        source_id=feature.id,
        poi_id=feature.properties.poi_id,
        name=name,
        address=_address(feature),
        geo=GeoPoint(lat=lat, lon=lon),
        url=feature.properties.www,
        category=feature.properties.kategorie,
    )


def fetch_raw(client: HttpClient) -> Result[bytes, ProviderError]:
    """The raw stage: fetch the GeoJSON bytes (transport/status errors as values). These
    bytes are what the medallion `raw` layer persists verbatim, before any parsing."""
    match client.get(WFS_URL, params=INDOOR_POOL_PARAMS):
        case Err(error):
            return Err(error)
        case Ok(resp):
            return Ok(resp.content)


def parse_pools(raw: bytes) -> Result[list[GeoPool], ProviderError]:
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
    return Ok([_to_geo_pool(f) for f in collection.features])


def fetch_indoor_pools(client: HttpClient) -> Result[list[GeoPool], ProviderError]:
    """Convenience: fetch + parse in one call. Returns typed pools or a ProviderError value
    on any failure — transport, HTTP status, malformed body, or unexpected shape."""
    return bind(fetch_raw(client), parse_pools)
