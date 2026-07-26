"""Composition-root wiring for the live water-temperature provider: the real Baditicker adapter
is built only when a feed URL is configured; otherwise the app stays fail-open with `None`."""

from __future__ import annotations

from pathlib import Path

from apps.web.config import Config
from apps.web.main import build_temperature_provider
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
