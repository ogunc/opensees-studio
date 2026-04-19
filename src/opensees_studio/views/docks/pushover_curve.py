"""Pushover curve dock — base shear (or moment) vs control DOF.

Renders the monotonic pushover curve from a :class:`PushoverResults`
using pyqtgraph. Values are plotted in the model's native units (we
never auto-convert — OpenSees itself is unit-agnostic); axis labels
are driven by the project's :class:`UnitSystem` setting so a kip-in
model reads as "kip" / "in" and an SI-m model reads as "N" / "m".

For a Moment-Curvature analysis (control DOF = rotation, e.g. DOF 3
in a 2D/3 model) the X-axis switches to curvature and Y-axis to
moment automatically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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

from opensees_studio.core import UnitLabels, UnitSystem, labels_for
from opensees_studio.services.results import PushoverResults

if TYPE_CHECKING:
    pass


# DOFs that mean rotation in the OpenSees convention (1-indexed):
#   2D/3 model: 1=Ux, 2=Uy, 3=Rz
#   3D/6 model: 1=Ux, 2=Uy, 3=Uz, 4=Rx, 5=Ry, 6=Rz
# Rotation DOFs are 3 (when ndf=3) or 4/5/6 (when ndf=6).
def _is_rotation_dof(dof: int, ndf: int) -> bool:
    if ndf == 3:
        return dof == 3
    return 4 <= dof <= 6


def _find_yield_idx(disp: np.ndarray, shear: np.ndarray) -> int | None:
    """Return index where tangent stiffness first drops below 30% of initial."""
    if len(disp) < 10:
        return None
    dd = np.diff(disp)
    dv = np.diff(shear)
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

    def __init__(
        self,
        units: UnitSystem = UnitSystem.SI_M_N,
        ndf: int = 6,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._units = units
        self._ndf = ndf
        self._build_ui()

    def set_results(self, results: PushoverResults | None) -> None:
        """Replace the currently-shown curve."""
        self._plot.clear()
        if results is None:
            self._info.setText("No pushover results loaded.")
            return

        labels = labels_for(self._units)
        rotational = _is_rotation_dof(results.control_dof, self._ndf)
        x = np.asarray(results.control_disp, dtype=float)
        y = np.asarray(results.base_shear, dtype=float)

        # Axis labels depend on what's being driven:
        # - translation DOF → displacement (length) vs base shear (force)
        # - rotation DOF    → curvature (1/length) vs moment (force·length)
        if rotational:
            x_unit = labels.curvature
            y_unit = labels.moment
            x_title = f"Curvature at N{results.control_node}, DOF {results.control_dof}"
            y_title = "Moment"
        else:
            x_unit = labels.length
            y_unit = labels.force
            x_title = f"Displacement at N{results.control_node}, DOF {results.control_dof}"
            y_title = "Base shear"

        pen = pg.mkPen("#1f77b4", width=2)
        self._plot.plot(
            x, y,
            pen=pen, symbol="o", symbolSize=4,
            symbolBrush="#1f77b4", symbolPen=None,
        )

        # ── Elastic reference line (initial stiffness) ──────────────
        if len(x) >= 5:
            slope = float(np.polyfit(x[:5], y[:5], 1)[0])
            x_ref = np.array([0.0, x[4]])
            y_ref = slope * x_ref
            self._plot.plot(
                x_ref, y_ref,
                pen=pg.mkPen("#888888", width=1,
                              style=pg.QtCore.Qt.PenStyle.DashLine),
            )

        # ── Yield-point marker ──────────────────────────────────────
        yi = _find_yield_idx(x, y)
        if yi is not None:
            self._plot.plot(
                [x[yi]], [y[yi]],
                pen=None, symbol="star", symbolSize=14,
                symbolBrush="#ff7f0e", symbolPen=pg.mkPen("#ff7f0e"),
            )
            noun = "κ" if rotational else "d"
            effort = "M" if rotational else "V"
            yield_txt = (
                f"  ~yield at {noun}={x[yi]:.4g} {x_unit}, "
                f"{effort}={y[yi]:.4g} {y_unit}"
            )
        else:
            yield_txt = ""

        self._plot.setLabel("bottom", f"{x_title} ({x_unit})")
        self._plot.setLabel("left", f"{y_title} ({y_unit})")
        peak_idx = int(np.argmax(np.abs(y)))
        effort_noun = "M" if rotational else "V"
        x_noun = "κ" if rotational else "d"
        self._info.setText(
            f"Case '{results.case_name}' — {results.n_steps} steps"
            f"{yield_txt}   "
            f"peak {effort_noun} = {abs(y).max():.4g} {y_unit}  "
            f"at {x_noun} = {x[peak_idx]:.4g} {x_unit}",
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
