"""S5 honesty invariants at the SERVED-asset layer (the Python half of the sweep;
the model/render logic is gated node-side in static/js/blocks/honesty.test.ts).

These assert that the invariants survive all the way to what the browser actually
loads: the served BoardLegend module, the served DetailPanel module, and the `/`
shell. They are gates (plan Risk #4), not nice-to-haves — a refactor that quietly
merged unknown into closed, faked busyness, or merged ? with ✕ would break here.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from apps.web.main import app


def _message(catalog: str, key: str) -> str:
    """The `en` string for `key`, read out of the served catalogue source."""
    match = re.search(rf'"{re.escape(key)}":\s*\n?\s*"((?:[^"\\]|\\.)*)"', catalog)
    return match.group(1) if match else ""


def _get(path: str) -> str:
    with TestClient(app) as client:
        res = client.get(path)
    assert res.status_code == 200, f"{path} → {res.status_code}"
    return str(res.text)


def _catalog() -> str:
    """The served `en` message catalogue.

    These invariants moved here in S3: the copy now lives in `locales/en.ts`, not inline
    in the block. Asserting DISTINCTNESS (three states are three different strings) rather
    than exact wording means the guard survives translation — a `pl` catalogue must keep
    the states distinct too, and a future test can run this over every locale.
    """
    return _get("/static/js/locales/en.ts")


def test_served_legend_keeps_the_three_terminal_states_distinct() -> None:
    """The three never-merged terminal states — open / closed-with-reason /
    hours-not-listed — stay three distinct rows, never collapsed."""
    legend = _get("/static/js/blocks/legend.ts")
    # The block still enumerates the three state keys distinctly...
    for key in ("'open'", "'closed'", "'unknown'"):
        assert key in legend, f"legend must key the {key} state"
    # ...and the catalogue gives each its OWN wording (the honesty invariant: an
    # unknown timetable must never read as a closure).
    catalog = _catalog()
    labels = [
        _message(catalog, key)
        for key in ("legend.state.open", "legend.state.closed", "legend.state.unknown")
    ]
    assert all(labels), "every terminal state needs a label"
    assert len(set(labels)) == 3, f"terminal states must not share wording: {labels}"


def test_served_legend_keeps_check_distinct_from_not_for_you() -> None:
    """Eligibility ? (chk) is never merged with ✕ (no) — they are different answers."""
    catalog = _catalog()
    chk = _message(catalog, "elig.chk")
    no = _message(catalog, "elig.no")
    assert chk and no
    assert chk != no, "'check with the venue' must not read the same as 'not for you'"


def test_served_legend_honesty_note_disclaims_busyness() -> None:
    """The honesty note states thickness is the real public-lane split, NOT busyness,
    and that busyness has no source yet — so the legend can't imply a data source that
    does not exist."""
    note = _message(_catalog(), "legend.honestyNote")
    assert "not busyness" in note
    assert "no source yet" in note


def test_served_detail_panel_renders_busyness_as_future_never_faked() -> None:
    """The served DetailPanel renders Busyness as the honest future state 'Not available
    yet' — never a fabricated figure."""
    panel = _get("/static/js/blocks/detailpanel.ts")
    assert "'Not available yet'" in panel
    assert "Busyness" in panel


def test_served_ribbonmodel_keeps_unknown_distinct_from_closed() -> None:
    """The served ribbon model renders a closed status as a DASHED ribbon and an
    uncurated status as a DOTTED ghost with the 'unknown' family — never merged into
    'closed'."""
    model = _get("/static/js/blocks/ribbonmodel.ts")
    assert "'dashed'" in model  # closed
    assert "'dotted'" in model  # uncurated ghost
    assert "family: 'closed'" in model
    assert "family: 'unknown'" in model


def test_shell_serves_the_legend_mount_and_charset() -> None:
    """The `/` shell declares the charset (the mojibake footgun) and carries the legend
    mount point the served BoardLegend hydrates into."""
    shell = _get("/")
    assert '<meta charset="utf-8">' in shell
    assert 'id="app-legend"' in shell
    assert '<link rel="stylesheet" href="/static/tokens.css">' in shell
