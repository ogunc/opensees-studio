"""Hysteresis plotter dock — X-Y plot of two transient series.

Common usage:
- Force vs displacement (energy dissipation loops)
- Moment vs rotation
- Two displacement DOFs against each other (orbit plots)

X is a node displacement DOF. Y is either another node displacement
DOF or the corresponding reaction force from an element local-force
record. Element forces are sourced via element_force_history.
"""

from __future__ import annotations

from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.services.results import TransientResults


class HysteresisView(QWidget):
    """X-Y plotter binding two transient series.

    UI: pick X-axis (node + DOF), pick Y-axis (node + DOF), click 'Plot'.
    """

    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._results: TransientResults | None = None
        self._curve: Any | None = None
        self._build_ui()

    def set_results(self, results: TransientResults | None) -> None:
        self._results = results
        self._clear_curve()
        if results is None:
            self._info.setText("No transient results loaded.")
        else:
            self._info.setText(
                f"Case '{results.case_name}': {results.n_steps} steps, dt={results.dt}",
            )

    def set_available_nodes(self, node_ids: list[int]) -> None:
        for picker in (self._x_node, self._y_node):
            picker.clear()
            for nid in node_ids:
                picker.addItem(str(nid), nid)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── X axis controls ──
        x_row = QHBoxLayout()
        x_row.addWidget(QLabel("X — Node:"))
        self._x_node = QComboBox()
        self._x_node.setMinimumWidth(80)
        x_row.addWidget(self._x_node)
        x_row.addWidget(QLabel("DOF:"))
        self._x_dof = QSpinBox()
        self._x_dof.setRange(1, 6)
        x_row.addWidget(self._x_dof)
        x_row.addStretch(1)
        root.addLayout(x_row)

        # ── Y axis controls ──
        y_row = QHBoxLayout()
        y_row.addWidget(QLabel("Y — Node:"))
        self._y_node = QComboBox()
        self._y_node.setMinimumWidth(80)
        y_row.addWidget(self._y_node)
        y_row.addWidget(QLabel("DOF:"))
        self._y_dof = QSpinBox()
        self._y_dof.setRange(1, 6)
        y_row.addWidget(self._y_dof)
        y_row.addStretch(1)
        root.addLayout(y_row)

        # ── Action row ──
        actions = QHBoxLayout()
        self._plot_btn = QPushButton("Plot")
        self._plot_btn.clicked.connect(self._on_plot)
        actions.addWidget(self._plot_btn)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._clear_curve)
        actions.addWidget(self._clear_btn)
        actions.addStretch(1)
        self._hide_btn = QPushButton("Hide")
        self._hide_btn.clicked.connect(self.closed.emit)
        actions.addWidget(self._hide_btn)
        root.addLayout(actions)

        self._info = QLabel("")
        self._info.setStyleSheet("color: #888;")
        root.addWidget(self._info)

        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#1e1e1e")
        self._plot.setLabel("left", "Y")
        self._plot.setLabel("bottom", "X")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        root.addWidget(self._plot, 1)

    # ── slots ───────────────────────────────────────────────────────
    def _on_plot(self) -> None:
        if self._results is None:
            return
        x = self._read_disp(self._x_node.currentData(), self._x_dof.value())
        y = self._read_disp(self._y_node.currentData(), self._y_dof.value())
        if x is None or y is None:
            return
        n = min(len(x), len(y))
        self._clear_curve()
        self._curve = self._plot.plot(
            x[:n], y[:n], pen=pg.mkPen("#1f77b4", width=2),
        )
        self._plot.setLabel(
            "bottom", f"N{self._x_node.currentData()}/D{self._x_dof.value()}",
        )
        self._plot.setLabel(
            "left", f"N{self._y_node.currentData()}/D{self._y_dof.value()}",
        )

    def _read_disp(self, nid_data, dof: int):
        if nid_data is None or self._results is None:
            return None
        nid = int(nid_data)
        try:
            h = self._results.node_disp_history(nid)
        except Exception as exc:
            self._info.setText(f"Failed to read node {nid}: {exc}")
            return None
        if dof - 1 >= h.shape[1]:
            self._info.setText(f"Node {nid} has no DOF {dof}.")
            return None
        return h[:, dof - 1]

    def _clear_curve(self) -> None:
        if self._curve is not None:
            try:
                self._plot.removeItem(self._curve)
            except Exception:
                pass
            self._curve = None
