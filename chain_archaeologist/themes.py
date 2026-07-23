from __future__ import annotations

import json
from pathlib import Path

from .config import PROJECT_ROOT


def load_theme(name: str) -> dict[str, str]:
    path = PROJECT_ROOT / "assets" / "themes" / f"{name}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "window": "#202124", "panel": "#292a2d", "panel_alt": "#33353a",
            "text": "#f1f3f4", "muted": "#aeb4bc", "accent": "#6ea8fe",
            "border": "#45474d", "danger": "#ff6b6b", "success": "#69db7c",
            "selection": "#3f5f8f",
        }


def make_qss(name: str) -> str:
    c = load_theme(name)
    return f"""
    QWidget {{ background: {c['window']}; color: {c['text']}; font-size: 10pt; }}
    QMainWindow, QDialog {{ background: {c['window']}; }}
    QFrame#Card, QGroupBox {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; }}
    QGroupBox {{ margin-top: 12px; padding: 10px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 5px; color: {c['accent']}; }}
    QPushButton {{ background: {c['panel_alt']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 7px 12px; }}
    QPushButton:hover {{ border-color: {c['accent']}; }}
    QPushButton:pressed {{ background: {c['selection']}; }}
    QPushButton:disabled {{ color: {c['muted']}; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit, QTableWidget, QListWidget {{
        background: {c['panel_alt']}; border: 1px solid {c['border']}; border-radius: 5px; padding: 5px;
    }}
    QTableWidget {{ gridline-color: {c['border']}; alternate-background-color: {c['panel']}; }}
    QHeaderView::section {{ background: {c['panel']}; color: {c['text']}; padding: 6px; border: 0; border-right: 1px solid {c['border']}; }}
    QListWidget::item {{ padding: 10px; border-radius: 5px; }}
    QListWidget::item:selected {{ background: {c['selection']}; }}
    QProgressBar {{ background: {c['panel_alt']}; border: 1px solid {c['border']}; border-radius: 5px; text-align: center; min-height: 18px; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 6px; }}
    QTabBar::tab {{ background: {c['panel']}; padding: 8px 14px; }}
    QTabBar::tab:selected {{ background: {c['selection']}; }}
    QToolTip {{ background: {c['panel_alt']}; color: {c['text']}; border: 1px solid {c['accent']}; }}
    QLabel#Muted {{ color: {c['muted']}; }}
    QLabel#Danger {{ color: {c['danger']}; }}
    QLabel#Success {{ color: {c['success']}; }}
    QScrollBar:vertical {{ background: {c['panel']}; width: 14px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; min-height: 24px; border-radius: 6px; }}
    QScrollBar:horizontal {{ background: {c['panel']}; height: 14px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {c['border']}; min-width: 24px; border-radius: 6px; }}
    """
