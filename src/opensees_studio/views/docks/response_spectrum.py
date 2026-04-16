"""Response-spectrum results dock.

Two panels:
- Mass-participation table (per mode: T, f, Γ, M_eff, ratio, Sa(T))
- Spectrum curve (period vs Sa) with markers at each modal period
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from opensees_studio.core import ResponseSpectrum
from opensees_studio.services.results import ResponseSpectrumResults


class ResponseSpectrumView(QWidget):
    """Dock: spectrum curve + per-mode contribution table."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def set_results(
        self, results: ResponseSpectrumResults | None,
        spectrum: ResponseSpectrum | None,
    ) -> None:
        self._plot.clear()
        self._table.setRowCount(0)
        if results is None:
            self._info.setText("No response-spectrum results loaded.")
            return

        # ── Spectrum curve ──
        if spectrum is not None:
            pen = pg.mkPen("#1f77b4", width=2)
            self._plot.plot(spectrum.periods, spectrum.accelerations, pen=pen,
                            name="Spectrum")
            # Mark each modal period with a scatter point + Sa value.
            sample_T = [m.period for m in results.modes if m.angular_frequency > 0]
            sample_Sa = [m.sa_at_period for m in results.modes if m.angular_frequency > 0]
            if sample_T:
                self._plot.plot(sample_T, sample_Sa,
                                pen=None, symbol="o",
                                symbolBrush="#d62728",
                                symbolPen=None, symbolSize=8,
                                name="Modal periods")

        total_mass_ratio = sum(m.mass_ratio for m in results.modes)
        self._info.setText(
            f"Case '{results.case_name}' — "
            f"direction DOF {results.direction}, {results.combination} combination. "
            f"Cumulative mass participation: {total_mass_ratio * 100:.1f}%",
        )

        # ── Mass participation table ──
        self._table.setRowCount(len(results.modes))
        for row, m in enumerate(results.modes):
            cells = [
                str(m.mode_number),
                f"{m.period:.4g}",
                f"{m.frequency:.4g}",
                f"{m.participation_factor:+.4g}",
                f"{m.effective_mass:.4g}",
                f"{m.mass_ratio * 100:.2f}",
                f"{m.sa_at_period:.4g}",
            ]
            for col, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, item)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self._info = QLabel("")
        self._info.setStyleSheet("color: #888;")
        root.addWidget(self._info)

        splitter = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(splitter, 1)

        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#1e1e1e")
        self._plot.setLabel("left", "Sa")
        self._plot.setLabel("bottom", "Period", units="s")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.addLegend(offset=(8, 8))
        splitter.addWidget(self._plot)

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels([
            "Mode", "T (s)", "f (Hz)", "Γ", "M_eff", "Mass %", "Sa(T)",
        ])
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch,
        )
        splitter.addWidget(self._table)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._hide_btn = QPushButton("Hide")
        self._hide_btn.clicked.connect(self.closed.emit)
        btn_row.addWidget(self._hide_btn)
        root.addLayout(btn_row)
