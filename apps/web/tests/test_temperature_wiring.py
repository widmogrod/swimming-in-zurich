"""Composition-root wiring for the live water-temperature provider: the real Baditicker adapter
is built only when a feed URL is configured; otherwise the app stays fail-open with `None`."""

from __future__ import annotations

from pathlib import Path

from apps.web.config import Config
from apps.web.main import build_http_transport, build_temperature_provider
from swimzh.core.httpcache import CacheMode
from swimzh.providers.baditicker import BaditickerProvider


def _config(baditicker_url: str | None) -> Config:
    return Config(
        gold_db=Path("gold.sqlite"),
        host="127.0.0.1",
        port=8000,
        reload=False,
        dev_ui=False,
        baditicker_url=baditicker_url,
    )


def test_no_provider_when_unset() -> None:
    assert build_temperature_provider(_config(None)) is None


def test_real_provider_when_configured() -> None:
    provider = build_temperature_provider(_config("https://feed.test/bathdatadownload"))
    assert isinstance(provider, BaditickerProvider)


def test_the_web_runtime_wires_the_provider_disk_cache_off() -> None:
    # The disk cache is a BUILD accelerator, not a runtime tier: at request time the app must not
    # serve bytes an operator can only invalidate with `rm -rf`. `OFF` is a straight passthrough,
    # so this pins the one thing that could silently change — the mode the transport is built with.
    assert build_http_transport().mode is CacheMode.OFF
