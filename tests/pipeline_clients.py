"""CLI-level test doubles: the per-source `ProviderClients` bundle the pipeline commands take.

This lives beside the CLI tests, NOT in `tests/providers/`, on purpose. `ProviderClients` is a
composition-root type — the *provider* fixtures below it must stay usable by provider tests that
know nothing about `swimzh.cli`. So the dependency runs one way only: this module imports the
recorded provider transports from `tests.providers.wfs_snapshot`, and that module imports nothing
from the CLI.

The wiring here is the production wiring: ONE transport, wrapped in ONE `httpx.Client`, wrapped in
one `HttpClient` per source. Only the innermost transport is a fixture replayer instead of the
network — which is exactly what lets a cache test slip `DiskCacheTransport` in between.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from swimzh.cli import ProviderClients
from swimzh.core.http import RetryPolicy
from tests.providers.wfs_snapshot import recorded_build_transport, unreachable_wfs_transport


def clients_over(transport: httpx.BaseTransport) -> ProviderClients:
    """The five per-source clients over ONE offline transport — the shape `build` now takes."""
    inner = httpx.Client(transport=transport, follow_redirects=True)
    return ProviderClients.over(inner, retry=RetryPolicy(max_attempts=1))


def recorded_build_clients(
    override: Callable[[httpx.Request], httpx.Response | None] | None = None,
) -> ProviderClients:
    """`recorded_build_transport` wrapped in the per-source clients the pipeline commands take."""
    return clients_over(recorded_build_transport(override))


def unreachable_wfs_clients() -> ProviderClients:
    """Per-source clients whose shared transport refuses every connection (the WFS-down case)."""
    return clients_over(unreachable_wfs_transport())
