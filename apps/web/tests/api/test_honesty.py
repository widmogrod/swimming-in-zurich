"""S5 honesty invariants at the SERVED-asset layer (the Python half of the sweep;
the model/render logic is gated node-side in static/js/blocks/honesty.test.ts).

These assert that the invariants survive all the way to what the browser actually
loads: the served BoardLegend module, the served DetailPanel module, and the `/`
shell. They are gates (plan Risk #4), not nice-to-haves — a refactor that quietly
merged unknown into closed, faked busyness, or merged ? with ✕ would break here.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.web.main import app


def _get(path: str) -> str:
    with TestClient(app) as client:
        res = client.get(path)
    assert res.status_code == 200, f"{path} → {res.status_code}"
    return str(res.text)


def test_served_legend_keeps_the_three_terminal_states_distinct() -> None:
    """The served BoardLegend keys the three never-merged terminal states as three
    distinct rows — open / closed-with-reason / hours-not-listed — never collapsed."""
    legend = _get("/static/js/blocks/legend.js")
    assert "Open (public lanes)" in legend
    assert "Closed — with reason" in legend
    assert "Hours not listed yet" in legend
    # The three state keys are enumerated distinctly (open/closed/unknown).
    for key in ("'open'", "'closed'", "'unknown'"):
        assert key in legend, f"legend must key the {key} state"


def test_served_legend_keeps_check_distinct_from_not_for_you() -> None:
    """Eligibility ? (chk) is never merged with ✕ (no): the served legend key carries
    BOTH 'Check with the venue' and 'Not for you' as separate rows."""
    legend = _get("/static/js/blocks/legend.js")
    assert "Check with the venue" in legend  # ? (chk)
    assert "Not for you" in legend  # ✕ (no)


def test_served_legend_honesty_note_disclaims_busyness() -> None:
    """The honesty note states thickness is the real public-lane split, NOT busyness,
    and that busyness has no source yet — so the legend can't imply a data source that
    does not exist."""
    legend = _get("/static/js/blocks/legend.js")
    assert "not busyness" in legend
    assert "no source yet" in legend


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
    model = _get("/static/js/blocks/ribbonmodel.js")
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
