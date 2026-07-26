"""Single source of truth for environment configuration.

All `os.getenv()` calls live here only, read and validated fail-fast at startup. A local
`.env` (copied from `.env.example`) is loaded as a convenience so a developer can run the
server without exporting anything — real environment variables always win (`.env` never
overrides an already-set var), and an absent `.env` is a silent no-op.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    gold_db: Path  # the single runtime source of truth; built by `swimzh build`
    host: str
    port: int
    reload: bool  # auto-reload on code change (dev server via `python -m apps.web.main`)
    dev_ui: bool  # register the dev-only /ui/gallery component gallery (absent in production)
    # Live water-temperature feed (Baditicker). None = unset = no provider wired (fail-open:
    # `/pools/{id}` reports "live temperature not configured"). Set the URL to enable the real
    # adapter; `apps.web.main` wires a `BaditickerProvider` against it.
    baditicker_url: str | None

    @staticmethod
    def from_env() -> Config:
        # Load `.env` (if present) BEFORE reading os.getenv. `override=False` (the default)
        # means a real, already-exported env var beats the `.env` value — `.env` is a
        # default layer for local dev, not an override. No `.env` -> no-op (prod sets real env).
        load_dotenv()
        return Config(
            gold_db=Path(os.getenv("SWIMZH_GOLD_DB", "gold.sqlite")),
            host=os.getenv("SWIMZH_HOST", "127.0.0.1"),
            port=int(os.getenv("SWIMZH_PORT", "8000")),
            reload=os.getenv("SWIMZH_RELOAD", "1") not in {"0", "false", "False", ""},
            dev_ui=os.getenv("SWIMZH_DEV_UI", "0") in {"1", "true", "True", "yes"},
            baditicker_url=os.getenv("SWIMZH_BADITICKER_URL") or None,
        )
