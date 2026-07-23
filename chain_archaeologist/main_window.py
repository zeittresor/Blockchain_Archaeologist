from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSpinBox, QDoubleSpinBox, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTextBrowser, QVBoxLayout, QWidget, QAbstractItemView
)

from . import APP_NAME, __version__
from .catalog import Catalog
from .config import AppConfig, PROJECT_ROOT
from .extraction import BulkExportWorker, export_candidate
from .i18n import Translator
from .node_manager import NodeManager
from .profiles import ChainProfile, load_profiles
from .progress_panel import ProgressPanel
from .rpc import RpcClient, RpcError, RpcSettings
from .scanner import ScanOptions, ScanWorker
from .themes import make_qss
from .util import RateEstimator, human_bytes, human_duration


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = AppConfig.load()
        self.tr = Translator(self.config.language)
        self.profiles = load_profiles()
        self.profile_by_id = {p.id: p for p in self.profiles}
        self.node_manager = NodeManager()
        self.scan_worker: ScanWorker | None = None
        self.export_worker: BulkExportWorker | None = None
        self._active_cancel: Callable[[], None] | None = None
        self._sync_started = time.monotonic()
        self._sync_progress_rate = RateEstimator(max_samples=30)
        self._sync_block_rate = RateEstimator(max_samples=30)
        self._last_profile_datadir = ""
        self._build_ui()
        self._load_config_into_ui()
        self.apply_language()
        self.apply_theme()
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(2500)
        self.sync_timer.timeout.connect(self.refresh_sync_status)
        self.refresh_dashboard()
        self.refresh_catalog()

    # ---------- UI foundations ----------
    def _build_ui(self) -> None:
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(self.config.window_width, self.config.window_height)
        self.setMinimumSize(900, 650)

        central = QWidget()
        root = QVBoxLayout(central)
        body = QHBoxLayout()
        self.nav = QListWidget()
        self.nav.setFixedWidth(205)
        self.nav_items = ["Dashboard", "Node & Sync", "Analysis", "Catalog", "Settings", "Help"]
        self.nav.addItems(self.nav_items)
        self.nav.setToolTip("Switch between application sections")
        self.stack = QStackedWidget()
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)
        self.progress_panel = ProgressPanel()
        self.progress_panel.cancel_requested.connect(self.cancel_active_operation)
        root.addWidget(self.progress_panel)
        self.setCentralWidget(central)

        self.dashboard_page = self._build_dashboard_page()
        self.node_page = self._build_node_page()
        self.analysis_page = self._build_analysis_page()
        self.catalog_page = self._build_catalog_page()
        self.settings_page = self._build_settings_page()
        self.help_page = self._build_help_page()
        for page in [self.dashboard_page, self.node_page, self.analysis_page, self.catalog_page, self.settings_page, self.help_page]:
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

    @staticmethod
    def _scroll_page(content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(content)
        return scroll

    @staticmethod
    def _card(title: str = "") -> tuple[QGroupBox, QVBoxLayout]:
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        return box, layout

    @staticmethod
    def _browse_row(line: QLineEdit, callback: Callable[[], None], button_text: str = "Browse…") -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton(button_text)
        button.clicked.connect(callback)
        layout.addWidget(line, 1)
        layout.addWidget(button)
        return widget

    # ---------- Dashboard ----------
    def _build_dashboard_page(self) -> QScrollArea:
        content = QWidget()
        layout = QVBoxLayout(content)
        title = QLabel(f"<h1>{APP_NAME}</h1><p>Offline-capable blockchain data archaeology with a controlled evidence catalog.</p>")
        title.setWordWrap(True)
        layout.addWidget(title)

        card, grid_layout = self._card("Current workspace")
        grid = QGridLayout()
        self.dashboard_chain = QLabel("—")
        self.dashboard_datadir = QLabel("—")
        self.dashboard_catalog = QLabel("—")
        self.dashboard_candidates = QLabel("—")
        self.dashboard_support = QLabel("—")
        for row, (label, value) in enumerate([
            ("Chain profile", self.dashboard_chain),
            ("Raw blockchain data directory", self.dashboard_datadir),
            ("Catalog database", self.dashboard_catalog),
            ("Cataloged candidates", self.dashboard_candidates),
            ("Adapter support", self.dashboard_support),
        ]):
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(value, row, 1)
        grid.setColumnStretch(1, 1)
        grid_layout.addLayout(grid)
        refresh = QPushButton("Refresh workspace summary")
        refresh.clicked.connect(self.refresh_dashboard)
        grid_layout.addWidget(refresh)
        layout.addWidget(card)

        safety, safety_layout = self._card("Safety model")
        safety_text = QLabel(
            "The application never executes extracted bytes and never renders binary media automatically. "
            "Only allow-listed textual MIME types can be previewed. Binary material is exported only after an explicit action."
        )
        safety_text.setWordWrap(True)
        safety_layout.addWidget(safety_text)
        layout.addWidget(safety)

        workflow, workflow_layout = self._card("Recommended workflow")
        workflow_label = QLabel(
            "1. Select an official Core-compatible node and a dedicated data directory.\n"
            "2. Synchronize with pruning disabled and watch the progress/ETA estimate.\n"
            "3. Disconnect the machine or disable node networking for offline analysis.\n"
            "4. Scan a selected height range into the SQLite evidence catalog.\n"
            "5. Review metadata and text previews; export selected or strictly identified file types."
        )
        workflow_label.setWordWrap(True)
        workflow_layout.addWidget(workflow_label)
        layout.addWidget(workflow)
        layout.addStretch(1)
        return self._scroll_page(content)

    # ---------- Node and sync ----------
    def _build_node_page(self) -> QScrollArea:
        content = QWidget()
        layout = QVBoxLayout(content)
        profile_box, profile_layout = self._card("Chain profile")
        form = QFormLayout()
        self.profile_combo = QComboBox()
        for profile in self.profiles:
            self.profile_combo.addItem(f"{profile.name} ({profile.symbol}) — {profile.support_level}", profile.id)
        self.profile_combo.setToolTip("Select the blockchain/node adapter. Profiles are stored in assets/chain_profiles.json.")
        self.profile_combo.currentIndexChanged.connect(self.on_profile_changed)
        self.profile_notes = QLabel()
        self.profile_notes.setWordWrap(True)
        self.profile_details = QLabel()
        self.profile_details.setWordWrap(True)
        form.addRow("Blockchain", self.profile_combo)
        form.addRow("Profile details", self.profile_details)
        form.addRow("Support notes", self.profile_notes)
        profile_layout.addLayout(form)
        official = QPushButton("Open official node download page")
        official.setToolTip("Opens the official project website. Verify signatures/checksums before using downloaded binaries.")
        official.clicked.connect(self.open_official_download)
        profile_layout.addWidget(official)
        layout.addWidget(profile_box)

        node_box, node_layout = self._card("Local node and raw data storage")
        form = QFormLayout()
        self.node_exe_edit = QLineEdit()
        self.node_exe_edit.setToolTip("Select the official daemon or GUI executable, such as bitcoind.exe or litecoind.exe.")
        self.node_datadir_edit = QLineEdit()
        self.node_datadir_edit.setToolTip("Dedicated destination for blocks/blk*.dat, chainstate and node metadata. Pruning is disabled.")
        self.node_extra_args_edit = QLineEdit()
        self.node_extra_args_edit.setToolTip("Optional advanced node command-line arguments. Avoid wallet or remote-RPC exposure.")
        form.addRow("Node executable", self._browse_row(self.node_exe_edit, self.browse_node_executable))
        form.addRow("Blockchain data directory", self._browse_row(self.node_datadir_edit, self.browse_node_datadir))
        form.addRow("Additional node arguments", self.node_extra_args_edit)
        self.disable_wallet_check = QCheckBox("Disable wallet subsystem for this analysis node")
        self.listen_check = QCheckBox("Allow inbound P2P connections")
        form.addRow("Safety", self.disable_wallet_check)
        form.addRow("Networking", self.listen_check)
        node_layout.addLayout(form)
        button_row = QHBoxLayout()
        self.start_node_button = QPushButton("Start node / begin or continue synchronization")
        self.stop_node_button = QPushButton("Stop node cleanly")
        self.start_node_button.clicked.connect(self.start_node)
        self.stop_node_button.clicked.connect(self.stop_node)
        button_row.addWidget(self.start_node_button)
        button_row.addWidget(self.stop_node_button)
        node_layout.addLayout(button_row)
        self.node_command_preview = QPlainTextEdit()
        self.node_command_preview.setReadOnly(True)
        self.node_command_preview.setMaximumHeight(100)
        self.node_command_preview.setPlaceholderText("The exact launch command will appear here.")
        node_layout.addWidget(self.node_command_preview)
        layout.addWidget(node_box)

        rpc_box, rpc_layout = self._card("Local JSON-RPC connection")
        form = QFormLayout()
        self.rpc_host_edit = QLineEdit("127.0.0.1")
        self.rpc_port_spin = QSpinBox(); self.rpc_port_spin.setRange(1, 65535)
        self.rpc_user_edit = QLineEdit()
        self.rpc_password_edit = QLineEdit(); self.rpc_password_edit.setEchoMode(QLineEdit.Password)
        self.cookie_edit = QLineEdit()
        self.cookie_edit.setToolTip("Cookie authentication is preferred. Default: <data directory>/.cookie")
        form.addRow("RPC host", self.rpc_host_edit)
        form.addRow("RPC port", self.rpc_port_spin)
        form.addRow("RPC user (optional)", self.rpc_user_edit)
        form.addRow("RPC password (optional)", self.rpc_password_edit)
        form.addRow("Cookie file", self._browse_row(self.cookie_edit, self.browse_cookie_file))
        rpc_layout.addLayout(form)
        row = QHBoxLayout()
        test = QPushButton("Test local RPC")
        refresh = QPushButton("Refresh synchronization status")
        test.clicked.connect(self.test_rpc)
        refresh.clicked.connect(self.refresh_sync_status)
        row.addWidget(test); row.addWidget(refresh)
        rpc_layout.addLayout(row)
        layout.addWidget(rpc_box)

        sync_box, sync_layout = self._card("Synchronization progress and forecast")
        stats = QGridLayout()
        self.sync_state_label = QLabel("Not connected")
        self.sync_height_label = QLabel("—")
        self.sync_disk_label = QLabel("—")
        self.sync_rate_label = QLabel("—")
        self.sync_eta_label = QLabel("—")
        self.sync_peers_label = QLabel("—")
        pairs = [
            ("State", self.sync_state_label), ("Blocks / headers", self.sync_height_label),
            ("Raw block and undo data", self.sync_disk_label), ("Recent validation rate", self.sync_rate_label),
            ("ETA forecast", self.sync_eta_label), ("Peer connections", self.sync_peers_label),
        ]
        for i, (label, widget) in enumerate(pairs):
            stats.addWidget(QLabel(label), i, 0)
            stats.addWidget(widget, i, 1)
        stats.setColumnStretch(1, 1)
        sync_layout.addLayout(stats)
        self.sync_overall_bar = QProgressBar(); self.sync_overall_bar.setRange(0, 10000)
        self.sync_header_bar = QProgressBar(); self.sync_header_bar.setRange(0, 10000)
        sync_layout.addWidget(QLabel("Consensus validation estimate")); sync_layout.addWidget(self.sync_overall_bar)
        sync_layout.addWidget(QLabel("Downloaded/validated blocks relative to known headers")); sync_layout.addWidget(self.sync_header_bar)
        warning = QLabel("ETA is a rolling estimate. Header discovery, signature verification, reindexing and disk I/O make initial synchronization non-linear.")
        warning.setWordWrap(True); warning.setObjectName("Muted")
        sync_layout.addWidget(warning)
        layout.addWidget(sync_box)
        layout.addStretch(1)
        return self._scroll_page(content)

    # ---------- Analysis ----------
    def _build_analysis_page(self) -> QScrollArea:
        content = QWidget()
        layout = QVBoxLayout(content)
        range_box, range_layout = self._card("Analysis range")
        form = QFormLayout()
        self.scan_start_spin = QSpinBox(); self.scan_start_spin.setRange(0, 2_100_000_000)
        self.scan_end_spin = QSpinBox(); self.scan_end_spin.setRange(-1, 2_100_000_000); self.scan_end_spin.setSpecialValueText("Current local tip")
        self.scan_batch_spin = QSpinBox(); self.scan_batch_spin.setRange(1, 128)
        form.addRow("Start block height", self.scan_start_spin)
        form.addRow("End block height (-1 = tip)", self.scan_end_spin)
        form.addRow("RPC batch size", self.scan_batch_spin)
        range_layout.addLayout(form)
        resume = QPushButton("Resume after last cataloged scan height")
        resume.clicked.connect(self.resume_scan_height)
        range_layout.addWidget(resume)
        layout.addWidget(range_box)

        detection_box, detection_layout = self._card("Detection policy")
        form = QFormLayout()
        self.min_payload_spin = QSpinBox(); self.min_payload_spin.setRange(1, 1_000_000)
        self.max_payload_spin = QSpinBox(); self.max_payload_spin.setRange(1024, 1024 * 1024 * 1024); self.max_payload_spin.setSingleStep(1024 * 1024)
        self.generic_conf_spin = QDoubleSpinBox(); self.generic_conf_spin.setRange(0.0, 1.0); self.generic_conf_spin.setSingleStep(0.05); self.generic_conf_spin.setDecimals(2)
        self.catalog_unknown_check = QCheckBox("Catalog unknown OP_RETURN / explicit envelope payloads")
        self.catalog_all_pushes_check = QCheckBox("Catalog every script data push (very large/noisy catalog)")
        form.addRow("Minimum candidate bytes", self.min_payload_spin)
        form.addRow("Maximum candidate bytes", self.max_payload_spin)
        form.addRow("Minimum generic type confidence", self.generic_conf_spin)
        form.addRow("Explicit data channels", self.catalog_unknown_check)
        form.addRow("Forensic exhaustive mode", self.catalog_all_pushes_check)
        detection_layout.addLayout(form)
        layout.addWidget(detection_box)

        action_box, action_layout = self._card("Run analysis")
        buttons = QHBoxLayout()
        self.start_scan_button = QPushButton("Start / continue analysis")
        self.pause_scan_button = QPushButton("Pause")
        self.cancel_scan_button = QPushButton("Cancel")
        self.pause_scan_button.setEnabled(False); self.cancel_scan_button.setEnabled(False)
        self.start_scan_button.clicked.connect(self.start_scan)
        self.pause_scan_button.clicked.connect(self.toggle_scan_pause)
        self.cancel_scan_button.clicked.connect(self.cancel_scan)
        buttons.addWidget(self.start_scan_button); buttons.addWidget(self.pause_scan_button); buttons.addWidget(self.cancel_scan_button)
        action_layout.addLayout(buttons)
        self.scan_progress_bar = QProgressBar(); self.scan_progress_bar.setRange(0, 10000)
        self.scan_status_label = QLabel("Idle")
        self.scan_metrics_label = QLabel("—")
        action_layout.addWidget(self.scan_status_label)
        action_layout.addWidget(self.scan_progress_bar)
        action_layout.addWidget(self.scan_metrics_label)
        self.scan_log = QPlainTextEdit(); self.scan_log.setReadOnly(True); self.scan_log.setMaximumHeight(190)
        action_layout.addWidget(self.scan_log)
        layout.addWidget(action_box)
        layout.addStretch(1)
        return self._scroll_page(content)

    # ---------- Catalog ----------
    def _build_catalog_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        self.catalog_search_edit = QLineEdit(); self.catalog_search_edit.setPlaceholderText("Search TXID, type, MIME or embedding method")
        self.catalog_extension_filter = QComboBox(); self.catalog_extension_filter.addItem("All types", "")
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_catalog)
        self.catalog_search_edit.returnPressed.connect(self.refresh_catalog)
        self.catalog_extension_filter.currentIndexChanged.connect(self.refresh_catalog)
        controls.addWidget(self.catalog_search_edit, 1); controls.addWidget(self.catalog_extension_filter); controls.addWidget(refresh)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Vertical)
        self.catalog_table = QTableWidget(0, 10)
        self.catalog_table.setHorizontalHeaderLabels(["ID", "Height", "UTC date", "TXID", "Embedding", "Detected type", "Size", "Entropy", "Confidence", "Location"])
        self.catalog_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.catalog_table.horizontalHeader().setStretchLastSection(True)
        self.catalog_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.catalog_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.catalog_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.catalog_table.setAlternatingRowColors(True)
        self.catalog_table.itemSelectionChanged.connect(self.show_selected_candidate)
        splitter.addWidget(self.catalog_table)

        details = QWidget(); details_layout = QVBoxLayout(details)
        self.candidate_meta = QPlainTextEdit(); self.candidate_meta.setReadOnly(True)
        self.candidate_preview = QPlainTextEdit(); self.candidate_preview.setReadOnly(True)
        self.candidate_preview.setPlaceholderText("Text preview is available only for allow-listed textual MIME types.")
        details_layout.addWidget(QLabel("Evidence metadata")); details_layout.addWidget(self.candidate_meta)
        details_layout.addWidget(QLabel("Safe text preview")); details_layout.addWidget(self.candidate_preview)
        buttons = QHBoxLayout()
        extract = QPushButton("Extract selected candidate…")
        extract.clicked.connect(self.extract_selected)
        self.bulk_type_combo = QComboBox()
        bulk = QPushButton("Bulk extract strictly identified type…")
        bulk.clicked.connect(self.bulk_extract)
        buttons.addWidget(extract); buttons.addStretch(1); buttons.addWidget(self.bulk_type_combo); buttons.addWidget(bulk)
        details_layout.addLayout(buttons)
        splitter.addWidget(details)
        splitter.setSizes([430, 280])
        layout.addWidget(splitter, 1)
        return page

    # ---------- Settings ----------
    def _build_settings_page(self) -> QScrollArea:
        content = QWidget(); layout = QVBoxLayout(content)
        ui_box, ui_layout = self._card("Interface")
        form = QFormLayout()
        self.language_combo = QComboBox()
        for code, label in [("en", "English"), ("de", "Deutsch"), ("fr", "Français"), ("ru", "Русский")]:
            self.language_combo.addItem(label, code)
        self.theme_combo = QComboBox(); self.theme_combo.addItems(["light", "dark", "sepia", "ocean", "matrix", "hellfire", "purple", "aurora"])
        self.window_width_spin = QSpinBox(); self.window_width_spin.setRange(900, 7680)
        self.window_height_spin = QSpinBox(); self.window_height_spin.setRange(650, 4320)
        form.addRow("Language (English default)", self.language_combo)
        form.addRow("Theme", self.theme_combo)
        form.addRow("Default window width", self.window_width_spin)
        form.addRow("Default window height", self.window_height_spin)
        ui_layout.addLayout(form)
        layout.addWidget(ui_box)

        paths_box, paths_layout = self._card("Project-local storage")
        form = QFormLayout()
        self.workspace_edit = QLineEdit()
        form.addRow("Workspace root", self._browse_row(self.workspace_edit, self.browse_workspace))
        paths_layout.addLayout(form)
        note = QLabel("Catalog databases and settings are stored under the project by default. Blockchain data remains in the separately selected node data directory.")
        note.setWordWrap(True); paths_layout.addWidget(note)
        layout.addWidget(paths_box)

        safety_box, safety_layout = self._card("Extraction and preview safety")
        form = QFormLayout()
        self.preview_max_spin = QSpinBox(); self.preview_max_spin.setRange(1024, 16 * 1024 * 1024); self.preview_max_spin.setSingleStep(1024)
        self.sidecar_check = QCheckBox("Write JSON evidence sidecar next to exported files")
        self.confirm_bulk_check = QCheckBox("Require confirmation before bulk extraction")
        form.addRow("Maximum text preview bytes", self.preview_max_spin)
        form.addRow("Evidence metadata", self.sidecar_check)
        form.addRow("Bulk extraction", self.confirm_bulk_check)
        safety_layout.addLayout(form)
        layout.addWidget(safety_box)

        save = QPushButton("Save settings")
        save.clicked.connect(self.save_settings)
        layout.addWidget(save)
        layout.addStretch(1)
        return self._scroll_page(content)

    # ---------- Help ----------
    def _build_help_page(self) -> QScrollArea:
        content = QWidget(); layout = QVBoxLayout(content)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(f"""
        <h1>{APP_NAME} v{__version__}</h1>
        <h2>Purpose</h2>
        <p>This application manages a dedicated archival full-node data directory and scans locally available blocks through the node's read-only JSON-RPC interface. The node remains responsible for consensus validation and storage of the original <code>blocks/blk*.dat</code> files.</p>
        <h2>Supported profiles</h2>
        <p>Bitcoin, Litecoin and Bitcoin Cash use the full generic adapter. Dogecoin, Namecoin and Dash are marked experimental because older RPC variants and chain-specific transaction fields can differ. The generic scanner still inspects coinbase bytes, input scripts, output scripts, OP_RETURN data, witness stack items and known ordinal-style envelopes. Dash extraPayload fields are cataloged when exposed by RPC.</p>
        <h2>Synchronization</h2>
        <p>The launcher forces <code>prune=0</code>. Synchronization progress uses <code>getblockchaininfo</code> fields such as blocks, headers, verificationprogress, initialblockdownload and size_on_disk. ETA is a rolling forecast, not a guarantee.</p>
        <h2>Offline operation</h2>
        <p>After synchronization, analysis requires only the local node and its data directory. Disconnect the network physically or start the node with a suitable network-disable argument supported by that node version. RPC should remain bound to localhost only.</p>
        <h2>Detection</h2>
        <p>The catalog records block height/time, block hash, TXID, exact location, embedding method, byte count, SHA-256, Shannon entropy, detected type, MIME, extension and confidence. Bulk extraction is limited to candidates with a signature at byte zero and confidence of at least 95%.</p>
        <h2>Safety</h2>
        <ul>
          <li>No binary payload is rendered or executed automatically.</li>
          <li>Only configured text MIME types can be previewed.</li>
          <li>Use a VM, quarantine directory and non-indexed storage for exports.</li>
          <li>Unknown or unlawful material may exist in public blockchains. The operator is responsible for local handling and applicable law.</li>
          <li>Do not expose node RPC to other hosts and do not use a wallet-enabled analysis node unless necessary.</li>
        </ul>
        <h2>Extensibility</h2>
        <p>Additional Bitcoin-Core-like chains can be added in <code>assets/chain_profiles.json</code>. Profile definitions select ports, executable names, default directories and support notes; they do not change consensus rules.</p>
        """)
        layout.addWidget(browser)
        return self._scroll_page(content)

    # ---------- Configuration ----------
    def _load_config_into_ui(self) -> None:
        index = self.profile_combo.findData(self.config.profile_id)
        self.profile_combo.setCurrentIndex(max(0, index))
        self.node_exe_edit.setText(self.config.node_executable)
        self.node_datadir_edit.setText(self.config.node_datadir or self.current_profile().expanded_windows_datadir())
        self._last_profile_datadir = self.node_datadir_edit.text()
        self.node_extra_args_edit.setText(self.config.node_extra_args)
        self.disable_wallet_check.setChecked(self.config.disable_wallet)
        self.listen_check.setChecked(self.config.listen_for_inbound_peers)
        self.rpc_host_edit.setText(self.config.rpc_host)
        self.rpc_port_spin.setValue(self.config.rpc_port)
        self.rpc_user_edit.setText(self.config.rpc_user)
        self.rpc_password_edit.setText(self.config.rpc_password)
        self.cookie_edit.setText(self.config.cookie_file)
        self.scan_start_spin.setValue(self.config.scan_start_height)
        self.scan_end_spin.setValue(self.config.scan_end_height)
        self.scan_batch_spin.setValue(self.config.scan_batch_size)
        self.min_payload_spin.setValue(self.config.minimum_payload_size)
        self.max_payload_spin.setValue(self.config.maximum_payload_size)
        self.generic_conf_spin.setValue(self.config.minimum_generic_confidence)
        self.catalog_unknown_check.setChecked(self.config.catalog_unknown_op_return)
        self.catalog_all_pushes_check.setChecked(self.config.catalog_all_data_pushes)
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(self.config.language)))
        self.theme_combo.setCurrentText(self.config.theme)
        self.window_width_spin.setValue(self.config.window_width)
        self.window_height_spin.setValue(self.config.window_height)
        self.workspace_edit.setText(self.config.workspace_root)
        self.preview_max_spin.setValue(self.config.preview_max_bytes)
        self.sidecar_check.setChecked(self.config.export_sidecar_json)
        self.confirm_bulk_check.setChecked(self.config.confirm_bulk_export)
        self.update_profile_labels()

    def save_settings(self) -> None:
        old_language = self.config.language
        self._capture_config()
        self.config.language = str(self.language_combo.currentData())
        self.config.theme = self.theme_combo.currentText()
        self.config.window_width = self.window_width_spin.value()
        self.config.window_height = self.window_height_spin.value()
        self.config.workspace_root = self.workspace_edit.text().strip()
        self.config.preview_max_bytes = self.preview_max_spin.value()
        self.config.export_sidecar_json = self.sidecar_check.isChecked()
        self.config.confirm_bulk_export = self.confirm_bulk_check.isChecked()
        self.config.save()
        self.apply_theme()
        self.refresh_dashboard(); self.refresh_catalog()
        message = "Settings saved."
        if old_language != self.config.language:
            message += " Restart the application to fully apply the new language file."
        QMessageBox.information(self, APP_NAME, message)

    def _capture_config(self) -> None:
        self.config.profile_id = self.current_profile().id
        self.config.node_executable = self.node_exe_edit.text().strip()
        self.config.node_datadir = self.node_datadir_edit.text().strip()
        self.config.node_extra_args = self.node_extra_args_edit.text().strip()
        self.config.disable_wallet = self.disable_wallet_check.isChecked()
        self.config.listen_for_inbound_peers = self.listen_check.isChecked()
        self.config.rpc_host = self.rpc_host_edit.text().strip() or "127.0.0.1"
        self.config.rpc_port = self.rpc_port_spin.value()
        self.config.rpc_user = self.rpc_user_edit.text()
        self.config.rpc_password = self.rpc_password_edit.text()
        self.config.cookie_file = self.cookie_edit.text().strip()
        self.config.scan_start_height = self.scan_start_spin.value()
        self.config.scan_end_height = self.scan_end_spin.value()
        self.config.scan_batch_size = self.scan_batch_spin.value()
        self.config.minimum_payload_size = self.min_payload_spin.value()
        self.config.maximum_payload_size = self.max_payload_spin.value()
        self.config.minimum_generic_confidence = self.generic_conf_spin.value()
        self.config.catalog_unknown_op_return = self.catalog_unknown_check.isChecked()
        self.config.catalog_all_data_pushes = self.catalog_all_pushes_check.isChecked()


    def apply_language(self) -> None:
        """Translate static widget text from its original English source text.

        Language changes are applied fully after restart, which avoids rebuilding
        active worker widgets while a scan or export is in progress.
        """
        if self.config.language == "en":
            return

        def translate_text(obj, getter: str, setter: str, property_name: str) -> None:
            if not hasattr(obj, getter) or not hasattr(obj, setter):
                return
            source = obj.property(property_name)
            if source is None:
                try:
                    source = getattr(obj, getter)()
                except TypeError:
                    return
                obj.setProperty(property_name, source)
            if source:
                getattr(obj, setter)(self.tr.t(str(source)))

        for widget in self.findChildren(QWidget):
            translate_text(widget, "text", "setText", "_source_text")
            translate_text(widget, "title", "setTitle", "_source_title")
            translate_text(widget, "placeholderText", "setPlaceholderText", "_source_placeholder")
            translate_text(widget, "toolTip", "setToolTip", "_source_tooltip")

        for row in range(self.nav.count()):
            item = self.nav.item(row)
            source = item.data(Qt.UserRole + 10)
            if source is None:
                source = item.text(); item.setData(Qt.UserRole + 10, source)
            item.setText(self.tr.t(str(source)))

        for combo in self.findChildren(QComboBox):
            for idx in range(combo.count()):
                source = combo.itemData(idx, Qt.UserRole + 10)
                if source is None:
                    source = combo.itemText(idx); combo.setItemData(idx, source, Qt.UserRole + 10)
                translated = self.tr.t(str(source))
                if translated != str(source):
                    combo.setItemText(idx, translated)

        for table in self.findChildren(QTableWidget):
            for col in range(table.columnCount()):
                item = table.horizontalHeaderItem(col)
                if item is None:
                    continue
                source = item.data(Qt.UserRole + 10)
                if source is None:
                    source = item.text(); item.setData(Qt.UserRole + 10, source)
                item.setText(self.tr.t(str(source)))

    def apply_theme(self) -> None:
        QApplication.instance().setStyleSheet(make_qss(self.config.theme))

    # ---------- Browsing ----------
    def browse_node_executable(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select node executable", self.node_exe_edit.text() or str(PROJECT_ROOT))
        if path:
            self.node_exe_edit.setText(path)

    def browse_node_datadir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select blockchain data directory", self.node_datadir_edit.text())
        if path:
            self.node_datadir_edit.setText(path)
            if not self.cookie_edit.text().strip():
                self.cookie_edit.setText(str(Path(path) / ".cookie"))

    def browse_cookie_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select RPC cookie", self.cookie_edit.text() or self.node_datadir_edit.text())
        if path:
            self.cookie_edit.setText(path)

    def browse_workspace(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select workspace root", self.workspace_edit.text())
        if path:
            self.workspace_edit.setText(path)

    # ---------- Profiles ----------
    def current_profile(self) -> ChainProfile:
        profile_id = self.profile_combo.currentData() or self.config.profile_id
        return self.profile_by_id[str(profile_id)]

    def on_profile_changed(self) -> None:
        profile = self.current_profile()
        old_default = self._last_profile_datadir
        current_dir = self.node_datadir_edit.text().strip() if hasattr(self, "node_datadir_edit") else ""
        if not current_dir or current_dir == old_default:
            new_dir = profile.expanded_windows_datadir()
            self.node_datadir_edit.setText(new_dir)
            self._last_profile_datadir = new_dir
        self.rpc_port_spin.setValue(profile.rpc_port)
        if self.node_datadir_edit.text() and not self.cookie_edit.text().strip():
            self.cookie_edit.setText(str(Path(self.node_datadir_edit.text()) / ".cookie"))
        self.update_profile_labels()
        self.refresh_dashboard(); self.refresh_catalog()

    def update_profile_labels(self) -> None:
        profile = self.current_profile()
        self.profile_details.setText(
            f"Family: {profile.family} | PoW: {profile.pow_algorithm} | RPC: {profile.rpc_port} | P2P: {profile.p2p_port} | Support: {profile.support_level}"
        )
        self.profile_notes.setText(profile.notes)

    def open_official_download(self) -> None:
        QDesktopServices.openUrl(QUrl(self.current_profile().official_url))

    # ---------- RPC / Node ----------
    def _rpc_settings(self) -> RpcSettings:
        cookie = self.cookie_edit.text().strip()
        if not cookie and self.node_datadir_edit.text().strip():
            cookie = str(Path(self.node_datadir_edit.text().strip()) / ".cookie")
        return RpcSettings(
            host=self.rpc_host_edit.text().strip() or "127.0.0.1",
            port=self.rpc_port_spin.value(),
            user=self.rpc_user_edit.text(),
            password=self.rpc_password_edit.text(),
            cookie_file=cookie,
            timeout=self.config.rpc_timeout_seconds,
        )

    def start_node(self) -> None:
        try:
            self._capture_config(); self.config.save()
            args = self.node_manager.start(
                self.node_exe_edit.text().strip(), self.node_datadir_edit.text().strip(), self.current_profile(),
                self.node_extra_args_edit.text().strip(), self.disable_wallet_check.isChecked(), self.listen_check.isChecked(),
            )
            self.node_command_preview.setPlainText(subprocess.list2cmdline(args))
            self._sync_started = time.monotonic(); self._sync_progress_rate.reset(); self._sync_block_rate.reset()
            self.sync_timer.start()
            self.sync_state_label.setText("Node starting; waiting for RPC cookie/interface…")
            QTimer.singleShot(2000, self.refresh_sync_status)
        except Exception as exc:
            QMessageBox.critical(self, "Node start failed", str(exc))

    def stop_node(self) -> None:
        try:
            RpcClient(self._rpc_settings()).call("stop")
            self.sync_state_label.setText("Clean shutdown requested")
            self.sync_timer.stop()
            self.progress_panel.set_idle("Node shutdown requested")
        except Exception as exc:
            if self.node_manager.is_running():
                QMessageBox.warning(self, "RPC stop failed", f"The process still appears active. RPC error: {exc}")
            else:
                QMessageBox.information(self, "Node", f"No managed node process is active. RPC response: {exc}")

    def test_rpc(self) -> None:
        try:
            client = RpcClient(self._rpc_settings())
            info = client.call("getblockchaininfo")
            network = client.call("getnetworkinfo")
            QMessageBox.information(self, "RPC connected", f"Chain: {info.get('chain')}\nBlocks: {info.get('blocks')}\nNode version: {network.get('subversion', network.get('version'))}")
            self.sync_timer.start(); self.refresh_sync_status()
        except Exception as exc:
            QMessageBox.critical(self, "RPC connection failed", str(exc))

    def refresh_sync_status(self) -> None:
        try:
            client = RpcClient(self._rpc_settings())
            info = client.call("getblockchaininfo")
            try:
                network = client.call("getnetworkinfo")
            except Exception:
                network = {}
            blocks = int(info.get("blocks", 0)); headers = int(info.get("headers", 0))
            progress = float(info.get("verificationprogress", 0.0))
            progress = max(0.0, min(1.0, progress))
            self._sync_progress_rate.add(progress)
            self._sync_block_rate.add(blocks)
            eta = self._sync_progress_rate.eta(progress, 1.0)
            block_rate = self._sync_block_rate.rate()
            elapsed = time.monotonic() - self._sync_started
            state = "Initial block download" if info.get("initialblockdownload", True) else "Synchronized"
            if info.get("pruned"):
                state += " — WARNING: pruning enabled"
            self.sync_state_label.setText(state)
            self.sync_height_label.setText(f"{blocks:,} / {headers:,}")
            self.sync_disk_label.setText(human_bytes(info.get("size_on_disk")))
            self.sync_rate_label.setText(f"{block_rate:.2f} blocks/s" if block_rate is not None else "Collecting samples…")
            self.sync_eta_label.setText(human_duration(eta))
            self.sync_peers_label.setText(str(network.get("connections", "—")))
            self.sync_overall_bar.setValue(int(progress * 10000)); self.sync_overall_bar.setFormat(f"{progress*100:.4f}%")
            header_fraction = blocks / headers if headers > 0 else 0.0
            self.sync_header_bar.setValue(int(max(0, min(1, header_fraction)) * 10000)); self.sync_header_bar.setFormat(f"{header_fraction*100:.2f}%")
            self.progress_panel.update_progress(
                task="Blockchain synchronization", status=state,
                current=progress, total=1.0,
                phase_current=blocks, phase_total=max(headers, blocks, 1),
                current_text=f"Height {blocks:,} / headers {headers:,} | {human_bytes(info.get('size_on_disk'))}",
                elapsed=elapsed, eta=eta, cancellable=True,
            )
            self._active_cancel = self.stop_node
            self.refresh_dashboard()
            if not info.get("initialblockdownload", True):
                self.progress_panel.set_idle("Local blockchain reports synchronized")
        except Exception as exc:
            self.node_manager.clear_if_stopped()
            self.sync_state_label.setText(f"RPC unavailable: {exc}")

    # ---------- Scan ----------
    def resume_scan_height(self) -> None:
        path = self.config.catalog_path(self.current_profile().id)
        if not path.exists():
            QMessageBox.information(self, "Resume", "No catalog scan state exists for this profile.")
            return
        catalog = Catalog(path)
        try:
            height = catalog.last_scanned_height(self.current_profile().id)
        finally:
            catalog.close()
        if height is None:
            QMessageBox.information(self, "Resume", "No completed scan batch is recorded.")
        else:
            self.scan_start_spin.setValue(height + 1)

    def start_scan(self) -> None:
        if self.scan_worker and self.scan_worker.isRunning():
            return
        self._capture_config(); self.config.save()
        options = ScanOptions(
            chain_id=self.current_profile().id,
            catalog_path=str(self.config.catalog_path(self.current_profile().id)),
            start_height=self.scan_start_spin.value(),
            end_height=self.scan_end_spin.value(),
            batch_size=self.scan_batch_spin.value(),
            minimum_payload_size=self.min_payload_spin.value(),
            maximum_payload_size=self.max_payload_spin.value(),
            catalog_unknown_op_return=self.catalog_unknown_check.isChecked(),
            catalog_all_data_pushes=self.catalog_all_pushes_check.isChecked(),
            minimum_generic_confidence=self.generic_conf_spin.value(),
            preview_max_bytes=self.preview_max_spin.value(),
            safe_text_mimes=tuple(self.config.safe_text_mimes),
        )
        self.scan_worker = ScanWorker(self._rpc_settings(), options)
        self.scan_worker.progress.connect(self.on_scan_progress)
        self.scan_worker.log.connect(self.append_scan_log)
        self.scan_worker.candidate_count.connect(lambda count: self.append_scan_log(f"Catalog candidates: {count:,}"))
        self.scan_worker.completed.connect(self.on_scan_completed)
        self.scan_worker.failed.connect(self.on_scan_failed)
        self.scan_worker.finished.connect(self._scan_thread_finished)
        self.scan_worker.start()
        self.start_scan_button.setEnabled(False); self.pause_scan_button.setEnabled(True); self.cancel_scan_button.setEnabled(True)
        self.pause_scan_button.setText("Pause")
        self.scan_status_label.setText("Starting local RPC scan…")
        self.append_scan_log(f"Started {self.current_profile().name} scan at height {options.start_height}.")
        self._active_cancel = self.cancel_scan

    def toggle_scan_pause(self) -> None:
        if not self.scan_worker:
            return
        if self.pause_scan_button.text() == "Pause":
            self.scan_worker.pause(); self.pause_scan_button.setText("Resume"); self.scan_status_label.setText("Paused")
        else:
            self.scan_worker.resume(); self.pause_scan_button.setText("Pause"); self.scan_status_label.setText("Running")

    def cancel_scan(self) -> None:
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.cancel(); self.scan_status_label.setText("Cancellation requested…")

    def on_scan_progress(self, data: dict[str, Any]) -> None:
        current = int(data["current"]); total = int(data["total"])
        fraction = current / total if total else 0
        self.scan_progress_bar.setValue(int(fraction * 10000)); self.scan_progress_bar.setFormat(f"{fraction*100:.2f}%")
        rate = data.get("rate")
        self.scan_status_label.setText(f"Scanning block {int(data['height']):,} of local tip {int(data['tip']):,}")
        self.scan_metrics_label.setText(
            f"{current:,}/{total:,} blocks | {rate:.2f} blocks/s" if rate else f"{current:,}/{total:,} blocks"
        )
        self.scan_metrics_label.setText(self.scan_metrics_label.text() + f" | candidates {int(data['found']):,} | ETA {human_duration(data.get('eta'))}")
        self.progress_panel.update_progress(
            task="Blockchain analysis", status="Scanning scripts and witness data",
            current=current, total=total,
            current_text=f"Block {int(data['height']):,} | candidates {int(data['found']):,}",
            elapsed=data.get("elapsed"), eta=data.get("eta"), cancellable=True,
        )

    def on_scan_completed(self, data: dict[str, Any]) -> None:
        state = "Cancelled" if data.get("cancelled") else "Completed"
        self.scan_status_label.setText(f"{state}: {data.get('processed', 0):,} blocks processed")
        self.append_scan_log(f"{state}. Processed {data.get('processed', 0):,}/{data.get('total', 0):,} blocks; catalog count {data.get('found', 0):,}; elapsed {human_duration(data.get('elapsed'))}.")
        self.progress_panel.set_idle(f"Analysis {state.lower()}")
        self.refresh_catalog(); self.refresh_dashboard()

    def on_scan_failed(self, message: str) -> None:
        self.scan_status_label.setText(f"Failed: {message}")
        self.append_scan_log(f"ERROR: {message}")
        self.progress_panel.set_idle("Analysis failed")
        QMessageBox.critical(self, "Analysis failed", message)

    def _scan_thread_finished(self) -> None:
        self.start_scan_button.setEnabled(True); self.pause_scan_button.setEnabled(False); self.cancel_scan_button.setEnabled(False)
        self.scan_worker = None
        self._active_cancel = None

    def append_scan_log(self, message: str) -> None:
        self.scan_log.appendPlainText(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {message}")

    # ---------- Catalog ----------
    def refresh_catalog(self) -> None:
        if not hasattr(self, "catalog_table"):
            return
        chain_id = self.current_profile().id
        path = self.config.catalog_path(chain_id)
        catalog = Catalog(path)
        try:
            rows = catalog.query(chain_id, self.catalog_search_edit.text().strip(), str(self.catalog_extension_filter.currentData() or ""))
            extensions = catalog.distinct_extensions(chain_id)
        finally:
            catalog.close()
        current_filter = self.catalog_extension_filter.currentData()
        self.catalog_extension_filter.blockSignals(True)
        self.catalog_extension_filter.clear(); self.catalog_extension_filter.addItem("All types", "")
        for ext in extensions:
            self.catalog_extension_filter.addItem(ext, ext)
        idx = self.catalog_extension_filter.findData(current_filter)
        self.catalog_extension_filter.setCurrentIndex(max(0, idx))
        self.catalog_extension_filter.blockSignals(False)
        self.bulk_type_combo.clear()
        for ext in extensions:
            self.bulk_type_combo.addItem(ext, ext)
        self.catalog_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            block_time = datetime.utcfromtimestamp(int(row["block_time"])).isoformat(sep=" ") if row["block_time"] else "—"
            values = [
                row["id"], row["block_height"], block_time, row["txid"], row["embedding_method"],
                row["detected_type"], human_bytes(row["payload_size"]), f"{row['entropy']:.3f}",
                f"{row['confidence']*100:.1f}%", row["location"],
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(Qt.UserRole, int(row["id"]))
                self.catalog_table.setItem(row_index, col, item)
        self.catalog_table.resizeColumnsToContents()
        self.candidate_meta.clear(); self.candidate_preview.clear()

    def _selected_candidate_id(self) -> int | None:
        row = self.catalog_table.currentRow()
        if row < 0:
            return None
        item = self.catalog_table.item(row, 0)
        return int(item.data(Qt.UserRole)) if item else None

    def show_selected_candidate(self) -> None:
        candidate_id = self._selected_candidate_id()
        if candidate_id is None:
            return
        catalog = Catalog(self.config.catalog_path(self.current_profile().id))
        try:
            row = catalog.get(candidate_id)
        finally:
            catalog.close()
        if row is None:
            return
        metadata = {key: row[key] for key in row.keys() if key not in {"payload", "preview_text"}}
        try:
            metadata["metadata_json"] = json.loads(metadata["metadata_json"])
        except Exception:
            pass
        self.candidate_meta.setPlainText(json.dumps(metadata, indent=2, ensure_ascii=False, default=str))
        self.candidate_preview.setPlainText(row["preview_text"] or "")

    def extract_selected(self) -> None:
        candidate_id = self._selected_candidate_id()
        if candidate_id is None:
            QMessageBox.information(self, "Extract", "Select a catalog row first.")
            return
        catalog = Catalog(self.config.catalog_path(self.current_profile().id))
        try:
            row = catalog.get(candidate_id)
        finally:
            catalog.close()
        if row is None:
            return
        default_name = f"{row['block_height']}_{str(row['txid'])[:16]}_{row['id']}{row['extension']}"
        destination, _ = QFileDialog.getSaveFileName(self, "Extract candidate", str(Path.home() / default_name))
        if not destination:
            return
        try:
            path = export_candidate(row, destination, self.config.export_sidecar_json)
            QMessageBox.information(self, "Extracted", f"Written to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Extraction failed", str(exc))

    def bulk_extract(self) -> None:
        extension = str(self.bulk_type_combo.currentData() or "")
        if not extension:
            QMessageBox.information(self, "Bulk extraction", "No strictly identified file type is available in the current catalog.")
            return
        target = QFileDialog.getExistingDirectory(self, f"Select target directory for {extension} files")
        if not target:
            return
        if self.config.confirm_bulk_export:
            answer = QMessageBox.warning(
                self, "Confirm bulk extraction",
                "Only catalog entries with confidence >=95% and a file signature at byte zero will be exported. "
                "The output can still contain unsafe or unlawful material. Continue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self.export_worker = BulkExportWorker(
            str(self.config.catalog_path(self.current_profile().id)), self.current_profile().id,
            extension, target, self.config.export_sidecar_json,
        )
        self.export_worker.progress.connect(self.on_export_progress)
        self.export_worker.completed.connect(self.on_export_completed)
        self.export_worker.failed.connect(self.on_export_failed)
        self.export_worker.finished.connect(self._export_thread_finished)
        self.export_worker.start()
        self._active_cancel = self.cancel_bulk_export

    def on_export_progress(self, data: dict[str, Any]) -> None:
        self.progress_panel.update_progress(
            task="Bulk extraction", status=f"Exporting {self.bulk_type_combo.currentData()}",
            current=data["current"], total=max(data["total"], 1), current_text=data.get("file", ""),
            elapsed=data.get("elapsed"), eta=data.get("eta"), cancellable=True,
        )

    def on_export_completed(self, data: dict[str, Any]) -> None:
        self.progress_panel.set_idle("Bulk extraction completed")
        QMessageBox.information(self, "Bulk extraction", f"Written {data.get('written', 0):,} of {data.get('total', 0):,} candidates.")

    def on_export_failed(self, message: str) -> None:
        self.progress_panel.set_idle("Bulk extraction failed")
        QMessageBox.critical(self, "Bulk extraction failed", message)

    def cancel_bulk_export(self) -> None:
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.cancel()

    def _export_thread_finished(self) -> None:
        self.export_worker = None; self._active_cancel = None

    # ---------- Summary and lifecycle ----------
    def refresh_dashboard(self) -> None:
        if not hasattr(self, "dashboard_chain"):
            return
        profile = self.current_profile()
        path = self.config.catalog_path(profile.id)
        count = 0
        if path.exists():
            catalog = Catalog(path)
            try:
                count = catalog.count(profile.id)
            finally:
                catalog.close()
        self.dashboard_chain.setText(f"{profile.name} ({profile.symbol}) — {profile.pow_algorithm}")
        self.dashboard_datadir.setText(self.node_datadir_edit.text().strip() or "Not selected")
        self.dashboard_catalog.setText(f"{path} ({human_bytes(path.stat().st_size) if path.exists() else 'new'})")
        self.dashboard_candidates.setText(f"{count:,}")
        self.dashboard_support.setText(f"{profile.support_level}: {profile.notes}")

    def cancel_active_operation(self) -> None:
        if self._active_cancel:
            self._active_cancel()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.scan_worker and self.scan_worker.isRunning():
            answer = QMessageBox.question(self, "Analysis running", "Cancel the analysis and close the application?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                event.ignore(); return
            self.scan_worker.cancel(); self.scan_worker.wait(5000)
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.cancel(); self.export_worker.wait(5000)
        self._capture_config()
        self.config.window_width = self.width(); self.config.window_height = self.height()
        self.config.save()
        event.accept()


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Local Forensic Tools")
    window = MainWindow()
    window.show()
    return app.exec()
