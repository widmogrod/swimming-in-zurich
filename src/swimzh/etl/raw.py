"""Raw stage: capture provider payloads verbatim, with provenance (source, url,
fetched_at, sha256), so any downstream derivation is reproducible and auditable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from swimzh.core.errors import ProviderError
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok, Result
from swimzh.providers import geo_sport


@dataclass(frozen=True, slots=True)
class RawArtifact:
    source: str
    url: str
    fetched_at: datetime
    sha256: str
    content: bytes


def capture_geo(client: HttpClient, fetched_at: datetime) -> Result[RawArtifact, ProviderError]:
    """Fetch the geo_sport GeoJSON bytes and wrap them with provenance."""
    match geo_sport.fetch_raw(client):
        case Err(error):
            return Err(error)
        case Ok(content):
            return Ok(
                RawArtifact(
                    source="geo_sport",
                    url=geo_sport.WFS_URL,
                    fetched_at=fetched_at,
                    sha256=hashlib.sha256(content).hexdigest(),
                    content=content,
                )
            )


def write_raw(raw_dir: Path, artifact: RawArtifact) -> Path:
    """Persist the raw bytes for audit/replay. Returns the written path."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{artifact.source}.json"
    path.write_bytes(artifact.content)
    return path
