"""Single source of truth for environment configuration.

All `os.getenv()` calls live here only, read and validated fail-fast at startup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: Path
    host: str
    port: int

    @staticmethod
    def from_env() -> Config:
        return Config(
            data_dir=Path(os.getenv("SWIMZH_DATA_DIR", "data")),
            host=os.getenv("SWIMZH_HOST", "127.0.0.1"),
            port=int(os.getenv("SWIMZH_PORT", "8000")),
        )
