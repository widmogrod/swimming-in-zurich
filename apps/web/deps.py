"""Dependency accessors over `app.state` (wired in main.py's lifespan). Kept separate from
main.py so routers can import getters without a router↔composition-root import cycle.
"""

from __future__ import annotations

from fastapi import Request

from apps.web.services.ports import SwimData


def get_swim_data(request: Request) -> SwimData:
    data: SwimData = request.app.state.swim_data
    return data
