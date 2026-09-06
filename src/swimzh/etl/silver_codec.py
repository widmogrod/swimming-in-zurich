"""Silver payload codecs — the JSON form of each provider phase's TYPED output.

One encode/decode pair per silver source (`storage/lake.SILVER_SOURCES`). Every pair reuses a
codec gold already trusts, so a fact that survives the gold round-trip survives silver by the
same code path and no second serialization can drift:

* `roster`     — `PoolCatalogEntry` rows via `catalog_json` (the committed-catalog codec).
* `prices`     — `CityTariffs` via the boundary `PriceTableDTO`.
* `schedules`  — the scraped-side `Facility` per reconciled pool via the gold `codec` blob
                 (exactly the object `compose_facilities` folds), plus the run's audit strings.
* `lane_plans` — the discovered links + each `ParsedPlan` via the boundary `LanePlanDTO`.

Payloads are plain JSON objects (the lake stores `{"silver": header, "payload": <this>}`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from swimzh.boundary.curated_dto import LanePlanDTO, PriceTableDTO
from swimzh.boundary.mapping import (
    lane_plan_from_dto,
    lane_plan_to_dto,
    price_table_from_dto,
    price_table_to_dto,
)
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.models import Facility, reconstruct_pool_id
from swimzh.providers.belegungsplan import ParsedPlan
from swimzh.providers.page_provider import DiscoveredLink
from swimzh.providers.price_scraper import CityTariffs
from swimzh.storage import catalog_json, codec

# ── roster ──────────────────────────────────────────────────────────────────────────────────


def encode_roster(entries: tuple[PoolCatalogEntry, ...], fetched_at: datetime) -> dict[str, Any]:
    obj: dict[str, Any] = json.loads(catalog_json.dumps(entries, fetched_at))
    return obj


def decode_roster(payload: dict[str, Any]) -> tuple[PoolCatalogEntry, ...]:
    return catalog_json.loads(json.dumps(payload))


# ── prices ──────────────────────────────────────────────────────────────────────────────────


def encode_prices(tariffs: CityTariffs) -> dict[str, Any]:
    return {
        "general": price_table_to_dto(tariffs.general).model_dump(mode="json"),
        "school": price_table_to_dto(tariffs.school).model_dump(mode="json"),
    }


def decode_prices(payload: dict[str, Any]) -> CityTariffs:
    return CityTariffs(
        general=price_table_from_dto(PriceTableDTO.model_validate(payload["general"])),
        school=price_table_from_dto(PriceTableDTO.model_validate(payload["school"])),
    )


# ── schedules ───────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ScrapedSchedules:
    """The schedule phase's silver: one scraped-side facility per RECONCILED pool, plus the
    honest audit the run printed — the extract names no crosswalk entry matched (`unresolved`,
    the benign exit-1 miss) and the provider notes (a page stating no city tariff, ...)."""

    facilities: tuple[Facility, ...]
    unresolved: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def encode_schedules(scraped: ScrapedSchedules) -> dict[str, Any]:
    return {
        "facilities": [json.loads(codec.dumps(f)) for f in scraped.facilities],
        "unresolved": list(scraped.unresolved),
        "notes": list(scraped.notes),
    }


def decode_schedules(payload: dict[str, Any]) -> ScrapedSchedules:
    return ScrapedSchedules(
        facilities=tuple(codec.loads(json.dumps(f)) for f in payload["facilities"]),
        unresolved=tuple(str(n) for n in payload.get("unresolved", [])),
        notes=tuple(str(n) for n in payload.get("notes", [])),
    )


# ── lane plans ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ScrapedLanePlans:
    """The lane phase's silver: the Belegungsplan links each pool page advertised (the
    discovery hop's result — what `undiscovered_authored` audits against) and every parsed
    sheet, keyed by the URL it was fetched from."""

    links: tuple[DiscoveredLink, ...]
    plans: tuple[ParsedPlan, ...]


def encode_lane_plans(scraped: ScrapedLanePlans) -> dict[str, Any]:
    return {
        "links": [{"pool_id": str(link.pool_id), "url": link.url} for link in scraped.links],
        "plans": [
            {
                "basin_hint": plan.basin_hint,
                "source_url": plan.source_url,
                "plan": lane_plan_to_dto(plan.plan).model_dump(mode="json"),
            }
            for plan in scraped.plans
        ],
    }


def decode_lane_plans(payload: dict[str, Any]) -> ScrapedLanePlans:
    return ScrapedLanePlans(
        links=tuple(
            DiscoveredLink(pool_id=reconstruct_pool_id(str(link["pool_id"])), url=str(link["url"]))
            for link in payload["links"]
        ),
        plans=tuple(
            ParsedPlan(
                basin_hint=str(plan["basin_hint"]),
                plan=lane_plan_from_dto(LanePlanDTO.model_validate(plan["plan"])),
                source_url=str(plan["source_url"]),
            )
            for plan in payload["plans"]
        ),
    )
