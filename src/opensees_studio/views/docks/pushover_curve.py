"""Pushover curve dock — base shear vs control displacement.

Renders the monotonic pushover curve from a :class:`PushoverResults`
using pyqtgraph. Single trace; exports PNG via pyqtgraph's right-click
context menu.
"""

from __future__ import annotations

import numpy as np
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


def _find_yield_idx(disp: np.ndarray, shear: np.ndarray) -> int | None:
    """Return index where tangent stiffness first drops below 30% of initial.

    Used for annotating the approximate yield point on the pushover curve.
    Returns None if fewer than 10 steps or the stiffness never drops that far.
    """
    if len(disp) < 10:
        return None
    dd = np.diff(disp)
    dv = np.diff(shear)
    # Guard against zero increments.
    safe = dd != 0
    tangent = np.where(safe, dv / np.where(safe, dd, 1.0), np.nan)
    k_init = float(np.nanmean(tangent[:5]))
    if k_init <= 0:
        return None
    for i, k in enumerate(tangent):
        if not np.isnan(k) and k < 0.30 * k_init:
            return i
    return None


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

        # Display in kN and cm for readability.
        d_cm = results.control_disp * 100.0       # m → cm
        v_kN = results.base_shear / 1_000.0       # N → kN

        pen = pg.mkPen("#1f77b4", width=2)
        self._plot.plot(
            d_cm, v_kN,
            pen=pen, symbol="o", symbolSize=4,
            symbolBrush="#1f77b4", symbolPen=None,
        )

        # ── Elastic reference line (initial stiffness) ──────────────
        if len(d_cm) >= 5:
            k_init_kN_cm = float(
                np.polyfit(d_cm[:5], v_kN[:5], 1)[0]
            )
            d_ref = np.array([0.0, d_cm[4]])
            v_ref = k_init_kN_cm * d_ref
            self._plot.plot(
                d_ref, v_ref,
                pen=pg.mkPen("#888888", width=1, style=pg.QtCore.Qt.PenStyle.DashLine),
            )

        # ── Yield-point marker ──────────────────────────────────────
        yi = _find_yield_idx(results.control_disp, results.base_shear)
        if yi is not None:
            self._plot.plot(
                [d_cm[yi]], [v_kN[yi]],
                pen=None, symbol="star", symbolSize=14,
                symbolBrush="#ff7f0e", symbolPen=pg.mkPen("#ff7f0e"),
            )
            yield_txt = (
                f"  ~yield at d={d_cm[yi]:.2f} cm, V={v_kN[yi]:.1f} kN"
            )
        else:
            yield_txt = ""

        self._plot.setLabel("bottom",
            f"Displacement at N{results.control_node}, "
            f"DOF {results.control_dof} (cm)")
        self._plot.setLabel("left", "Base shear (kN)")
        self._info.setText(
            f"Case '{results.case_name}' — {results.n_steps} steps"
            f"{yield_txt}   "
            f"peak V = {abs(v_kN).max():.1f} kN  "
            f"at d = {d_cm[int(np.argmax(abs(v_kN)))]:.2f} cm",
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        self._info = QLabel("")
        self._info.setStyleSheet("color: #888;")
        root.addWidget(self._info)

        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#1e1e1e")
        self._plot.setLabel("left", "Base shear (kN)")
        self._plot.setLabel("bottom", "Displacement (cm)")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        root.addWidget(self._plot, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._hide_btn = QPushButton("Hide")
        self._hide_btn.clicked.connect(self.closed.emit)
        btn_row.addWidget(self._hide_btn)
        root.addLayout(btn_row)
