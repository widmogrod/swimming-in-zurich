"""The size ratchet's own tests — the arithmetic, and that a regression FAILS.

A budget file nothing enforces is a wish. These prove the things that make the
ratchet real: the two numbers are separated, an over-limit measurement is reported
as a failure, and a data refresh alone cannot push the code number over.

**Two tiers, deliberately.** The arithmetic — `check`, `is_test_artifact`, and the
committed budget and privacy files — runs EVERYWHERE the Python chain runs, which
includes the `ubuntu-latest` `qa` job. The tests that build a synthetic `.app` need
a real Mach-O to copy and `size -m` to read it, and both are macOS-only: on Linux
`/bin/echo` is an ELF binary that `is_macho` correctly classifies as a resource
rather than as code, so those tests would fail on a fact about the host and not
about the ratchet (and GNU `size` has no `-m` besides). They skip there, through the
`fake_app` fixture, exactly as the CRAP gate's end-to-end test skips without a
`swift test` build directory.
"""

from __future__ import annotations

import importlib.util
import json
import plistlib
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUDGETS = REPO_ROOT / "apps" / "ios" / "budgets.json"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ios_budget = _load("ios_budget", REPO_ROOT / "scripts" / "ios_budget.py")


def host_measures_macho() -> bool:
    """Can this host both PRODUCE a Mach-O to measure and read it with `size -m`?

    Only macOS can. The gate itself only ever runs there — it is a build phase on an
    Xcode target — so this is a property of the test's materials, not a gap in the
    ratchet: the arithmetic tests below carry it on every platform.
    """
    return sys.platform == "darwin" and shutil.which("size") is not None


@pytest.fixture
def fake_app(tmp_path: Path) -> Path:
    """A bundle shaped like a built `.app`: one Mach-O, one store, one resource."""
    if not host_measures_macho():
        pytest.skip("needs a Mach-O host binary and `size -m` (macOS only)")
    app = tmp_path / "SwimZH.app"
    (app / "Kit.bundle").mkdir(parents=True)
    shutil.copy("/bin/echo", app / "SwimZH")
    (app / "Kit.bundle" / ios_budget.STORE_NAME).write_bytes(b"\x00" * 5000)
    (app / "Info.plist").write_bytes(b"<plist/>" + b" " * 92)
    return app


def test_the_store_is_measured_apart_from_the_code(fake_app: Path) -> None:
    measurement = ios_budget.measure(fake_app)
    assert measurement.sqlite == 5000
    assert measurement.resource_bytes == 100
    # The real binary's __TEXT is whatever /bin/echo carries; what matters is that it
    # is a positive number derived from `size -m` and that the store is NOT in it.
    assert measurement.text_bytes > 0
    assert measurement.app_minus_sqlite == measurement.text_bytes + 100


def test_a_data_refresh_cannot_mask_a_code_regression(fake_app: Path) -> None:
    """The whole reason there are two numbers rather than one."""
    before = ios_budget.measure(fake_app)
    (fake_app / "Kit.bundle" / ios_budget.STORE_NAME).write_bytes(b"\x00" * 5_000_000)
    after = ios_budget.measure(fake_app)
    assert after.sqlite > before.sqlite
    assert after.app_minus_sqlite == before.app_minus_sqlite


def test_test_injection_artifacts_are_not_counted(fake_app: Path) -> None:
    """The gate runs inside `xcodebuild … test`, which copies ~8.8 MB of XCTest INTO the app.

    Measured: counting them put the proxy at 9,035,863 B — 2.15x the whole ratchet — in the
    one command that runs the gate. They are not downloaded by anyone.
    """
    before = ios_budget.measure(fake_app)
    plugins = fake_app / "PlugIns" / "SwimZHTests.xctest"
    plugins.mkdir(parents=True)
    shutil.copy("/bin/echo", plugins / "SwimZHTests")
    frameworks = fake_app / "Frameworks"
    frameworks.mkdir()
    shutil.copy("/bin/echo", frameworks / "libXCTestSwiftSupport.dylib")
    (frameworks / "XCTest.framework").mkdir()
    shutil.copy("/bin/echo", frameworks / "XCTest.framework" / "XCTest")
    assert ios_budget.measure(fake_app) == before


def test_a_real_embedded_framework_is_still_measured(fake_app: Path) -> None:
    """The exclusion is a named test-support family, not "everything in Frameworks"."""
    before = ios_budget.measure(fake_app)
    shipped = fake_app / "Frameworks" / "SwimZHShared.framework"
    shipped.mkdir(parents=True)
    shutil.copy("/bin/echo", shipped / "SwimZHShared")
    assert ios_budget.measure(fake_app).text_bytes > before.text_bytes


def test_the_exclusion_rule_names_test_injection_and_nothing_else() -> None:
    """The same rule as the fixture test above, as pure path logic — so it runs on Linux.

    The `.app` tests are macOS-only; this one is what protects the exclusion everywhere
    the Python chain runs, which is where the ratchet's arithmetic is reviewed.
    """
    excluded = [
        "PlugIns/SwimZHTests.xctest/SwimZHTests",
        "PlugIns/SwimZHTests.xctest/Info.plist",
        "Frameworks/XCTest.framework/XCTest",
        "Frameworks/XCUIAutomation.framework/XCUIAutomation",
        "Frameworks/libXCTestSwiftSupport.dylib",
        "Frameworks/Testing.framework/Testing",
    ]
    for path in excluded:
        assert ios_budget.is_test_artifact(Path(path)), path

    kept = [
        "SwimZH",
        "SwimZH.debug.dylib",
        "Info.plist",
        "PrivacyInfo.xcprivacy",
        "SwimZHKit_SwimZHKit.bundle/ios.sqlite",
        # A real embedded framework is NOT test support, and must stay measured.
        "Frameworks/SwimZHShared.framework/SwimZHShared",
    ]
    for path in kept:
        assert not ios_budget.is_test_artifact(Path(path)), path


def test_only_mach_o_files_are_counted_as_code(tmp_path: Path) -> None:
    """The classification that decides whether a file lands in `__TEXT` or in resources.

    Pinned as its own test because it is exactly what differs by host: an ELF binary is
    correctly NOT a Mach-O, which is why the bundle tests above cannot run on Linux.
    """
    macho = tmp_path / "macho"
    macho.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 64)
    assert ios_budget.is_macho(macho)

    elf = tmp_path / "elf"
    elf.write_bytes(b"\x7fELF" + b"\x00" * 64)
    assert not ios_budget.is_macho(elf)

    (tmp_path / "plist").write_bytes(b"<plist/>")
    assert not ios_budget.is_macho(tmp_path / "plist")


def test_an_over_limit_measurement_is_a_failure_not_a_note() -> None:
    measurement = ios_budget.Measurement(
        app_minus_sqlite=5_000_000, sqlite=1_000, text_bytes=5_000_000, resource_bytes=0
    )
    budgets = {"app_minus_sqlite": {"limit_bytes": 4_194_304}, "sqlite": {"limit_bytes": 8_388_608}}
    [failure] = ios_budget.check(measurement, budgets)
    assert "app_minus_sqlite" in failure and "exceeds" in failure


def test_each_budget_is_checked_independently() -> None:
    measurement = ios_budget.Measurement(
        app_minus_sqlite=1, sqlite=9_000_000, text_bytes=1, resource_bytes=0
    )
    budgets = {"app_minus_sqlite": {"limit_bytes": 4_194_304}, "sqlite": {"limit_bytes": 8_388_608}}
    [failure] = ios_budget.check(measurement, budgets)
    assert failure.startswith("sqlite:")


def test_a_measurement_inside_both_limits_is_green() -> None:
    measurement = ios_budget.Measurement(
        app_minus_sqlite=300_000, sqlite=2_000_000, text_bytes=300_000, resource_bytes=0
    )
    assert ios_budget.check(measurement, json.loads(BUDGETS.read_text())) == []


def test_the_committed_budget_file_states_a_limit_for_every_gated_number() -> None:
    budgets = json.loads(BUDGETS.read_text())
    for name in ("app_minus_sqlite", "sqlite", "peak_memory"):
        assert isinstance(budgets[name]["limit_bytes"], int), name
        assert budgets[name]["why"].strip(), f"{name} carries no reason"
    # The numbers themselves, so a silent loosening shows up as a diff in this test too.
    # The live ratchet was TIGHTER than the plan's 4 MB for S2b and S3b, deliberately: a limit
    # with that much slack would not bite until the app was finished, which is the
    # audit-at-the-end failure this gate exists to prevent. S5 spent the last of that margin,
    # so the two are now EQUAL and the plan's figure is the live limit. There is no headroom
    # left inside the plan: the next raise has to move `plan_ratchet_bytes`, which is a decision
    # about the plan rather than about a build.
    #
    # RAISED TWICE, and this literal is where each raise becomes visible.
    #  * S3b, 1 MB -> 2 MB: the canvas renderer, Swift Charts, the detail sheet, the pools
    #    browser and the access-types legend landed together, measuring 1,339,498 B.
    #  * S5, 2 MB -> the plan's 4 MB: S4's five compiled catalogs took the measurement to
    #    1,908,758 B (91% of the 2 MB limit), and S5's live client, refresh path and the sheet
    #    row that renders them took it to 2,072,598 B — 98.8%, i.e. 24 KB of headroom, which is
    #    a gate that would fail on the next comment. 4 MB is the figure the PLAN ratcheted to
    #    and it is not a widening beyond it: `plan_ratchet_bytes` is unchanged, the two are now
    #    equal, and the 30 MB ceiling the user set is still 7x away. Any future raise has to
    #    move the plan's own number, which is a different and larger conversation.
    assert budgets["app_minus_sqlite"]["limit_bytes"] == 4 * 1024 * 1024
    assert budgets["app_minus_sqlite"]["plan_ratchet_bytes"] == 4 * 1024 * 1024
    assert (
        budgets["app_minus_sqlite"]["limit_bytes"]
        <= budgets["app_minus_sqlite"]["plan_ratchet_bytes"]
    )
    assert budgets["app_minus_sqlite"]["ceiling_bytes"] == 30 * 1024 * 1024
    assert budgets["sqlite"]["limit_bytes"] == 8 * 1024 * 1024
    assert budgets["peak_memory"]["limit_bytes"] == 100 * 1024 * 1024
    # Launch time is deliberately a target, not a gated limit — see the budgets table.
    assert "limit_bytes" not in budgets["launch_seconds"]
    assert budgets["launch_seconds"]["target"] == 1.0


def test_the_recorded_measurements_are_inside_the_limits_they_are_recorded_against() -> None:
    """A recorded number above its own ratchet would mean the gate had been bypassed."""
    budgets = json.loads(BUDGETS.read_text())
    for name in ("app_minus_sqlite", "sqlite"):
        assert budgets[name]["measured_bytes"] <= budgets[name]["limit_bytes"], name


def test_the_memory_ceiling_in_the_metric_test_matches_the_budget_file() -> None:
    """The Swift test cannot read this repo from a simulator, so it restates the number.

    Two copies of a budget drift the moment nobody joins them; this is the join.
    """
    budgets = json.loads(BUDGETS.read_text())
    metric = (REPO_ROOT / "apps/ios/App/SwimZHTests/MemoryMetricTests.swift").read_text()
    megabytes = budgets["peak_memory"]["limit_bytes"] // (1024 * 1024)
    assert f"= {megabytes} * 1024 * 1024" in metric, (
        f"MemoryMetricTests does not state the {megabytes} MB ceiling budgets.json does"
    )
    # And it is measured on the footprint the OS terminates on, not only on the delta
    # XCTMemoryMetric reports.
    assert "phys_footprint" in metric
    assert "XCTMemoryMetric" in metric


def test_the_privacy_manifest_declares_the_userdefaults_reason() -> None:
    """Omitting it is an ITMS-91055 rejection that only shows up at upload time.

    Asserted from Python too, not only from the app-hosted test, because the app-hosted
    test needs a simulator and this one runs everywhere the Python chain does.
    """
    manifest = (REPO_ROOT / "apps/ios/App/SwimZH/PrivacyInfo.xcprivacy").read_bytes()
    plist = plistlib.loads(manifest)
    assert plist["NSPrivacyTracking"] is False
    assert plist["NSPrivacyTrackingDomains"] == []
    assert plist["NSPrivacyCollectedDataTypes"] == []
    [accessed] = plist["NSPrivacyAccessedAPITypes"]
    assert accessed["NSPrivacyAccessedAPIType"] == "NSPrivacyAccessedAPICategoryUserDefaults"
    assert accessed["NSPrivacyAccessedAPITypeReasons"] == ["CA92.1"]


def test_missing_bundle_is_reported_rather_than_silently_passing(tmp_path: Path) -> None:
    assert ios_budget.main([str(tmp_path / "nope.app")]) == 2


def test_the_gate_exits_nonzero_on_a_regression(fake_app: Path, tmp_path: Path) -> None:
    budgets = tmp_path / "budgets.json"
    budgets.write_text(
        json.dumps({"app_minus_sqlite": {"limit_bytes": 1}, "sqlite": {"limit_bytes": 8_388_608}})
    )
    assert ios_budget.main([str(fake_app), "--budgets", str(budgets)]) == 1


def test_the_gate_exits_zero_against_the_committed_budgets(fake_app: Path) -> None:
    assert ios_budget.main([str(fake_app), "--budgets", str(BUDGETS)]) == 0
