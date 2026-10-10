"""Response-spectrum results dock.

Two panels:
- Mass-participation table (per mode: T, f, Γ, M_eff, ratio, Sa(T))
- Spectrum curve (period vs Sa) with markers at each modal period
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
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

from opensees_studio.core import ResponseSpectrum, UnitConverter
from opensees_studio.services.results import ResponseSpectrumResults
from opensees_studio.views.plot_style import add_legend, axis_label, readable_plot


class ResponseSpectrumView(QWidget):
    """Dock: spectrum curve + per-mode contribution table."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._results: ResponseSpectrumResults | None = None
        self._spectrum: ResponseSpectrum | None = None
        self._converter = UnitConverter()
        self._build_ui()

    # ── public API ──────────────────────────────────────────────────
    def set_units(self, converter: UnitConverter) -> None:
        """Re-plot and re-fill the table in ``converter``'s display units."""
        self._converter = converter
        if self._results is not None:
            self.set_results(self._results, self._spectrum)

    def set_results(
        self,
        results: ResponseSpectrumResults | None,
        spectrum: ResponseSpectrum | None,
    ) -> None:
        self._results = results
        self._spectrum = spectrum
        self._plot.clear()
        self._table.setRowCount(0)
        if results is None:
            self._info.setText("No response-spectrum results loaded.")
            return

        # Spectral accelerations are accelerations: only the length unit differs,
        # so Sa converts with the length factor (and the axis says so).
        accel_unit = f"{self._converter.labels.length}/s²"
        self._plot.setLabel("left", axis_label("Sa", accel_unit))
        self._table.setHorizontalHeaderItem(6, QTableWidgetItem(f"Sa(T) [{accel_unit}]"))

        # ── Spectrum curve ──
        if spectrum is not None:
            import numpy as np

            # Dense interpolation so the spectrum shape reads clearly
            # even with few control points.
            p_arr = np.asarray(spectrum.periods)
            a_arr = np.asarray(spectrum.accelerations) * self._converter.length
            p_dense = np.linspace(p_arr[0], p_arr[-1], 300)
            a_dense = np.interp(p_dense, p_arr, a_arr)
            pen = pg.mkPen("#1f77b4", width=2)
            self._plot.plot(p_dense, a_dense, pen=pen, name="Sa(T)")
            # Original control points.
            self._plot.plot(
                list(spectrum.periods),
                list(a_arr),
                pen=None,
                symbol="s",
                symbolSize=7,
                symbolBrush="#1f77b4",
                symbolPen=None,
                name="Control pts",
            )

            # Modal-period markers — one red dot per mode, offset
            # vertically for duplicate T values so they don't overlap.
            seen_t: dict[float, int] = {}
            for m in results.modes:
                if m.angular_frequency <= 0.0:
                    continue
                sa = m.sa_at_period * self._converter.length
                t_key = round(m.period, 6)
                count = seen_t.get(t_key, 0)
                seen_t[t_key] = count + 1
                # Slight vertical jitter for duplicate periods
                y_offset = count * sa * 0.04
                self._plot.plot(
                    [m.period],
                    [sa + y_offset],
                    pen=None,
                    symbol="o",
                    symbolSize=12,
                    symbolBrush="#d62728",
                    symbolPen=pg.mkPen("#ffffff", width=1),
                    name=f"Mode {m.mode_number}" if count == 0 else None,
                )
                # Small text label right next to the marker.
                txt = pg.TextItem(
                    f"  M{m.mode_number}",
                    color="#d62728",
                    anchor=(0.0, 0.5),
                )
                txt.setPos(m.period, sa + y_offset)
                self._plot.addItem(txt)

        total_mass_ratio = sum(m.mass_ratio for m in results.modes)
        damping = (
            f" (damping {results.damping_ratio:g})" if results.damping_ratio is not None else ""
        )
        text = (
            f"Case '{results.case_name}' — "
            f"direction DOF {results.direction}, {results.combination} combination{damping}"
            f"{f', eigen solver {results.solver}' if results.solver else ''}. "
            f"Cumulative mass participation: {total_mass_ratio * 100:.1f}%"
        )
        for warning in results.warnings:
            text += f"<br><span style='color: #c0392b;'>Warning: {warning}</span>"
        self._info.setText(text)

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
                f"{m.sa_at_period * self._converter.length:.4g}",
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
        self._plot = readable_plot()
        self._plot.setLabel("left", axis_label("Sa", f"{self._converter.labels.length}/s²"))
        self._plot.setLabel("bottom", axis_label("Period", "s"))
        add_legend(self._plot)
        splitter.addWidget(self._plot)

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            [
                "Mode",
                "T (s)",
                "f (Hz)",
                "Γ",
                "M_eff",
                "Mass %",
                "Sa(T)",
            ]
        )
        # The Sa(T) header carries the display unit, refreshed by `set_results`.
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
