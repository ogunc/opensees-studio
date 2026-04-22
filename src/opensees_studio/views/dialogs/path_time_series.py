"""Add Path TimeSeries dialog — ground-motion import / manual entry.

Builds a :class:`PathTimeSeries` either from a PEER ``.at2``-style
file (auto-reads ``dt`` + ``npts`` from header) or from a plain text
number list where the user supplies ``dt``. A scale factor is applied
at runtime (e.g. g = 386.4 for records in g-units).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import PathTimeSeries
from opensees_studio.services.peer_record import (
    parse_peer_record,
    parse_plain_values,
)


class PathTimeSeriesDialog(QDialog):
    """Modal dialog: import or build a PathTimeSeries from a file."""

    def __init__(self, next_ts_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Path TimeSeries")
        self.resize(520, 420)
        self._next_id = next_ts_id
        self._values: list[float] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "<b>Path TimeSeries</b> — tabulated values sampled at a "
            "uniform time step. Used by UniformExcitation (ground "
            "motion) and by PlainLoadPattern scaled forces."
        ))

        form = QFormLayout()
        self._name_edit = QLineEdit("GroundMotion")
        form.addRow("Name:", self._name_edit)

        self._dt_spin = QDoubleSpinBox()
        self._dt_spin.setRange(1e-9, 100.0)
        self._dt_spin.setDecimals(6)
        self._dt_spin.setSingleStep(0.001)
        self._dt_spin.setValue(0.01)
        form.addRow("Δt (s):", self._dt_spin)

        self._factor_spin = QDoubleSpinBox()
        self._factor_spin.setRange(-1e12, 1e12)
        self._factor_spin.setDecimals(6)
        self._factor_spin.setSingleStep(1.0)
        self._factor_spin.setValue(386.4)     # default: convert g → in/s²
        self._factor_spin.setToolTip(
            "Multiplier applied to every value at runtime. Typical use: "
            "386.4 for ground motion in g → in/s² (US_IN_KIP), 9.81 for "
            "SI, 1.0 for data already in the project's unit system."
        )
        form.addRow("Factor:", self._factor_spin)
        root.addLayout(form)

        # ── Import controls ─────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._btn_peer = QPushButton("Import PEER .at2…")
        self._btn_plain = QPushButton("Import plain values…")
        self._btn_peer.clicked.connect(self._on_import_peer)
        self._btn_plain.clicked.connect(self._on_import_plain)
        btn_row.addWidget(self._btn_peer)
        btn_row.addWidget(self._btn_plain)
        root.addLayout(btn_row)

        self._status = QLabel(
            "<i>No data loaded — use one of the import buttons.</i>"
        )
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #666;")
        root.addWidget(self._status)

        # Preview area — first few values.
        self._preview = QLabel("")
        self._preview.setStyleSheet(
            "font-family: monospace; color: #333; background: #f0f0f0; padding: 6px;"
        )
        self._preview.setWordWrap(True)
        self._preview.setMinimumHeight(80)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignTop)
        root.addWidget(self._preview, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ── file-import slots ───────────────────────────────────────────
    def _on_import_peer(self) -> None:
        fname, _ = QFileDialog.getOpenFileName(
            self, "Import PEER record",
            "", "PEER records (*.at2 *.AT2);;All files (*)",
        )
        if not fname:
            return
        try:
            dt, npts, vals = parse_peer_record(fname)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "PEER import failed", str(exc))
            return
        self._values = vals
        self._dt_spin.setValue(dt)
        self._status.setText(
            f"Loaded <b>{len(vals)}</b> points from PEER record "
            f"(header claimed {npts}, Δt = {dt:g} s)."
        )
        self._refresh_preview()

    def _on_import_plain(self) -> None:
        fname, _ = QFileDialog.getOpenFileName(
            self, "Import plain values",
            "", "Text files (*.txt *.csv *.dat);;All files (*)",
        )
        if not fname:
            return
        try:
            vals = parse_plain_values(fname)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        self._values = vals
        self._status.setText(
            f"Loaded <b>{len(vals)}</b> values from plain-text file. "
            "Set Δt manually above."
        )
        self._refresh_preview()

    # ── preview ─────────────────────────────────────────────────────
    def _refresh_preview(self) -> None:
        if not self._values:
            self._preview.setText("")
            return
        head = "  ".join(f"{v:+.5g}" for v in self._values[:8])
        tail = "  ".join(f"{v:+.5g}" for v in self._values[-4:])
        peak = max(abs(v) for v in self._values)
        self._preview.setText(
            f"First 8: {head}\n"
            f"Last 4:  {tail}\n"
            f"Peak |value|: {peak:.6g}   Count: {len(self._values)}"
        )

    # ── result ──────────────────────────────────────────────────────
    def _on_accept(self) -> None:
        if not self._values:
            QMessageBox.warning(
                self, "No data", "Import a record first.",
            )
            return
        self.accept()

    def time_series(self) -> PathTimeSeries:
        """Return the constructed PathTimeSeries (call after accept)."""
        return PathTimeSeries(
            id=self._next_id,
            name=self._name_edit.text().strip() or "GroundMotion",
            dt=self._dt_spin.value(),
            factor=self._factor_spin.value(),
            values=list(self._values),
        )
