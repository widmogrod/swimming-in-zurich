"""Single source of truth for environment configuration.

All `os.getenv()` calls live here only, read and validated fail-fast at startup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    gold_db: Path  # the single runtime source of truth; built by `swimzh build`
    host: str
    port: int
    reload: bool  # auto-reload on code change (dev server via `python -m apps.web.main`)
    dev_ui: bool  # register the dev-only /ui/gallery component gallery (absent in production)

    @staticmethod
    def from_env() -> Config:
        return Config(
            gold_db=Path(os.getenv("SWIMZH_GOLD_DB", "gold.sqlite")),
            host=os.getenv("SWIMZH_HOST", "127.0.0.1"),
            port=int(os.getenv("SWIMZH_PORT", "8000")),
            reload=os.getenv("SWIMZH_RELOAD", "1") not in {"0", "false", "False", ""},
            dev_ui=os.getenv("SWIMZH_DEV_UI", "0") in {"1", "true", "True", "yes"},
        )
