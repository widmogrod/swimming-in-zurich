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

from swimzh.storage.atomic import atomic_swap

#: The silver documents a build reads and writes, in pipeline order. Each name is a file
#: `silver/<name>.json`; the set is closed so `pull`/`export` can enumerate without listing.
SILVER_SOURCES: Final[tuple[str, ...]] = ("roster", "prices", "schedules", "lane_plans")

DEFAULT_LAKE_ROOT: Final = Path(".lake")

_SILVER_DIR: Final = "silver"
_PULL_TIMEOUT_S: Final = 30.0


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

    def to_json_obj(self) -> dict[str, str]:
        return {
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
        )


@dataclass(frozen=True, slots=True)
class SilverDoc:
    """One silver file, decoded: its header plus the JSON payload object."""

    header: SilverHeader
    payload: dict[str, Any]


def _payload_sha(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
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
        )
        return self._store(SilverDoc(header=header, payload=previous.payload))

    def _store(self, doc: SilverDoc) -> SilverDoc:
        obj = {"silver": doc.header.to_json_obj(), "payload": doc.payload}
        text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        with atomic_swap(self.path_for(doc.header.source)) as staging:
            staging.path.write_text(text, encoding="utf-8")
            staging.commit()
        return doc

    def headers(self) -> tuple[SilverHeader, ...]:
        """The headers of every silver document present, in `SILVER_SOURCES` order."""
        found: list[SilverHeader] = []
        for source in SILVER_SOURCES:
            doc = self.read(source)
            if doc is not None:
                found.append(doc.header)
        return tuple(found)

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

    def pull(self, origin: str, *, client: httpx.Client | None = None) -> tuple[str, ...]:
        """Seed this lake's silver from a previous publish — a directory or an `http(s)://` base
        that serves `<origin>/silver/<source>.json`.

        BEST-EFFORT AND LOUD: a source the origin does not have (a 404, a missing file) is
        simply "first run for that source" and is skipped; any other failure is printed to
        stderr and that source is skipped too. Nothing here aborts: an unreachable origin makes
        the following build behave exactly like today's (every source must fetch fresh), which
        is the honest fallback — the build itself reports what it could not refresh.

        Returns the sources pulled. Pulled documents are validated by decoding them, so a
        corrupt upstream file is skipped rather than adopted.
        """
        pulled: list[str] = []
        for source in SILVER_SOURCES:
            text = _read_origin(origin, source, client)
            if text is None:
                continue
            doc = _decode_document(text, source)
            if doc is None:
                print(f"lake pull: skipping {source}: unreadable document", file=sys.stderr)
                continue
            self._store(doc)
            pulled.append(source)
        return tuple(pulled)


def _decode_document(text: str, source: str) -> SilverDoc | None:
    """Decode a pulled silver document, or `None` if it is not one for `source`."""
    try:
        obj = json.loads(text)
        header = SilverHeader.from_json_obj(obj["silver"])
        payload = obj["payload"]
    except (ValueError, KeyError, TypeError):
        return None
    if header.source != source or not isinstance(payload, dict):
        return None
    return SilverDoc(header=header, payload=payload)


def _read_origin(origin: str, source: str, client: httpx.Client | None) -> str | None:
    """The text of `<origin>/silver/<source>.json`, or `None` if it is absent/unreadable."""
    if origin.startswith(("http://", "https://")):
        url = f"{origin.rstrip('/')}/{_SILVER_DIR}/{source}.json"
        try:
            if client is None:
                response = httpx.get(url, timeout=_PULL_TIMEOUT_S, follow_redirects=True)
            else:
                response = client.get(url)
        except httpx.HTTPError as exc:
            print(f"lake pull: skipping {source}: {url}: {exc}", file=sys.stderr)
            return None
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            print(
                f"lake pull: skipping {source}: {url}: HTTP {response.status_code}",
                file=sys.stderr,
            )
            return None
        return response.text
    path = Path(origin) / _SILVER_DIR / f"{source}.json"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")
