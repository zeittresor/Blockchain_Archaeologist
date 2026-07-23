from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_id TEXT NOT NULL,
    block_height INTEGER NOT NULL,
    block_hash TEXT NOT NULL,
    block_time INTEGER NOT NULL,
    txid TEXT NOT NULL,
    tx_index INTEGER NOT NULL,
    location TEXT NOT NULL,
    embedding_method TEXT NOT NULL,
    item_index INTEGER NOT NULL,
    payload_size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    entropy REAL NOT NULL,
    detected_type TEXT NOT NULL,
    extension TEXT NOT NULL,
    mime TEXT NOT NULL,
    confidence REAL NOT NULL,
    magic_offset INTEGER NOT NULL,
    preview_text TEXT,
    payload BLOB NOT NULL,
    metadata_json TEXT NOT NULL,
    UNIQUE(chain_id, block_hash, txid, location, item_index, sha256)
);
CREATE INDEX IF NOT EXISTS idx_candidates_height ON candidates(chain_id, block_height);
CREATE INDEX IF NOT EXISTS idx_candidates_type ON candidates(chain_id, detected_type, extension, confidence);
CREATE INDEX IF NOT EXISTS idx_candidates_txid ON candidates(txid);
CREATE TABLE IF NOT EXISTS scan_state (
    chain_id TEXT PRIMARY KEY,
    last_scanned_height INTEGER NOT NULL,
    tip_at_scan INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
"""


@dataclass
class CandidateRecord:
    chain_id: str
    block_height: int
    block_hash: str
    block_time: int
    txid: str
    tx_index: int
    location: str
    embedding_method: str
    item_index: int
    payload_size: int
    sha256: str
    entropy: float
    detected_type: str
    extension: str
    mime: str
    confidence: float
    magic_offset: int
    preview_text: str | None
    payload: bytes
    metadata: dict[str, Any]


class Catalog:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=60)
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def add_many(self, records: Iterable[CandidateRecord]) -> int:
        rows = []
        for r in records:
            rows.append((
                r.chain_id, r.block_height, r.block_hash, r.block_time, r.txid, r.tx_index,
                r.location, r.embedding_method, r.item_index, r.payload_size, r.sha256, r.entropy,
                r.detected_type, r.extension, r.mime, r.confidence, r.magic_offset, r.preview_text,
                sqlite3.Binary(r.payload), json.dumps(r.metadata, ensure_ascii=False, sort_keys=True),
            ))
        if not rows:
            return 0
        before = self.connection.total_changes
        self.connection.executemany("""
            INSERT OR IGNORE INTO candidates (
                chain_id, block_height, block_hash, block_time, txid, tx_index,
                location, embedding_method, item_index, payload_size, sha256, entropy,
                detected_type, extension, mime, confidence, magic_offset, preview_text,
                payload, metadata_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        self.connection.commit()
        return self.connection.total_changes - before

    def update_scan_state(self, chain_id: str, last_height: int, tip: int, updated_at: int) -> None:
        self.connection.execute("""
            INSERT INTO scan_state(chain_id,last_scanned_height,tip_at_scan,updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(chain_id) DO UPDATE SET
              last_scanned_height=excluded.last_scanned_height,
              tip_at_scan=excluded.tip_at_scan,
              updated_at=excluded.updated_at
        """, (chain_id, last_height, tip, updated_at))
        self.connection.commit()

    def last_scanned_height(self, chain_id: str) -> int | None:
        row = self.connection.execute("SELECT last_scanned_height FROM scan_state WHERE chain_id=?", (chain_id,)).fetchone()
        return int(row[0]) if row else None

    def count(self, chain_id: str) -> int:
        row = self.connection.execute("SELECT COUNT(*) FROM candidates WHERE chain_id=?", (chain_id,)).fetchone()
        return int(row[0])

    def query(self, chain_id: str, search: str = "", extension: str = "", limit: int = 5000) -> list[sqlite3.Row]:
        self.connection.row_factory = sqlite3.Row
        where = ["chain_id=?"]
        params: list[Any] = [chain_id]
        if search:
            where.append("(txid LIKE ? OR detected_type LIKE ? OR embedding_method LIKE ? OR mime LIKE ?)")
            token = f"%{search}%"
            params.extend([token, token, token, token])
        if extension:
            where.append("extension=?")
            params.append(extension)
        params.append(limit)
        sql = f"SELECT * FROM candidates WHERE {' AND '.join(where)} ORDER BY block_height DESC, id DESC LIMIT ?"
        return list(self.connection.execute(sql, params))

    def get(self, candidate_id: int) -> sqlite3.Row | None:
        self.connection.row_factory = sqlite3.Row
        return self.connection.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()

    def export_rows(self, chain_id: str, extension: str) -> list[sqlite3.Row]:
        self.connection.row_factory = sqlite3.Row
        return list(self.connection.execute("""
            SELECT * FROM candidates
            WHERE chain_id=? AND extension=? AND confidence>=0.95 AND magic_offset=0
            ORDER BY block_height, id
        """, (chain_id, extension)))

    def distinct_extensions(self, chain_id: str) -> list[str]:
        return [row[0] for row in self.connection.execute(
            "SELECT DISTINCT extension FROM candidates WHERE chain_id=? AND confidence>=0.95 AND magic_offset=0 ORDER BY extension",
            (chain_id,),
        )]
