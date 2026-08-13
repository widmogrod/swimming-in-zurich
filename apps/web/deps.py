"""Dependency accessors over `app.state` (wired in main.py's lifespan). Kept separate from
main.py so routers can import getters without a router↔composition-root import cycle.
"""

from __future__ import annotations

from fastapi import Request

from apps.web.services.ports import SwimStore, TemperatureProvider


def get_swim_data(request: Request) -> SwimStore:
    data: SwimStore = request.app.state.swim_data
    return data


def get_temperature_provider(request: Request) -> TemperatureProvider | None:
    """The wired live water-temperature provider, or `None` when none is configured.

    Fail-open by design: `None` is a valid state (the router turns it into a
    `TempUnavailable("live temperature not configured")`), so this reads defensively — a launch
    path that never set `app.state.temperature` still yields `None`, never an `AttributeError`."""
    provider: TemperatureProvider | None = getattr(request.app.state, "temperature", None)
    return provider
