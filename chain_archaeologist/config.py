from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .util import ensure_dir


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DATA = ensure_dir(PROJECT_ROOT / "app_data")
CONFIG_FILE = APP_DATA / "config.json"


@dataclass
class AppConfig:
    language: str = "en"
    theme: str = "dark"
    window_width: int = 1280
    window_height: int = 820
    restore_window_geometry: bool = True
    workspace_root: str = str(APP_DATA / "workspaces")
    profile_id: str = "bitcoin"
    node_executable: str = ""
    node_datadir: str = ""
    rpc_host: str = "127.0.0.1"
    rpc_port: int = 8332
    rpc_user: str = ""
    rpc_password: str = ""
    cookie_file: str = ""
    rpc_timeout_seconds: int = 30
    scan_batch_size: int = 8
    scan_start_height: int = 0
    scan_end_height: int = -1
    minimum_payload_size: int = 4
    maximum_payload_size: int = 16 * 1024 * 1024
    catalog_unknown_op_return: bool = True
    catalog_all_data_pushes: bool = False
    minimum_generic_confidence: float = 0.80
    preview_max_bytes: int = 65536
    safe_text_mimes: list[str] = field(default_factory=lambda: [
        "text/plain", "application/json", "application/xml", "text/xml",
        "text/csv", "text/html", "text/x-python", "text/x-c", "text/x-shellscript",
    ])
    export_sidecar_json: bool = True
    confirm_bulk_export: bool = True
    node_extra_args: str = ""
    disable_wallet: bool = True
    listen_for_inbound_peers: bool = False

    @classmethod
    def load(cls) -> "AppConfig":
        if not CONFIG_FILE.exists():
            cfg = cls()
            cfg.save()
            return cfg
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**known)
        except Exception:
            return cls()

    def save(self) -> None:
        ensure_dir(Path(self.workspace_root))
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    def workspace_dir(self, chain_id: str | None = None) -> Path:
        chain = chain_id or self.profile_id
        return ensure_dir(Path(self.workspace_root) / chain)

    def catalog_path(self, chain_id: str | None = None) -> Path:
        return self.workspace_dir(chain_id) / "catalog.sqlite3"
