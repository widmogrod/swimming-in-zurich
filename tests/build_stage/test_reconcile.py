"""`reconcile.resolve` is the sole PoolId producer — by lookup, never fuzzy; loud on miss."""

from __future__ import annotations

from swimzh.build.reconcile import (
    BasinHint,
    Crosswalk,
    Global,
    Name,
    PoolId,
    SourceRef,
    Xref,
    build_basin_hint_index,
    crosswalk_from_rows,
    resolve,
    resolve_all,
)
from swimzh.core.errors import SchemaMismatch
from swimzh.core.result import Err, Ok
from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    Facility,
    FacilityId,
    PoolIdentity,
    PoolKind,
    Provenance,
)


def _crosswalk() -> Crosswalk:
    city = PoolId("hallenbad-city")
    return Crosswalk(
        xref={("geo_sport", "poi_hallenbad_view.2"): city, ("crowdmonitor", "City"): city},
        alias={"hallenbad city": city, "city": city},
        basin_hint={"hallenbad city schwimmerbecken": city},
        ambiguous_hints=frozenset({"twin bad schwimmerbecken"}),
    )


def test_resolve_xref_hit() -> None:
    result = resolve(Xref("geo_sport", "poi_hallenbad_view.2"), _crosswalk())
    assert result == Ok(PoolId("hallenbad-city"))


def test_resolve_name_hit_uses_normalized_key() -> None:
    # A messy display name still resolves — the alias index is keyed on the normalized form.
    assert resolve(Name("  Hallenbad   CITY "), _crosswalk()) == Ok(PoolId("hallenbad-city"))


def test_resolve_basin_hint_hit() -> None:
    result = resolve(BasinHint("Hallenbad City Schwimmerbecken"), _crosswalk())
    assert result == Ok(PoolId("hallenbad-city"))


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


def test_resolve_ambiguous_basin_hint_is_loud_err_never_guessed() -> None:
    result = resolve(BasinHint("Twin Bad Schwimmerbecken"), _crosswalk())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "ambiguous" in result.error.detail.lower()


def test_resolve_unknown_basin_hint_is_loud_err() -> None:
    result = resolve(BasinHint("Hallenbad City Variobecken"), _crosswalk())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "Variobecken" in result.error.detail


def test_resolve_global_is_not_a_single_pool() -> None:
    # An identity-free payload (a city-wide price table) belongs to many pools — resolve is
    # honest and refuses to mint a single id (compose fans it out later).
    result = resolve(Global(), _crosswalk())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "identity-free" in result.error.detail


def test_crosswalk_resolve_method_delegates() -> None:
    assert _crosswalk().resolve(Name("city")) == Ok(PoolId("hallenbad-city"))


# --- resolve_all: batch resolution, loud on any miss --------------------------------


def test_resolve_all_keys_every_extract_on_success() -> None:
    extracts: list[tuple[SourceRef, str]] = [
        (Name("Hallenbad City"), "payload-a"),
        (Xref("crowdmonitor", "City"), "payload-b"),
    ]
    result = resolve_all(extracts, _crosswalk())
    assert result == Ok(
        ((PoolId("hallenbad-city"), "payload-a"), (PoolId("hallenbad-city"), "payload-b"))
    )


def test_resolve_all_is_loud_on_any_unresolved_ref() -> None:
    # One good, one unresolvable -> the whole batch is a typed Err naming the offender; the
    # caller never silently attaches "payload-b" to a guessed pool.
    extracts = [(Name("Hallenbad City"), "payload-a"), (Name("Hallenbad Nonexistent"), "payload-b")]
    result = resolve_all(extracts, _crosswalk())
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "Hallenbad Nonexistent" in result.error.detail


# --- basin-hint index + crosswalk_from_rows -----------------------------------------


def _facility() -> Facility:
    return Facility(
        identity=PoolIdentity(FacilityId("hallenbad-city"), "Hallenbad City", PoolKind.INDOOR),
        address="",
        provenance=Provenance(source="curated", curated=True),
        basins=(Basin(basin_id=BasinId("city-50m"), name="50m", rules=(), kind=BasinKind.LAP),),
    )


def test_build_basin_hint_index_keys_name_by_basin_word() -> None:
    index, ambiguous = build_basin_hint_index((_facility(),))
    assert index["hallenbad city schwimmerbecken"] == PoolId("hallenbad-city")
    assert ambiguous == set()


def test_crosswalk_from_rows_mints_ids_and_resolves() -> None:
    crosswalk = crosswalk_from_rows(
        alias_rows=[("hallenbad city", "hallenbad-city")],
        xref_rows=[("geo_sport", "poi_hallenbad_view.2", "hallenbad-city")],
        curated=(_facility(),),
    )
    assert crosswalk.resolve(Name("Hallenbad City")) == Ok(PoolId("hallenbad-city"))
    assert crosswalk.resolve(Xref("geo_sport", "poi_hallenbad_view.2")) == Ok(
        PoolId("hallenbad-city")
    )
    assert crosswalk.resolve(BasinHint("Hallenbad City Schwimmerbecken")) == Ok(
        PoolId("hallenbad-city")
    )
