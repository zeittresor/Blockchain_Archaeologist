from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .catalog import Catalog


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(value: str) -> str:
    return _SAFE.sub("_", value).strip("._") or "candidate"


def export_candidate(row, destination: str | Path, include_sidecar: bool = True) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = bytes(row["payload"])
    destination.write_bytes(payload)
    if include_sidecar:
        metadata = {key: row[key] for key in row.keys() if key != "payload"}
        sidecar = destination.with_suffix(destination.suffix + ".json")
        sidecar.write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return destination


class BulkExportWorker(QThread):
    progress = Signal(dict)
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(self, catalog_path: str, chain_id: str, extension: str, target_dir: str, include_sidecars: bool) -> None:
        super().__init__()
        self.catalog_path = catalog_path
        self.chain_id = chain_id
        self.extension = extension
        self.target_dir = target_dir
        self.include_sidecars = include_sidecars
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        catalog: Catalog | None = None
        started = time.monotonic()
        try:
            catalog = Catalog(self.catalog_path)
            rows = catalog.export_rows(self.chain_id, self.extension)
            total = len(rows)
            target = Path(self.target_dir)
            target.mkdir(parents=True, exist_ok=True)
            written = 0
            for index, row in enumerate(rows, 1):
                if self._cancel.is_set():
                    break
                name = safe_filename(
                    f"{row['block_height']}_{str(row['txid'])[:16]}_{row['id']}{row['extension']}"
                )
                export_candidate(row, target / name, self.include_sidecars)
                written += 1
                elapsed = time.monotonic() - started
                rate = written / elapsed if elapsed > 0 else None
                eta = ((total - written) / rate) if rate and rate > 0 else None
                self.progress.emit({"current": written, "total": total, "eta": eta, "elapsed": elapsed, "file": name})
            self.completed.emit({"written": written, "total": total, "cancelled": self._cancel.is_set(), "elapsed": time.monotonic() - started})
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if catalog:
                catalog.close()
