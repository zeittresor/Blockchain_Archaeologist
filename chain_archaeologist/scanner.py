from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from PySide6.QtCore import QThread, Signal

from .catalog import CandidateRecord, Catalog
from .detection import detect_payload, shannon_entropy
from .rpc import RpcClient, RpcError, RpcSettings
from .script_parser import data_pushes, op_return_payloads, ordinal_envelopes
from .util import RateEstimator


@dataclass(frozen=True)
class ScanOptions:
    chain_id: str
    catalog_path: str
    start_height: int
    end_height: int
    batch_size: int
    minimum_payload_size: int
    maximum_payload_size: int
    catalog_unknown_op_return: bool
    catalog_all_data_pushes: bool
    minimum_generic_confidence: float
    preview_max_bytes: int
    safe_text_mimes: tuple[str, ...]


class ScanWorker(QThread):
    progress = Signal(dict)
    candidate_count = Signal(int)
    log = Signal(str)
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(self, rpc_settings: RpcSettings, options: ScanOptions) -> None:
        super().__init__()
        self.rpc_settings = rpc_settings
        self.options = options
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._pause.set()
        self._rate = RateEstimator(max_samples=30)

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.set()

    def pause(self) -> None:
        self._pause.clear()

    def resume(self) -> None:
        self._pause.set()

    def _wait_if_paused(self) -> bool:
        while not self._pause.wait(0.2):
            if self._cancel.is_set():
                return False
        return not self._cancel.is_set()

    def run(self) -> None:
        client = RpcClient(self.rpc_settings)
        catalog: Catalog | None = None
        started = time.monotonic()
        try:
            info = client.call("getblockchaininfo")
            tip = int(info["blocks"])
            start = max(0, self.options.start_height)
            end = tip if self.options.end_height < 0 else min(tip, self.options.end_height)
            if end < start:
                raise RuntimeError(f"Invalid scan range: {start}..{end}")
            catalog = Catalog(self.options.catalog_path)
            total = end - start + 1
            found_total = catalog.count(self.options.chain_id)
            processed = 0
            last_processed_height: int | None = None
            self._rate.add(0)

            for batch_start in range(start, end + 1, max(1, self.options.batch_size)):
                if self._cancel.is_set() or not self._wait_if_paused():
                    break
                heights = list(range(batch_start, min(end + 1, batch_start + self.options.batch_size)))
                hashes = client.batch(("getblockhash", [height]) for height in heights)
                blocks = self._fetch_blocks(client, hashes)
                batch_records: list[CandidateRecord] = []
                for height, block_hash, block in zip(heights, hashes, blocks):
                    if self._cancel.is_set() or not self._wait_if_paused():
                        break
                    batch_records.extend(self._analyze_block(client, height, str(block_hash), block))
                    processed += 1
                    last_processed_height = height
                    self._rate.add(processed)
                    rate = self._rate.rate()
                    eta = ((total - processed) / rate) if rate and rate > 0 else None
                    self.progress.emit({
                        "current": processed,
                        "total": total,
                        "height": height,
                        "tip": tip,
                        "rate": rate,
                        "eta": eta,
                        "elapsed": time.monotonic() - started,
                        "found": found_total + len(batch_records),
                    })
                added = catalog.add_many(batch_records)
                found_total += added
                self.candidate_count.emit(found_total)
                if last_processed_height is not None:
                    catalog.update_scan_state(self.options.chain_id, last_processed_height, tip, int(time.time()))

            cancelled = self._cancel.is_set()
            self.completed.emit({
                "cancelled": cancelled,
                "processed": processed,
                "total": total,
                "found": found_total,
                "elapsed": time.monotonic() - started,
            })
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if catalog is not None:
                catalog.close()

    def _fetch_blocks(self, client: RpcClient, hashes: list[Any]) -> list[dict[str, Any]]:
        try:
            blocks = client.batch(("getblock", [str(block_hash), 2]) for block_hash in hashes)
        except RpcError:
            blocks = [client.call("getblock", [str(block_hash), 2]) for block_hash in hashes]
        hydrated: list[dict[str, Any]] = []
        for block_hash, block in zip(hashes, blocks):
            txs = block.get("tx", []) if isinstance(block, dict) else []
            if txs and isinstance(txs[0], str):
                self.log.emit("Node returned transaction IDs only; using getrawtransaction fallback.")
                txids = [str(txid) for txid in txs]
                try:
                    full_txs = client.batch(("getrawtransaction", [txid, True, str(block_hash)]) for txid in txids)
                except RpcError:
                    full_txs = client.batch(("getrawtransaction", [txid, True]) for txid in txids)
                block = dict(block)
                block["tx"] = full_txs
            hydrated.append(block)
        return hydrated

    def _analyze_block(self, client: RpcClient, height: int, block_hash: str, block: dict[str, Any]) -> list[CandidateRecord]:
        records: list[CandidateRecord] = []
        block_time = int(block.get("time", 0))
        txs = block.get("tx", [])
        for tx_index, tx in enumerate(txs):
            if not isinstance(tx, dict):
                continue
            txid = str(tx.get("txid") or tx.get("hash") or "")
            context = {
                "block_time_iso": datetime.fromtimestamp(block_time, tz=timezone.utc).isoformat() if block_time else "",
                "version": tx.get("version"),
                "locktime": tx.get("locktime"),
            }

            for vin_index, vin in enumerate(tx.get("vin", [])):
                coinbase_hex = vin.get("coinbase")
                if coinbase_hex:
                    payload = self._safe_hex(coinbase_hex)
                    self._consider(records, payload, height, block_hash, block_time, txid, tx_index,
                                   f"vin[{vin_index}].coinbase", "coinbase scriptSig", 0, context,
                                   explicit=False)
                script_hex = (vin.get("scriptSig") or {}).get("hex")
                if script_hex:
                    script = self._safe_hex(script_hex)
                    for item_index, payload in enumerate(data_pushes(script)):
                        self._consider(records, payload, height, block_hash, block_time, txid, tx_index,
                                       f"vin[{vin_index}].scriptSig", "scriptSig data push", item_index,
                                       context, explicit=False)
                witness = vin.get("txinwitness") or vin.get("witness") or []
                for witness_index, item_hex in enumerate(witness):
                    item = self._safe_hex(item_hex)
                    if not item:
                        continue
                    envelopes = ordinal_envelopes(item)
                    for env_index, envelope in enumerate(envelopes):
                        meta = dict(context)
                        meta["declared_content_type"] = envelope.content_type
                        self._consider(records, envelope.body, height, block_hash, block_time, txid, tx_index,
                                       f"vin[{vin_index}].witness[{witness_index}]", "ordinal-style witness envelope",
                                       env_index, meta, explicit=True, declared_mime=envelope.content_type)
                    if not envelopes:
                        self._consider(records, item, height, block_hash, block_time, txid, tx_index,
                                       f"vin[{vin_index}].witness[{witness_index}]", "witness stack item",
                                       witness_index, context, explicit=False)

            for vout_index, vout in enumerate(tx.get("vout", [])):
                script_info = vout.get("scriptPubKey") or {}
                script_hex = script_info.get("hex")
                if not script_hex:
                    continue
                script = self._safe_hex(script_hex)
                returned = op_return_payloads(script)
                if returned:
                    joined = b"".join(returned)
                    self._consider(records, joined, height, block_hash, block_time, txid, tx_index,
                                   f"vout[{vout_index}].scriptPubKey", "OP_RETURN", 0,
                                   {**context, "script_type": script_info.get("type")}, explicit=True)
                    continue
                pushes = data_pushes(script)
                for item_index, payload in enumerate(pushes):
                    self._consider(records, payload, height, block_hash, block_time, txid, tx_index,
                                   f"vout[{vout_index}].scriptPubKey", "output script data push", item_index,
                                   {**context, "script_type": script_info.get("type")}, explicit=False)
                if len(pushes) > 1:
                    self._consider(records, b"".join(pushes), height, block_hash, block_time, txid, tx_index,
                                   f"vout[{vout_index}].scriptPubKey", "joined output script pushes", 999,
                                   {**context, "script_type": script_info.get("type")}, explicit=False)

            extra_payload = tx.get("extraPayload") or tx.get("extra_payload")
            if isinstance(extra_payload, str) and extra_payload:
                self._consider(records, self._safe_hex(extra_payload), height, block_hash, block_time, txid, tx_index,
                               "transaction.extraPayload", "special transaction extra payload", 0,
                               context, explicit=True)
        return records

    def _consider(
        self,
        records: list[CandidateRecord],
        payload: bytes,
        height: int,
        block_hash: str,
        block_time: int,
        txid: str,
        tx_index: int,
        location: str,
        method: str,
        item_index: int,
        metadata: dict[str, Any],
        explicit: bool,
        declared_mime: str | None = None,
    ) -> None:
        if not (self.options.minimum_payload_size <= len(payload) <= self.options.maximum_payload_size):
            return
        detection = detect_payload(payload, declared_mime, self.options.preview_max_bytes)
        if explicit:
            if detection.confidence <= 0 and not self.options.catalog_unknown_op_return:
                return
        elif not self.options.catalog_all_data_pushes and detection.confidence < self.options.minimum_generic_confidence:
            return
        preview = detection.preview_text if detection.mime in self.options.safe_text_mimes else None
        records.append(CandidateRecord(
            chain_id=self.options.chain_id,
            block_height=height,
            block_hash=block_hash,
            block_time=block_time,
            txid=txid,
            tx_index=tx_index,
            location=location,
            embedding_method=method,
            item_index=item_index,
            payload_size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            entropy=shannon_entropy(payload),
            detected_type=detection.detected_type,
            extension=detection.extension,
            mime=detection.mime,
            confidence=detection.confidence,
            magic_offset=detection.magic_offset,
            preview_text=preview,
            payload=payload,
            metadata=metadata,
        ))

    @staticmethod
    def _safe_hex(value: Any) -> bytes:
        if not isinstance(value, str):
            return b""
        try:
            return bytes.fromhex(value)
        except ValueError:
            return b""
