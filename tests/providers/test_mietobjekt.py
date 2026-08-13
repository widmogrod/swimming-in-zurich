"""`parse_mietobjekte` turns a pool page's ``Mietobjekt | Preis`` table into lockers and
rentals — routed by German noun, costs decomposed on the orthogonal fee/deposit axes, prose
cells preserved (never crashed on), garble fatal, and absence of the table not an error.

Pinned against the COMMITTED declared-source fixtures — the whole population the build
scrapes — so the corpus sweep at the bottom is exactly the exposure surface of the
fail-fast build: a cell shape this parser cannot read would abort a real `swimzh build`.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from swimzh.core.errors import ParseError
from swimzh.core.result import Err, Ok
from swimzh.domain.lockers import LockerCategory, LockerOption
from swimzh.domain.rentals import Gratis, Priced, RentalItem, RentalKind, Unstated
from swimzh.providers.mietobjekt import MietobjektTable, parse_mietobjekte
from tests.declared_fixtures import (
    CABIN_NOUN,
    LOCKER_NOUN,
    MIETOBJEKT_NOUN,
    PAGE_FIXTURES,
    PARASOL_NOUN,
    RENTAL_WEAR_NOUN,
    SUNLOUNGER_NOUN,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _parsed(name: str) -> MietobjektTable:
    result = parse_mietobjekte(_page(name))
    assert isinstance(result, Ok), result
    return result.value


# --- the S1 acceptance page: Hallenbad City ---------------------------------------------


def test_city_yields_exactly_the_four_locker_rows() -> None:
    """Wardrobe + valuables (free, Fr. 5 deposit) and the two Wäschefach terms — with the
    `(1/2 Jahr)`-style suffix carried as `period` VERBATIM, deliberately unparsed."""
    table = _parsed("hallenbad_city.html")
    assert table.lockers == (
        LockerOption(
            category=LockerCategory.WARDROBE,
            fee_chf=None,
            deposit_chf=Decimal("5.00"),
            raw="Garderobenkasten | gratis, plus Depot Fr. 5.–",
        ),
        LockerOption(
            category=LockerCategory.VALUABLES,
            fee_chf=None,
            deposit_chf=Decimal("5.00"),
            raw="Wertsachenfach | gratis, plus Depot Fr. 5.–",
        ),
        LockerOption(
            category=LockerCategory.LAUNDRY,
            fee_chf=Decimal("240.00"),
            deposit_chf=None,
            period="1/2 Jahr",
            raw="Wäschefach (1/2 Jahr) | Fr. 240.–",
        ),
        LockerOption(
            category=LockerCategory.LAUNDRY,
            fee_chf=Decimal("400.00"),
            deposit_chf=None,
            period="1 Jahr",
            raw="Wäschefach (1 Jahr) | Fr. 400.–",
        ),
    )


def test_city_routes_the_non_locker_rows_to_rentals_not_to_the_floor() -> None:
    """The other half of the same table: towel/swimwear/goggles at Fr. 3 + Fr. 20 deposit.
    Parsed since S1; wired onto the facility — with the fee as the closed union — in S2."""
    table = _parsed("hallenbad_city.html")
    assert [(r.kind, r.fee, r.deposit_chf) for r in table.rentals] == [
        (RentalKind.TOWEL, Priced(Decimal("3.00")), Decimal("20.00")),
        (RentalKind.SWIMWEAR, Priced(Decimal("3.00")), Decimal("20.00")),
        (RentalKind.GOGGLES, Priced(Decimal("3.00")), Decimal("20.00")),
    ]


def test_the_synthetic_unknown_label_lands_as_other_with_raw_not_on_the_floor() -> None:
    """The no-drop guarantee, pinned synthetically (S2 acceptance): a label no route knows —
    `Luftmatratze | Fr. 5.–` — parses to `RentalItem(OTHER, Priced(5), raw=…)`; nothing a
    future page invents can be silently dropped."""
    page = (
        '<stzh-datatable columns="[{&#34;text&#34;:&#34;Mietobjekt&#34;},'
        '{&#34;text&#34;:&#34;Preis&#34;}]" rows="[[{&#34;value&#34;:&#34;Luftmatratze&#34;},'
        '{&#34;value&#34;:&#34;Fr. 5.–&#34;}]]"></stzh-datatable>'
    )
    result = parse_mietobjekte(page)
    assert isinstance(result, Ok)
    assert result.value == MietobjektTable(
        rentals=(
            RentalItem(
                kind=RentalKind.OTHER,
                fee=Priced(Decimal("5.00")),
                raw="Luftmatratze | Fr. 5.–",
            ),
        )
    )


# --- absence vs garble ------------------------------------------------------------------


def test_a_declared_page_without_the_table_yields_empty_tuples_not_an_error() -> None:
    # maennerbad is a real declared source whose committed page carries no Mietobjekt table:
    # absence is data (6 of the 26 declared pages), never a build-aborting failure.
    assert _parsed("maennerbad.html") == MietobjektTable(lockers=(), rentals=())


def test_a_page_with_no_datatable_at_all_yields_empty_tuples() -> None:
    assert parse_mietobjekte("<html><body>kein Tisch</body></html>") == Ok(MietobjektTable())


def test_a_garbled_price_cell_in_a_present_table_is_a_fatal_parse_error() -> None:
    """A `Fr.` token with no parseable amount is garble, not prose — `Err(ParseError)`, which
    under the build's fail-fast posture aborts the run instead of persisting a wrong price."""
    page = _page("hallenbad_city.html")
    assert "Fr. 240.–" in page  # the premise is real
    result = parse_mietobjekte(page.replace("Fr. 240.–", "Fr. ab"))
    assert isinstance(result, Err)
    assert isinstance(result.error, ParseError)
    assert "Fr. ab" in result.error.detail


def test_a_mietobjekt_table_with_an_undecodable_attribute_is_fatal_not_absence() -> None:
    """A `Mietobjekt`-anchored element whose escaped-JSON attribute no longer decodes is a
    table that EXISTS but cannot be read — `Err(ParseError)`, never silently `lockers: ()`
    (which would be indistinguishable from the page carrying no table at all). Both attributes
    covered: garbled `columns=` (the anchor is matched on the raw attribute text) and a valid
    `Mietobjekt` header with garbled `rows=`."""
    garbled_columns = (
        '<stzh-datatable columns="[{&#34;text&#34;:&#34;Mietobjekt&#34;}not-json"'
        ' rows="[]"></stzh-datatable>'
    )
    garbled_rows = (
        '<stzh-datatable columns="[{&#34;text&#34;:&#34;Mietobjekt&#34;},'
        '{&#34;text&#34;:&#34;Preis&#34;}]" rows="[[not-json"></stzh-datatable>'
    )
    for page in (garbled_columns, garbled_rows):
        result = parse_mietobjekte(page)
        assert isinstance(result, Err), page
        assert isinstance(result.error, ParseError)
        assert "failed to decode" in result.error.detail
    # …while a garbled table that is NOT Mietobjekt-anchored stays the absence posture: some
    # other table's malformedness is not this parser's fatality.
    other = '<stzh-datatable columns="[{&#34;text&#34;:&#34;Ticketart&#34;}oops" rows="x">'
    assert parse_mietobjekte(other) == Ok(MietobjektTable())


# --- the cost grammar over the real prose corpus ----------------------------------------


def test_bring_your_own_padlock_is_prose_not_a_price_nor_an_error() -> None:
    """ "gratis, eigenes Vorhängeschloss mitbringen" — the Garderobenkasten row at the outdoor
    pools. No `Fr.` token ⇒ fee/deposit None; the prose survives in `raw`."""
    table = _parsed("freibad_allenmoos.html")
    wardrobe = next(lo for lo in table.lockers if lo.category is LockerCategory.WARDROBE)
    assert wardrobe.fee_chf is None and wardrobe.deposit_chf is None
    assert wardrobe.raw == "Garderobenkasten | gratis, eigenes Vorhängeschloss mitbringen"


def test_auf_anfrage_is_prose_not_a_price_nor_an_error() -> None:
    # mythenquai's Mehrzweckraum: "auf Anfrage" — an unmapped label with an unstated price,
    # kept as OTHER with everything in raw. Absence of a stated price is data.
    table = _parsed("strandbad_mythenquai.html")
    on_request = next(r for r in table.rentals if r.raw.startswith("Mehrzweckraum"))
    assert on_request.kind is RentalKind.OTHER
    assert on_request.fee == Unstated() and on_request.deposit_chf is None
    assert on_request.raw == "Mehrzweckraum | auf Anfrage"


def test_stated_gratis_and_auf_anfrage_are_different_fee_facts_never_one_value() -> None:
    """The S1-review directive's proof pair, on ONE fixture's one table: mythenquai's
    Liegestuhl prints "gratis, plus Depot Fr. 2.–" — the page STATING free-ness — while its
    Mehrzweckraum prints "auf Anfrage" — the page stating nothing. `Gratis()` vs `Unstated()`:
    the admission-union Free/Unknown lesson at rental scale, no shared null."""
    table = _parsed("strandbad_mythenquai.html")
    lounger = next(r for r in table.rentals if r.kind is RentalKind.SUNLOUNGER)
    assert lounger.fee == Gratis()
    assert lounger.deposit_chf == Decimal("2.00")  # gratis usage still carries a real Pfand
    assert lounger.raw == "Liegestuhl | gratis, plus Depot Fr. 2.–"  # nbsp normalised by _text
    on_request = next(r for r in table.rentals if r.raw.startswith("Mehrzweckraum"))
    # The collision the directive forbids, pinned shut: the two rows carry DIFFERENT arms.
    assert on_request.fee == Unstated()


def test_a_non_monetary_deposit_is_a_fee_with_no_deposit_amount() -> None:
    """au-hoengg's "Fr. 2.–, plus Ausweis als Depot": the deposit is an ID card, not money —
    fee 2, deposit None, the clause preserved in `raw` (never invented as an amount)."""
    table = _parsed("flussbad_au_hoengg.html")
    padlock = next(r for r in table.rentals if r.raw.startswith("Vorhängeschloss"))
    assert padlock.fee == Priced(Decimal("2.00"))
    assert padlock.deposit_chf is None
    assert padlock.raw == "Vorhängeschloss | Fr. 2.–, plus Ausweis als Depot"


def test_rental_via_kiosk_prose_keeps_its_known_kind() -> None:
    # wollishofen's parasol row states no price at all ("Vermietung via Kiosk") — the KIND is
    # still known even when the price is prose, and prose is `Unstated`, never stated-free.
    table = _parsed("strandbad_wollishofen.html")
    parasol = next(r for r in table.rentals if r.kind is RentalKind.PARASOL)
    assert parasol.fee == Unstated() and parasol.deposit_chf is None
    assert parasol.raw == "Sonnenschirm | Vermietung via Kiosk"


def test_a_triple_clause_cell_takes_fee_and_deposit_and_keeps_the_rest_in_raw() -> None:
    # oberer-letten's Saisonkasten: "Fr. 40.–, plus Depot Fr. 20.–, eigenes Vorhängeschloss
    # mitbringen" — first non-Depot amount is the fee, the Depot clause the deposit, and the
    # extra clause rides in raw.
    table = _parsed("flussbad_oberer_letten.html")
    season = next(lo for lo in table.lockers if lo.period == "Saison")
    assert season.category is LockerCategory.WARDROBE
    assert season.fee_chf == Decimal("40.00")
    assert season.deposit_chf == Decimal("20.00")
    assert season.raw.endswith("eigenes Vorhängeschloss mitbringen")


# --- label routing beyond the City page --------------------------------------------------


def test_a_kasten_is_a_wardrobe_locker_whatever_its_rental_term() -> None:
    """blaesi's Monatskasten (Fr. 10, no deposit) routes WARDROBE with its term prefix as
    `period` — verbatim, deliberately unparsed, like every other period."""
    table = _parsed("hallenbad_blaesi.html")
    monthly = next(lo for lo in table.lockers if lo.period is not None)
    assert monthly.category is LockerCategory.WARDROBE
    assert monthly.period == "Monats"
    assert monthly.fee_chf == Decimal("10.00") and monthly.deposit_chf is None


def test_mythenquai_has_lockers_despite_no_garderobenkasten_row() -> None:
    """The table opens with `Wertsachenfach` and carries no Garderobenkasten — the case a
    Garderobenkasten-only grep misses. It must still count as locker-carrying."""
    table = _parsed("strandbad_mythenquai.html")
    assert table.lockers  # non-empty
    categories = {lo.category for lo in table.lockers}
    assert LockerCategory.VALUABLES in categories
    assert LockerCategory.WARDROBE not in categories


def test_a_bare_waeschefach_has_no_period() -> None:
    # utoquai prints `Wäschefach` with no term suffix: LAUNDRY, period honestly None.
    table = _parsed("seebad_utoquai.html")
    laundry = next(lo for lo in table.lockers if lo.category is LockerCategory.LAUNDRY)
    assert laundry.period is None
    assert laundry.fee_chf == Decimal("40.00") and laundry.deposit_chf == Decimal("20.00")


def test_cabins_carry_their_term_prefix_as_period() -> None:
    table = _parsed("freibad_letzigraben.html")
    cabins = [r for r in table.rentals if r.kind is RentalKind.CABIN]
    assert {c.period for c in cabins} == {"Saison", "Tages"}


def test_an_unmapped_label_with_a_parenthesized_suffix_keeps_it_in_raw_not_as_a_period() -> None:
    # allenmoos' "Mööslihalle (35 x 16 Meter)": the parentheses are dimensions, not a rental
    # term — OTHER, period None, and the full label survives in raw (the no-drop guarantee).
    table = _parsed("freibad_allenmoos.html")
    hall = next(r for r in table.rentals if r.raw.startswith("Mööslihalle"))
    assert hall.kind is RentalKind.OTHER
    assert hall.period is None
    assert hall.raw == "Mööslihalle (35 x 16 Meter) | Auf Anfrage"


def test_a_liegestuhl_compound_is_not_a_sunlounger_rental() -> None:
    # "Liegestuhlsaisonfach" is a compartment FOR a lounger, not renting one: OTHER, so the
    # SUNLOUNGER kind stays a statement about actual lounger rentals.
    table = _parsed("strandbad_mythenquai.html")
    compounds = [r for r in table.rentals if r.raw.startswith("Liegestuhlsaisonfach")]
    assert compounds and all(r.kind is RentalKind.OTHER for r in compounds)


# --- the whole declared corpus -----------------------------------------------------------


def test_every_declared_fixture_parses_and_the_locker_carrying_set_is_the_noun_scan() -> None:
    """The fail-fast exposure surface: all 26 declared pages parse `Ok` (a single `Err` here
    would abort a real build), and the pages yielding lockers are EXACTLY the 20 the shared
    `LOCKER_NOUN` scan finds — derived from the fixtures, independent of the parser's own
    routing, so this cannot collapse into comparing the parser with itself."""
    carrying: set[str] = set()
    expected: set[str] = set()
    renting: set[str] = set()
    tabled: set[str] = set()
    for pool_id, fixture in PAGE_FIXTURES.items():
        page = _page(fixture)
        if LOCKER_NOUN.search(page):
            expected.add(pool_id)
        if MIETOBJEKT_NOUN.search(page):
            tabled.add(pool_id)
        result = parse_mietobjekte(page)
        assert isinstance(result, Ok), (pool_id, result)
        if result.value.lockers:
            carrying.add(pool_id)
        if result.value.rentals:
            renting.add(pool_id)
        # No-drop across the corpus: every parsed row landed in one of the two tuples —
        # nothing raised, nothing silently skipped — and absence stays absence.
        if not result.value.lockers and not result.value.rentals:
            assert pool_id in {
                "hallenbad-altstetten",
                "maennerbad-schanzengraben",
                "schulschwimmanlage-aemtler",
                "schulschwimmanlage-altweg",
                "schulschwimmanlage-riedtli",
                "schulschwimmanlage-tannenrauch",
            }, pool_id
    assert carrying == expected
    assert len(carrying) == 20
    assert "strandbad-mythenquai" in carrying  # the Wertsachenfach-only table
    # …and the rental-carrying set is EXACTLY the table-carrying set (the Decisions-corrected
    # count: with OTHER routing honest, every declared table has ≥1 non-locker row), derived
    # by the shared `Mietobjekt`-header scan, independent of the parser's own routing.
    assert renting == tabled
    assert len(renting) == 20
    # heuried's only non-locker row is a `Liegestuhlsaisonfach` — an UNMAPPED label. It carries
    # rentals only because OTHER routing keeps it; a kind-noun-only counter would call it 0.
    assert "freibad-heuried" in renting


def test_the_rental_kind_carrying_sets_are_the_fixture_derived_noun_scans() -> None:
    """Kind-level acceptance pins (S2), each expected set derived by the shared
    parser-independent noun scan over the declared fixtures: TOWEL/SWIMWEAR/GOGGLES on the 11
    wear-noun fixtures, CABIN on 11 (the plan's ≥10), SUNLOUNGER on the 9 exact-`Liegestuhl`
    fixtures, PARASOL on 8 — where `(?!\\w)` keeps `Liegestuhlsaisonfach` (a compartment, not
    a lounger rental) out of both sides of the comparison."""
    wear_kinds = {RentalKind.TOWEL, RentalKind.SWIMWEAR, RentalKind.GOGGLES}
    scans = (
        (RENTAL_WEAR_NOUN, wear_kinds, 11),
        (CABIN_NOUN, {RentalKind.CABIN}, 11),
        (SUNLOUNGER_NOUN, {RentalKind.SUNLOUNGER}, 9),
        (PARASOL_NOUN, {RentalKind.PARASOL}, 8),
    )
    for noun, kinds, count in scans:
        expected = {pool_id for pool_id, f in PAGE_FIXTURES.items() if noun.search(_page(f))}
        carrying = {
            pool_id
            for pool_id, fixture in PAGE_FIXTURES.items()
            if kinds & {r.kind for r in _parsed(fixture).rentals}
        }
        assert carrying == expected, kinds
        assert len(carrying) == count, kinds


def test_every_rental_fee_arm_agrees_with_its_own_source_cell() -> None:
    """The fee-union honesty sweep over the whole declared corpus: every `Priced` rental's
    cell carries a `Fr.` token, every `Gratis` one's OPENS with the word gratis (a stated
    fact), and every `Unstated` one's has neither — so no arm can ever swallow another's
    cells. Measured scale: 13 stated-gratis (Liegestuhl ×8, Sonnenschirm ×4, Spielmaterial)
    vs 8 unstated — the two populations the pre-S2 `None` compressed into one value."""
    gratis, unstated = 0, 0
    for fixture in set(PAGE_FIXTURES.values()):
        for rental in _parsed(fixture).rentals:
            cell = rental.raw.split(" | ", 1)[1]
            if isinstance(rental.fee, Priced):
                assert "Fr." in cell, rental
            elif isinstance(rental.fee, Gratis):
                gratis += 1
                assert cell.lower().startswith("gratis"), rental
            else:
                unstated += 1
                assert "Fr." not in cell, rental
                assert not cell.lower().startswith("gratis"), rental
    assert (gratis, unstated) == (13, 8)


def test_no_locker_in_the_corpus_carries_an_unstated_fee() -> None:
    """What keeps the LOCKER side's S1 two-state `fee_chf` honest (`None` == free to use):
    every fee-less locker cell in the committed corpus PRINTS gratis — the unstated cells
    all sit on rental-labeled rows, where the union now carries the distinction. If a page
    ever prints an `auf Anfrage` locker row, this sweep fails and the locker representation
    must be revisited rather than silently reading it as free."""
    for fixture in set(PAGE_FIXTURES.values()):
        for locker in _parsed(fixture).lockers:
            cell = locker.raw.split(" | ", 1)[1]
            if locker.fee_chf is None:
                assert cell.lower().startswith("gratis"), locker
