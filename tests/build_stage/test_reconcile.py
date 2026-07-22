"""`reconcile.resolve` is the sole PoolId producer — by lookup, never fuzzy; loud on miss."""

from __future__ import annotations

import pytest

from swimzh.build.reconcile import (
    Crosswalk,
    Name,
    ReconcileOutcome,
    SourceRef,
    Xref,
    crosswalk_from_rows,
    resolve,
    resolve_all,
)
from swimzh.core.errors import SchemaMismatch
from swimzh.core.result import Err, Ok
from swimzh.domain.models import PoolId


def _crosswalk() -> Crosswalk:
    city = PoolId("hallenbad-city")
    return Crosswalk(
        xref={("geo_sport", "poi_hallenbad_view.2"): city, ("crowdmonitor", "City"): city},
        alias={"hallenbad city": city, "city": city},
    )


def test_resolve_xref_hit() -> None:
    result = resolve(Xref("geo_sport", "poi_hallenbad_view.2"), _crosswalk())
    assert result == Ok(PoolId("hallenbad-city"))


def test_resolve_name_hit_uses_normalized_key() -> None:
    # A messy display name still resolves — the alias index is keyed on the normalized form.
    assert resolve(Name("  Hallenbad   CITY "), _crosswalk()) == Ok(PoolId("hallenbad-city"))


def test_resolve_unknown_xref_is_loud_err() -> None:
    result = resolve(Xref("geo_sport", "poi_nope.99"), _crosswalk())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "poi_nope.99" in result.error.detail


def test_resolve_unknown_name_is_loud_err() -> None:
    result = resolve(Name("Hallenbad Nonexistent"), _crosswalk())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "Hallenbad Nonexistent" in result.error.detail


def test_crosswalk_resolve_method_delegates() -> None:
    assert _crosswalk().resolve(Name("city")) == Ok(PoolId("hallenbad-city"))


# --- resolve_all: resilient to benign misses ----------------------------------------


def test_resolve_all_keys_every_extract_on_success() -> None:
    extracts: list[tuple[SourceRef, str]] = [
        (Name("Hallenbad City"), "payload-a"),
        (Xref("crowdmonitor", "City"), "payload-b"),
    ]
    result = resolve_all(extracts, _crosswalk())
    # An all-resolve batch: every pool in `resolved`, `unresolved` empty.
    assert result == Ok(
        ReconcileOutcome(
            resolved=(
                (PoolId("hallenbad-city"), "payload-a"),
                (PoolId("hallenbad-city"), "payload-b"),
            ),
            unresolved=(),
        )
    )


def test_resolve_all_collects_benign_miss_and_keeps_the_rest() -> None:
    # A benign no-crosswalk miss no longer aborts the batch: the good scrape is kept in
    # `resolved`, the unmatched name is reported (by display label) in `unresolved`.
    extracts: list[tuple[SourceRef, str]] = [
        (Name("Hallenbad City"), "payload-a"),
        (Name("Hallenbad Nonexistent"), "payload-b"),
    ]
    result = resolve_all(extracts, _crosswalk())
    assert result == Ok(
        ReconcileOutcome(
            resolved=((PoolId("hallenbad-city"), "payload-a"),),
            unresolved=("Hallenbad Nonexistent",),
        )
    )


def test_resolve_all_unresolved_is_required_no_default() -> None:
    # The required `unresolved` field means a caller cannot construct an outcome that
    # silently swallows a miss.
    with pytest.raises(TypeError):
        ReconcileOutcome(resolved=())  # type: ignore[call-arg]


# --- crosswalk_from_rows ------------------------------------------------------------


def test_crosswalk_from_rows_mints_ids_and_resolves() -> None:
    crosswalk = crosswalk_from_rows(
        alias_rows=[("hallenbad city", "hallenbad-city")],
        xref_rows=[("geo_sport", "poi_hallenbad_view.2", "hallenbad-city")],
    )
    assert crosswalk.resolve(Name("Hallenbad City")) == Ok(PoolId("hallenbad-city"))
    assert crosswalk.resolve(Xref("geo_sport", "poi_hallenbad_view.2")) == Ok(
        PoolId("hallenbad-city")
    )
