"""Performance monitor: opt-in timings, counters, memory and cProfile.

The dialog reads the global :data:`~opensees_studio.diagnostics.performance.perf`
monitor. It can enable profiling at runtime, so a user can work normally and
only pay the instrumentation cost while investigating a slow model.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio import __version__
from opensees_studio.diagnostics.performance import perf
from opensees_studio.views.screen_fit import FittedDialog


class PerformanceDialog(FittedDialog):
    """Live view of the performance monitor (non-modal)."""

    _HEADERS = ("Stage", "Last ms", "Total ms", "N", "p95 ms", "Max ms")

    def __init__(self, vm: Any = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OpenSees Studio — Performance monitor")
        self.resize(940, 620)
        self._vm = vm
        self._last_profile_generation = perf.profile_generation
        self._build_ui()
        self._refresh()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        outer.addWidget(self._summary)

        controls = QHBoxLayout()
        self._enable_btn = QPushButton("Enable profiling")
        self._enable_btn.clicked.connect(self._on_enable)
        controls.addWidget(self._enable_btn)
        self._profile_btn = QPushButton("Profile next action")
        self._profile_btn.clicked.connect(self._on_profile_next)
        controls.addWidget(self._profile_btn)
        controls.addStretch(1)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._refresh)
        controls.addWidget(self._refresh_btn)
        self._reset_btn = QPushButton("Reset")
        self._reset_btn.clicked.connect(self._on_reset)
        controls.addWidget(self._reset_btn)
        self._save_btn = QPushButton("Save JSON…")
        self._save_btn.clicked.connect(self._on_save)
        controls.addWidget(self._save_btn)
        self._copy_btn = QPushButton("Copy JSON")
        self._copy_btn.clicked.connect(self._on_copy)
        controls.addWidget(self._copy_btn)
        outer.addLayout(controls)

        self._table = QTableWidget(0, len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self._table, stretch=1)

        self._gauge_label = QLabel()
        self._gauge_label.setWordWrap(True)
        outer.addWidget(self._gauge_label)

        outer.addWidget(QLabel("<b>Last cProfile</b> (Profile next action, then do the operation)"))
        self._profile_view = QPlainTextEdit()
        self._profile_view.setReadOnly(True)
        self._profile_view.setMaximumHeight(190)
        self._profile_view.setPlaceholderText(
            "Presiona «Profile next action» y realiza la operación que quieras medir."
        )
        outer.addWidget(self._profile_view)

        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        outer.addLayout(row)

    # ── refresh ────────────────────────────────────────────────────────
    def _refresh(self) -> None:
        snapshot = perf.snapshot()
        enabled = bool(snapshot.get("enabled"))
        self._enable_btn.setEnabled(not enabled)
        self._enable_btn.setText("Profiling enabled" if enabled else "Enable profiling")
        self._profile_btn.setEnabled(enabled)

        model = ""
        project = getattr(self._vm, "project", None)
        if project is not None:
            model = (
                f" · {len(project.nodes)} nodes · {len(project.elements)} elements"
                f" · {len(project.load_patterns)} patterns"
            )
        memory = snapshot.get("memory", {})
        memory_text = ""
        if memory:
            memory_text = " · " + ", ".join(f"{key}: {value}" for key, value in memory.items())
        self._summary.setText(
            f"<b>OpenSees Studio {__version__}</b> · profiling "
            f"{'enabled' if enabled else 'disabled'}{model}{memory_text}"
        )

        metrics = snapshot.get("metrics", {})
        rows = sorted(metrics.items(), key=lambda item: item[1].get("total_ms", 0.0), reverse=True)
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for row, (name, values) in enumerate(rows):
            cells = (
                name,
                f"{values.get('last_ms', 0.0):.2f}",
                f"{values.get('total_ms', 0.0):.2f}",
                str(values.get("count", 0)),
                f"{values.get('p95_ms', 0.0):.2f}",
                f"{values.get('max_ms', 0.0):.2f}",
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self._table.setItem(row, column, item)
        self._table.setSortingEnabled(True)

        counters = snapshot.get("counters", {})
        gauges = snapshot.get("gauges", {})
        parts = []
        if counters:
            parts.append(
                "Counters: " + ", ".join(f"{key}={value:g}" for key, value in counters.items())
            )
        if gauges:
            parts.append(
                "Gauges: " + ", ".join(f"{key}={value:g}" for key, value in gauges.items())
            )
        stalls = [event for event in snapshot.get("events", []) if event.get("name") == "ui.stall"]
        if stalls:
            worst = max(stalls, key=lambda event: float(event.get("duration_ms", 0.0)))
            parts.append(
                f"UI stalls: {len(stalls)} (worst {float(worst.get('duration_ms', 0.0)):.0f} ms)"
            )
        self._gauge_label.setText(" · ".join(parts))

        if perf.profile_generation != self._last_profile_generation:
            self._last_profile_generation = perf.profile_generation
            self._profile_view.setPlainText(perf.last_profile_text())
        if not enabled and not self._profile_view.toPlainText():
            self._profile_view.setPlaceholderText(
                "El diagnóstico está apagado. Actívalo con «Enable profiling» o "
                "arranca con --profile / OPENSEES_STUDIO_PERF=1."
            )

    # ── actions ────────────────────────────────────────────────────────
    def _on_enable(self) -> None:
        perf.enable()
        self._refresh()

    def _on_reset(self) -> None:
        perf.reset()
        self._last_profile_generation = perf.profile_generation
        self._profile_view.clear()
        self._refresh()

    def _on_profile_next(self) -> None:
        perf.request_profile_next()
        self._profile_view.setPlainText(
            "Perfilando la próxima operación… Realiza ahora la acción que quieras medir."
        )

    def _on_copy(self) -> None:
        QApplication.clipboard().setText(perf.to_json())

    def _on_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save performance report",
            "performance.json",
            "JSON (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            written = perf.write_json(path)
        except OSError as exc:
            QMessageBox.critical(self, "Could not save the report", str(exc))
            return
        self._summary.setText(f"Report written to {written}")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._timer.stop()
        super().closeEvent(event)
