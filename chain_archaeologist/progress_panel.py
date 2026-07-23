from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QProgressBar, QPushButton, QWidget
)

from .util import human_duration


class ProgressPanel(QFrame):
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QGridLayout(self)
        self.task_label = QLabel("Idle")
        self.status_label = QLabel("No active operation")
        self.current_label = QLabel("—")
        self.overall = QProgressBar()
        self.phase = QProgressBar()
        self.elapsed_label = QLabel("Elapsed: —")
        self.eta_label = QLabel("ETA: —")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_requested)
        layout.addWidget(QLabel("Task"), 0, 0)
        layout.addWidget(self.task_label, 0, 1)
        layout.addWidget(self.status_label, 0, 2, 1, 2)
        layout.addWidget(QLabel("Overall"), 1, 0)
        layout.addWidget(self.overall, 1, 1, 1, 3)
        layout.addWidget(QLabel("Current phase"), 2, 0)
        layout.addWidget(self.phase, 2, 1, 1, 3)
        layout.addWidget(self.current_label, 3, 0, 1, 2)
        layout.addWidget(self.elapsed_label, 3, 2)
        layout.addWidget(self.eta_label, 3, 3)
        layout.addWidget(self.cancel_button, 0, 4, 4, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)
        self.set_idle()

    def set_idle(self, message: str = "No active operation") -> None:
        self.task_label.setText("Idle")
        self.status_label.setText(message)
        self.current_label.setText("—")
        self.overall.setRange(0, 100)
        self.overall.setValue(0)
        self.phase.setRange(0, 100)
        self.phase.setValue(0)
        self.elapsed_label.setText("Elapsed: —")
        self.eta_label.setText("ETA: —")
        self.cancel_button.setEnabled(False)

    def update_progress(
        self,
        task: str,
        status: str,
        current: int | float,
        total: int | float,
        phase_current: int | float | None = None,
        phase_total: int | float | None = None,
        current_text: str = "",
        elapsed: float | None = None,
        eta: float | None = None,
        cancellable: bool = True,
    ) -> None:
        self.task_label.setText(task)
        self.status_label.setText(status)
        self._set_bar(self.overall, current, total)
        self._set_bar(self.phase, phase_current if phase_current is not None else current,
                      phase_total if phase_total is not None else total)
        self.current_label.setText(current_text or f"{current} / {total}")
        self.elapsed_label.setText(f"Elapsed: {human_duration(elapsed)}")
        self.eta_label.setText(f"ETA (estimate): {human_duration(eta)}")
        self.cancel_button.setEnabled(cancellable)

    @staticmethod
    def _set_bar(bar: QProgressBar, current: int | float, total: int | float) -> None:
        if total <= 0:
            bar.setRange(0, 0)
            return
        bar.setRange(0, 10000)
        value = max(0, min(10000, int(float(current) / float(total) * 10000)))
        bar.setValue(value)
        bar.setFormat(f"{value / 100:.2f}%")
