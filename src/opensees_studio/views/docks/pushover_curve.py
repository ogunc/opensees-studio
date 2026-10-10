"""Pushover curve dock — base shear (or moment) vs control DOF.

Renders the monotonic pushover curve from a :class:`PushoverResults`
using pyqtgraph. Values are plotted in the project's *display* units:
the model keeps its own system (we never auto-convert what an engineer
typed — OpenSees itself is unit-agnostic), and the curve converts into
whatever system the display is set to, axis labels included. A kip-in
model shown in SI reads as "m" / "N".

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

from opensees_studio.core import UnitConverter, UnitSystem
from opensees_studio.services.results import PushoverResults
from opensees_studio.views.plot_style import axis_label, readable_plot

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
        display_units: UnitSystem | None = None,
    ) -> None:
        super().__init__(parent)
        self._units = units
        self._display_units = display_units
        self._ndf = ndf
        self._results: PushoverResults | None = None
        self._build_ui()

    # ── public API ──────────────────────────────────────────────────
    def set_units(self, converter: UnitConverter) -> None:
        """Re-plot in ``converter``'s display units (values and axis labels)."""
        self._units = converter.model
        self._display_units = converter.display
        if self._results is not None:
            self.set_results(self._results)

    @property
    def converter(self) -> UnitConverter:
        return UnitConverter(self._units, self._display_units)

    def set_results(self, results: PushoverResults | None) -> None:
        """Replace the currently-shown curve."""
        self._results = results
        self._plot.clear()
        if results is None:
            self._info.setText("No pushover results loaded.")
            return

        converter = self.converter
        labels = converter.labels
        rotational = _is_rotation_dof(results.control_dof, self._ndf)
        # The recorded control value is a displacement (translation DOF) or a
        # rotation (rotational DOF, shown as curvature); only the length part of
        # either converts, and a rotation has none. The effort converts as a
        # moment when the control is rotational and as a force otherwise.
        x_factor = 1.0 if rotational else converter.length
        y_factor = converter.moment if rotational else converter.force
        x = np.asarray(results.control_disp, dtype=float) * x_factor
        y = np.asarray(results.base_shear, dtype=float) * y_factor

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
            x,
            y,
            pen=pen,
            symbol="o",
            symbolSize=4,
            symbolBrush="#1f77b4",
            symbolPen=None,
        )

        # ── Elastic reference line (initial stiffness) ──────────────
        if len(x) >= 5:
            slope = float(np.polyfit(x[:5], y[:5], 1)[0])
            x_ref = np.array([0.0, x[4]])
            y_ref = slope * x_ref
            self._plot.plot(
                x_ref,
                y_ref,
                pen=pg.mkPen("#888888", width=1, style=pg.QtCore.Qt.PenStyle.DashLine),
            )

        # ── Yield-point marker ──────────────────────────────────────
        yi = _find_yield_idx(x, y)
        if yi is not None:
            self._plot.plot(
                [x[yi]],
                [y[yi]],
                pen=None,
                symbol="star",
                symbolSize=14,
                symbolBrush="#ff7f0e",
                symbolPen=pg.mkPen("#ff7f0e"),
            )
            noun = "κ" if rotational else "d"
            effort = "M" if rotational else "V"
            yield_txt = f"  ~yield at {noun}={x[yi]:.4g} {x_unit}, {effort}={y[yi]:.4g} {y_unit}"
        else:
            yield_txt = ""

        self._plot.setLabel("bottom", axis_label(x_title, x_unit))
        self._plot.setLabel("left", axis_label(y_title, y_unit))
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
        self._plot = readable_plot()
        self._plot.setLabel("left", "Base shear")
        self._plot.setLabel("bottom", "Displacement")
        root.addWidget(self._plot, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._hide_btn = QPushButton("Hide")
        self._hide_btn.clicked.connect(self.closed.emit)
        btn_row.addWidget(self._hide_btn)
        root.addLayout(btn_row)
