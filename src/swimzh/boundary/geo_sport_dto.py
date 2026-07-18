"""Pydantic DTOs for the Stadt Zürich WFS `poi_hallenbad_view` GeoJSON.

The feature properties carry ~50 fields; we validate only the handful we consume and
`ignore` the rest, so an upstream adding a column does not break the parse. Geometry is
WGS84 (lon, lat) — the WFS is queried with `OUTPUTFORMAT=application/json`, which returns
coordinates in EPSG:4326.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class PointDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["Point"]
    coordinates: list[float]  # [lon, lat]


class PropertiesDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    namenzus: str | None = None  # name addition
    strasse: str | None = None
    hausnummer: str | None = None
    plz: str | None = None
    ort: str | None = None
    www: str | None = None
    poi_id: str | None = None
    kategorie: str | None = None


class FeatureDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["Feature"]
    id: str
    geometry: PointDTO
    properties: PropertiesDTO


class FeatureCollectionDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["FeatureCollection"]
    features: list[FeatureDTO]
