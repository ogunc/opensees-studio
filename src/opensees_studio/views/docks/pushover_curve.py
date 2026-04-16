"""Pushover curve dock — base shear vs control displacement.

Renders the monotonic pushover curve from a :class:`PushoverResults`
using pyqtgraph. Single trace; exports PNG via pyqtgraph's right-click
context menu.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.services.results import PushoverResults


class PushoverCurveView(QWidget):
    """Dock contents: curve + metadata + hide button."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def set_results(self, results: PushoverResults | None) -> None:
        """Replace the currently-shown curve."""
        self._plot.clear()
        if results is None:
            self._info.setText("No pushover results loaded.")
            return

        # Plot with markers at every step so users can see how finely
        # the solver stepped through softening/collapse regions.
        pen = pg.mkPen("#1f77b4", width=2)
        self._plot.plot(
            results.control_disp, results.base_shear,
            pen=pen, symbol="o", symbolSize=4,
            symbolBrush="#1f77b4", symbolPen=None,
        )
        self._plot.setLabel(
            "bottom",
            f"Displacement at N{results.control_node}, DOF {results.control_dof}",
        )
        self._plot.setLabel("left", "Base shear")
        self._info.setText(
            f"Case '{results.case_name}' — {results.n_steps} steps, "
            f"max disp = {results.control_disp.max():.4g}, "
            f"peak base shear = {abs(results.base_shear).max():.4g}",
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        self._info = QLabel("")
        self._info.setStyleSheet("color: #888;")
        root.addWidget(self._info)

        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#1e1e1e")
        self._plot.setLabel("left", "Base shear")
        self._plot.setLabel("bottom", "Displacement")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        root.addWidget(self._plot, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._hide_btn = QPushButton("Hide")
        self._hide_btn.clicked.connect(self.closed.emit)
        btn_row.addWidget(self._hide_btn)
        root.addLayout(btn_row)
