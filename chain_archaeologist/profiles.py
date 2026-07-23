from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .config import PROJECT_ROOT


@dataclass(frozen=True)
class ChainProfile:
    id: str
    name: str
    symbol: str
    family: str
    pow_algorithm: str
    rpc_port: int
    p2p_port: int
    official_url: str
    executable_names: list[str]
    windows_datadir: str
    support_level: str
    notes: str
    supports_witness: bool = True
    extra_start_args: list[str] | None = None

    def expanded_windows_datadir(self) -> str:
        return os.path.expandvars(self.windows_datadir)


def load_profiles() -> list[ChainProfile]:
    path = PROJECT_ROOT / "assets" / "chain_profiles.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ChainProfile(**item) for item in data]


def profile_map() -> dict[str, ChainProfile]:
    return {p.id: p for p in load_profiles()}
