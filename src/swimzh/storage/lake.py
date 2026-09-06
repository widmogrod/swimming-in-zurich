"""The lake: the pipeline-owned SILVER layer — one typed JSON document per provider source.

`swimzh build` keeps three layers under one directory the CODE owns (`--lake`, default `.lake/`):

* **raw** — the provider HTTP cache (`core/httpcache`), the city's own HTML/PDF bytes. Private
  and ephemeral; never published (re-hosting a third party's pages is not scraping them).
* **silver** — THIS module: `silver/<source>.json`, our own typed facts per source, each under a
  header naming *where the facts came from and how old they are* (`SilverHeader`). Small,
  diffable, safe to publish: the build exports it beside the store and the NEXT run pulls it
  back first, so last time's output is this time's input on any host — laptop, CI, a server.
* **gold** — the composed SQLite store, built from silver ONLY (never from raw directly).

GitHub is a trigger and a host, not the pipeline: it calls one command and serves one folder.
Nothing here knows about git, Actions, or Pages. `pull` reads a directory OR an `http(s)://`
base; `export` writes a directory. That is the whole runtime contract.

A silver document is `{"silver": <header>, "payload": <object>}`. The header's `status` is the
provenance signal gold and the manifest carry forward: `fresh` when this payload came from a
successful fetch, `stale` when a run kept a previous payload because the source was unreachable
(`etl/refresh.stale_if_transient`). A run REWRITES the header on a stale replay so a published
lake says so; the payload bytes are untouched.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final

import httpx

from swimzh.core.errors import HttpStatus, ProviderError, SchemaMismatch
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok, Result
from swimzh.storage.atomic import atomic_swap

#: The silver documents a build reads and writes, in pipeline order. Each name is a file
#: `silver/<name>.json`; the set is closed so `pull`/`export` can enumerate without listing.
SILVER_SOURCES: Final[tuple[str, ...]] = ("roster", "prices", "schedules", "lane_plans")

DEFAULT_LAKE_ROOT: Final = Path(".lake")

#: The silver envelope's schema. Bump when a payload codec changes what it carries: a document
#: written under another schema is treated as ABSENT (a first run for that source), never decoded
#: with today's codec — the 2026-09-06 audit found a roster silver that silently lacked `poi_id`.
SILVER_SCHEMA: Final = 2

_SILVER_DIR: Final = "silver"
_PULL_TIMEOUT_S: Final = 30.0
#: The `HttpClient.source` of a pull. It has NO row in `core/cache_tiers.CACHE_POLICIES` on
#: purpose: a pull must never be served from the provider disk cache (last week's silver is the
#: one thing a run wants current), and `pull` builds its own uncached transport anyway — the
#: tier stamp `policy_for` falls back to is inert without a `DiskCacheTransport` underneath.
_PULL_SOURCE: Final = "lake"


class SilverStatus(Enum):
    """Whether a silver payload came from THIS run's fetch or was kept from an earlier one."""

    FRESH = "fresh"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class SilverHeader:
    """Provenance of one silver payload: which source, fetched when, fresh or kept-stale, and a
    content hash so an unchanged payload is byte-provably unchanged across runs."""

    source: str
    fetched_at: datetime
    status: SilverStatus
    content_sha: str
    schema: int = SILVER_SCHEMA

    def to_json_obj(self) -> dict[str, str | int]:
        return {
            "schema": self.schema,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
            "status": self.status.value,
            "content_sha": self.content_sha,
        }

    @staticmethod
    def from_json_obj(obj: dict[str, Any]) -> SilverHeader:
        fetched_at = datetime.fromisoformat(str(obj["fetched_at"]))
        if fetched_at.tzinfo is None:
            raise ValueError("silver header fetched_at must be timezone-aware")
        return SilverHeader(
            source=str(obj["source"]),
            fetched_at=fetched_at,
            status=SilverStatus(str(obj["status"])),
            content_sha=str(obj["content_sha"]),
            schema=int(obj.get("schema", 0)),
        )


@dataclass(frozen=True, slots=True)
class SilverDoc:
    """One silver file, decoded: its header plus the JSON payload object."""

    header: SilverHeader
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PullReport:
    """What one `Lake.pull` did, per source, in `SILVER_SOURCES` order.

    `pulled` were adopted; `absent` the origin does not have (a 404 or a missing file — "first
    run for that source", not a failure); `failed` carry the typed reason each was skipped: a
    `ProviderError` straight from the transport (`HttpStatus`, `ConnectionFailed`, ...) or a
    `SchemaMismatch` for a document that was fetched but is not a silver for that source.
    """

    pulled: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()
    failed: tuple[tuple[str, ProviderError], ...] = ()


#: Keys that name WHEN a payload was produced rather than WHAT it says (`valid_as_of` is the
#: scrape date stamped onto prices and provenance, not a fact from any page — a plan's own
#: `valid_from` IS a fact and is kept). The content hash skips them at any depth, so a re-fetch of
#: unchanged facts hashes the same and a changed sha means the facts changed — the only reading
#: that makes `content_sha` worth publishing.
_RUN_STAMP_KEYS: Final = frozenset({"fetched_at", "generated_at", "valid_as_of"})


def _without_run_stamps(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_run_stamps(v) for k, v in value.items() if k not in _RUN_STAMP_KEYS}
    if isinstance(value, list):
        return [_without_run_stamps(v) for v in value]
    return value


def _payload_sha(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        _without_run_stamps(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Lake:
    """The silver directory under one lake root. Every write is whole-file atomic."""

    def __init__(self, root: Path = DEFAULT_LAKE_ROOT) -> None:
        self.root = Path(root)

    @property
    def silver_dir(self) -> Path:
        return self.root / _SILVER_DIR

    def path_for(self, source: str) -> Path:
        return self.silver_dir / f"{source}.json"

    def read(self, source: str) -> SilverDoc | None:
        """The stored document for `source`, or `None` when this lake has never held one.

        A present-but-unreadable file raises: silently treating a corrupt silver as "first run"
        would refetch and overwrite the one copy of last week's facts without a word.
        """
        path = self.path_for(source)
        if not path.exists():
            return None
        obj = json.loads(path.read_text(encoding="utf-8"))
        # Schema first, before the header is parsed: a document from another schema is absent by
        # definition, whatever else is in it.
        schema = int(obj.get("silver", {}).get("schema", 0)) if isinstance(obj, dict) else 0
        if schema != SILVER_SCHEMA:
            print(
                f"lake: ignoring {path} (silver schema {schema}, this build writes "
                f"{SILVER_SCHEMA}); {source} will be fetched as a first run",
                file=sys.stderr,
            )
            return None
        header = SilverHeader.from_json_obj(obj["silver"])
        payload = obj["payload"]
        if not isinstance(payload, dict):
            raise TypeError(f"silver payload for {source} is not an object")
        if header.source != source:
            raise ValueError(f"silver file {path} claims source {header.source!r}")
        return SilverDoc(header=header, payload=payload)

    def write(self, source: str, payload: dict[str, Any], *, fetched_at: datetime) -> SilverDoc:
        """Store a freshly fetched payload under a `fresh` header."""
        header = SilverHeader(
            source=source,
            fetched_at=fetched_at,
            status=SilverStatus.FRESH,
            content_sha=_payload_sha(payload),
        )
        return self._store(SilverDoc(header=header, payload=payload))

    def mark_stale(self, source: str) -> SilverDoc:
        """Rewrite `source`'s header as `stale`, payload untouched. Raises if absent — there is
        nothing to mark, and the caller's refresh policy should have aborted instead."""
        previous = self.read(source)
        if previous is None:
            raise LookupError(f"no silver document for {source} to mark stale")
        header = SilverHeader(
            source=previous.header.source,
            fetched_at=previous.header.fetched_at,
            status=SilverStatus.STALE,
            content_sha=previous.header.content_sha,
            schema=previous.header.schema,
        )
        return self._store(SilverDoc(header=header, payload=previous.payload))

    def _store(self, doc: SilverDoc) -> SilverDoc:
        obj = {"silver": doc.header.to_json_obj(), "payload": doc.payload}
        text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        with atomic_swap(self.path_for(doc.header.source)) as staging:
            staging.path.write_text(text, encoding="utf-8")
            staging.commit()
        return doc

    # ── runtime seams: where the previous silver comes from, where this one goes ──────────

    def export(self, out: Path) -> tuple[str, ...]:
        """Copy every present silver file to `out/silver/`. Returns the sources copied."""
        target = Path(out) / _SILVER_DIR
        target.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for source in SILVER_SOURCES:
            path = self.path_for(source)
            if path.exists():
                shutil.copyfile(path, target / path.name)
                copied.append(source)
        return tuple(copied)

    def pull(self, origin: str, *, client: HttpClient | None = None) -> PullReport:
        """Seed this lake's silver from a previous publish — a directory or an `http(s)://` base
        that serves `<origin>/silver/<source>.json`.

        BEST-EFFORT AND TYPED: a source the origin does not have (a 404, a missing file) is
        simply "first run for that source" (`absent`); any other failure is reported as a typed
        value in `failed` and that source is skipped too. Nothing here raises or aborts: an
        unreachable origin makes the following build behave exactly like today's (every source
        must fetch fresh), which is the honest fallback — the build itself reports what it could
        not refresh. Printing is the caller's job (`cli.lake_command`).

        Pulled documents are validated by decoding them, so a corrupt upstream file is reported
        (`SchemaMismatch`) rather than adopted. For an http origin without a `client`, a plain
        uncached `HttpClient` is built for the pull (see `_PULL_SOURCE`).
        """
        if _is_http(origin) and client is None:
            with httpx.Client(timeout=_PULL_TIMEOUT_S, follow_redirects=True) as inner:
                return self.pull(origin, client=_pull_client(inner))
        pulled: list[str] = []
        absent: list[str] = []
        failed: list[tuple[str, ProviderError]] = []
        for source in SILVER_SOURCES:
            match _read_origin(origin, source, client):
                case Ok(None):
                    absent.append(source)
                case Ok(str() as text):
                    match _decode_document(text, source):
                        case Ok(doc):
                            self._store(doc)
                            pulled.append(source)
                        case Err(error):
                            failed.append((source, error))
                case Err(error):
                    failed.append((source, error))
        return PullReport(pulled=tuple(pulled), absent=tuple(absent), failed=tuple(failed))


def _is_http(origin: str) -> bool:
    return origin.startswith(("http://", "https://"))


def _pull_client(inner: httpx.Client) -> HttpClient:
    return HttpClient(inner, source=_PULL_SOURCE, timeout_s=_PULL_TIMEOUT_S)


def _decode_document(text: str, source: str) -> Result[SilverDoc, SchemaMismatch]:
    """Decode a pulled silver document, or say why it is not one for `source`."""

    def mismatch(detail: str) -> Err[SchemaMismatch]:
        return Err(SchemaMismatch(source=_PULL_SOURCE, detail=f"{source}: {detail}"))

    try:
        obj = json.loads(text)
        header = SilverHeader.from_json_obj(obj["silver"])
        payload = obj["payload"]
    except (ValueError, KeyError, TypeError) as exc:
        return mismatch(f"unreadable silver document: {exc}")
    if header.source != source:
        return mismatch(f"document claims source {header.source!r}")
    if not isinstance(payload, dict):
        return mismatch("payload is not an object")
    if header.schema != SILVER_SCHEMA:
        return mismatch(f"silver schema {header.schema}, this build reads {SILVER_SCHEMA}")
    return Ok(SilverDoc(header=header, payload=payload))


def _read_origin(
    origin: str, source: str, client: HttpClient | None
) -> Result[str | None, ProviderError]:
    """The text of `<origin>/silver/<source>.json`; `Ok(None)` when the origin has no such
    document (a 404 / a missing file), `Err` for any other failure."""
    if _is_http(origin):
        if client is None:  # pragma: no cover - `pull` always supplies one for an http origin
            raise ValueError("an http(s) origin needs an HttpClient")
        url = f"{origin.rstrip('/')}/{_SILVER_DIR}/{source}.json"
        match client.get(url):
            case Ok(response):
                return Ok(response.text)
            case Err(HttpStatus(status=404)):
                return Ok(None)
            case Err(error):
                return Err(error)
    path = Path(origin) / _SILVER_DIR / f"{source}.json"
    if not path.exists():
        return Ok(None)
    return Ok(path.read_text(encoding="utf-8"))
