# Blockchain Archaeologist v0.1.0

A project-local PySide6 desktop application for downloading and preserving archival full-node data through official Core-compatible clients, monitoring synchronization, and cataloging embedded non-financial payloads without automatically executing or rendering them.

## Included chain profiles

| Profile | Mining family | Adapter status | Notes |
|---|---|---:|---|
| Bitcoin | SHA-256d | Full | OP_RETURN, script pushes, witness items and ordinal-style envelopes |
| Litecoin | Scrypt | Full | Generic transaction/script scanner; MWEB semantic decoding is not included |
| Bitcoin Cash Node | SHA-256d | Full | Generic vin/vout script scanning |
| Dogecoin | Scrypt + AuxPoW | Experimental | Older node versions can require `txindex` for fallback transaction hydration |
| Namecoin | SHA-256d + AuxPoW | Experimental | Name operations are visible as generic script pushes; semantic name decoding is not included |
| Dash | X11 | Experimental | Generic scripts plus RPC-exposed special-transaction `extraPayload`; full special-TX decoding is not included |

Profiles are external JSON in `assets/chain_profiles.json`; additional Bitcoin-Core-like chains can be added without changing the GUI.

## What the application does

- Launches a user-selected official node executable against a user-selected data directory.
- Forces archival storage with `-prune=0` and defaults to a wallet-disabled analysis node.
- Monitors `blocks`, `headers`, `verificationprogress`, `initialblockdownload`, `size_on_disk`, peer count and rolling rates.
- Shows two progress bars, elapsed time, current work item, a cancellable phase, and a rolling ETA forecast.
- Scans a selected block-height range via local JSON-RPC, which avoids parsing chain-specific AuxPoW headers directly.
- Catalogs candidates in a project-local SQLite database with:
  - chain/profile
  - block height, hash and UTC time
  - TXID and transaction index
  - exact transaction field/location
  - embedding method
  - payload size
  - SHA-256
  - Shannon entropy
  - detected type, extension and MIME
  - confidence and magic offset
  - safe text preview, where allowed
  - exact candidate bytes for controlled export
- Supports pause/resume/cancel for analysis.
- Extracts one selected candidate or all strictly identified candidates of a chosen type.
- Bulk extraction is restricted to confidence >= 95% and a file signature beginning at byte zero.
- Writes optional JSON evidence sidecars.

## Safety model

The application deliberately does **not**:

- execute payloads;
- launch exported files;
- render images, audio, video, PDFs or archives automatically;
- invoke shell commands based on blockchain content;
- expose RPC beyond the host configured by the user.

Only allow-listed textual MIME types are shown in the preview pane. Binary extraction should be performed in a VM or quarantine directory. Public blockchains can contain malicious, disturbing, copyrighted or unlawful content; the operator is responsible for local handling and applicable law.

## Installation on Windows

1. Install Python 3.10 or newer.
2. Run `install_windows.bat`.
3. The installer creates a project-local `.venv`, installs dependencies, writes a log under `app_data/logs`, and offers a cancellable 10-second automatic start.

For a disconnected target machine:

1. On an online machine, run `build_wheelhouse.bat`.
2. Copy the whole project including `wheelhouse` to the offline machine.
3. Run `install_offline.bat`.

The blockchain itself must first be synchronized by the selected node. After synchronization, scanning and catalog work against the local node and local data directory and can operate without internet access.

## Typical first run

1. Open **Node & Sync**.
2. Select a chain profile.
3. Use the official download-page button, download the correct official node, and verify its signatures/checksums according to that project's instructions.
4. Select the daemon or GUI executable.
5. Select a fresh dedicated data directory on a drive with sufficient free space. A previously pruned directory cannot recreate deleted historical blocks merely by switching pruning off.
6. Start the node. The exact command is displayed.
7. Wait until the node reports synchronized. ETA is approximate because validation and disk I/O are non-linear.
8. Optionally disconnect networking.
9. Open **Analysis**, select a block range, and start the scan.
10. Review the **Catalog** and export only material you deliberately choose.

## RPC authentication

Cookie authentication is preferred. The default expected cookie is `<data directory>/.cookie`. Explicit RPC username/password fields are available for older or custom configurations. Keep RPC bound to `127.0.0.1`.

## Storage layout

```text
Blockchain-Archaeologist/
├─ app.py
├─ app_data/
│  ├─ config.json
│  ├─ logs/
│  └─ workspaces/
│     └─ <chain-id>/catalog.sqlite3
├─ assets/
│  ├─ chain_profiles.json
│  ├─ locales/
│  └─ themes/
└─ chain_archaeologist/
```

The selected blockchain data directory is separate and is never rewritten by the scanner. The official node owns and updates its `blocks`, `chainstate`, indexes and cookie files.

## Detection notes

High-confidence signatures include PNG, JPEG, GIF, BMP, TIFF, PDF, ZIP, 7-Zip, RAR, GZIP, Ogg, FLAC, WAV/RIFF, MP3, PE, ELF, WebAssembly, SQLite and TAR. UTF-8 text, JSON, XML/HTML, CSV-like text and several source-code patterns are also recognized.

Detection does not prove authorship, legality, completeness or original filename. Fragmented, encrypted, compressed-without-header or custom-protocol data may remain unidentified. The exhaustive script-push option can produce a very large number of false positives and is disabled by default.

## Known v0.1.0 limitations

- The scanner uses decoded block/transaction JSON from local RPC rather than direct `blk*.dat` parsing. This is intentional for multi-chain compatibility and does not modify raw block files.
- File fragments spread across unrelated transactions are not automatically reassembled.
- Ordinal-style envelopes are supported conservatively; every inscription variant is not guaranteed.
- Litecoin MWEB, Namecoin name semantics and the complete Dash special-transaction schema need dedicated adapters.
- Very old node versions may not support `getblock(hash, 2)`. The fallback can require `txindex=1`.
- ETA is a rolling estimate and can change substantially during initial sync or slow historical blocks.

## Development checks

```bash
python -m compileall app.py chain_archaeologist
python -m unittest discover -s tests -v
```
