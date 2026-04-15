"""Hysteresis plotter dock — X-Y plot of two transient series.

X axis is always a node displacement DOF.
Y axis is one of:
- Another node displacement DOF (orbit plot)
- A node velocity DOF
- A node acceleration DOF
- An element local force component (force-displacement loops)

Element local-force convention (3D beam, 12 components per row):
    [N1, Vy1, Vz1, T1, My1, Mz1, N2, Vy2, Vz2, T2, My2, Mz2]
    end-i = first 6, end-j = last 6.
For 2D it's [N1, Vy1, Mz1, N2, Vy2, Mz2].
"""

from __future__ import annotations

from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.services.results import TransientResults

# Y-axis source kinds the user can pick.
_Y_KINDS = [
    ("Displacement (node)", "node_disp"),
    ("Velocity (node)", "node_vel"),
    ("Acceleration (node)", "node_accel"),
    ("Element force (local)", "element_force"),
]


class HysteresisView(QWidget):
    """X-Y plotter binding two transient series."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._results: TransientResults | None = None
        self._curve: Any | None = None
        self._build_ui()

    # ── public API ──────────────────────────────────────────────────
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

    def set_available_elements(self, element_ids: list[int]) -> None:
        self._y_element.clear()
        for eid in element_ids:
            self._y_element.addItem(str(eid), eid)

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        grid = QGridLayout()
        grid.addWidget(QLabel("<b>X axis</b>"), 0, 0, 1, 4)
        grid.addWidget(QLabel("Node:"), 1, 0)
        self._x_node = QComboBox()
        self._x_node.setMinimumWidth(80)
        grid.addWidget(self._x_node, 1, 1)
        grid.addWidget(QLabel("DOF:"), 1, 2)
        self._x_dof = QSpinBox()
        self._x_dof.setRange(1, 6)
        grid.addWidget(self._x_dof, 1, 3)

        grid.addWidget(QLabel("<b>Y axis</b>"), 2, 0, 1, 4)
        grid.addWidget(QLabel("Kind:"), 3, 0)
        self._y_kind = QComboBox()
        for label, code in _Y_KINDS:
            self._y_kind.addItem(label, code)
        self._y_kind.currentIndexChanged.connect(self._on_y_kind_changed)
        grid.addWidget(self._y_kind, 3, 1, 1, 3)

        # Node-based Y controls
        self._y_node_label = QLabel("Node:")
        grid.addWidget(self._y_node_label, 4, 0)
        self._y_node = QComboBox()
        self._y_node.setMinimumWidth(80)
        grid.addWidget(self._y_node, 4, 1)
        self._y_dof_label = QLabel("DOF:")
        grid.addWidget(self._y_dof_label, 4, 2)
        self._y_dof = QSpinBox()
        self._y_dof.setRange(1, 6)
        grid.addWidget(self._y_dof, 4, 3)

        # Element-based Y controls
        self._y_element_label = QLabel("Element:")
        grid.addWidget(self._y_element_label, 5, 0)
        self._y_element = QComboBox()
        self._y_element.setMinimumWidth(80)
        grid.addWidget(self._y_element, 5, 1)
        self._y_comp_label = QLabel("Component:")
        grid.addWidget(self._y_comp_label, 5, 2)
        self._y_component = QComboBox()
        for comp in ("N1", "Vy1", "Vz1", "T1", "My1", "Mz1",
                     "N2", "Vy2", "Vz2", "T2", "My2", "Mz2"):
            self._y_component.addItem(comp, comp)
        grid.addWidget(self._y_component, 5, 3)

        root.addLayout(grid)

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

        self._on_y_kind_changed(0)

    # ── slots ───────────────────────────────────────────────────────
    def _on_y_kind_changed(self, _idx: int) -> None:
        kind = self._y_kind.currentData()
        is_element = (kind == "element_force")
        for w in (self._y_node, self._y_dof, self._y_node_label, self._y_dof_label):
            w.setVisible(not is_element)
        for w in (self._y_element, self._y_component,
                  self._y_element_label, self._y_comp_label):
            w.setVisible(is_element)

    def _on_plot(self) -> None:
        if self._results is None:
            return
        x = self._read_x()
        y = self._read_y()
        if x is None or y is None:
            return
        n = min(len(x), len(y))
        self._clear_curve()
        self._curve = self._plot.plot(
            x[:n], y[:n], pen=pg.mkPen("#1f77b4", width=2),
        )
        self._plot.setLabel(
            "bottom", f"N{self._x_node.currentData()} DOF {self._x_dof.value()} disp",
        )
        self._plot.setLabel("left", self._y_label())

    # ── data accessors ──────────────────────────────────────────────
    def _read_x(self):
        nid_data = self._x_node.currentData()
        dof = self._x_dof.value()
        if nid_data is None or self._results is None:
            return None
        try:
            h = self._results.node_disp_history(int(nid_data))
        except Exception as exc:
            self._info.setText(f"Failed to read X node {nid_data}: {exc}")
            return None
        if dof - 1 >= h.shape[1]:
            self._info.setText(f"X node has no DOF {dof}.")
            return None
        return h[:, dof - 1]

    def _read_y(self):
        if self._results is None:
            return None
        kind = self._y_kind.currentData()
        if kind == "element_force":
            return self._read_element_force()
        accessor_name = {
            "node_disp": "node_disp_history",
            "node_vel": "node_vel_history",
            "node_accel": "node_accel_history",
        }.get(kind)
        if accessor_name is None:
            return None
        nid_data = self._y_node.currentData()
        dof = self._y_dof.value()
        if nid_data is None:
            return None
        try:
            h = getattr(self._results, accessor_name)(int(nid_data))
        except Exception as exc:
            self._info.setText(f"Failed to read Y node {nid_data}: {exc}")
            return None
        if dof - 1 >= h.shape[1]:
            self._info.setText(f"Y node has no DOF {dof}.")
            return None
        return h[:, dof - 1]

    def _read_element_force(self):
        eid_data = self._y_element.currentData()
        comp_name = self._y_component.currentData()
        if eid_data is None or comp_name is None:
            return None
        try:
            forces = self._results.element_force_history(int(eid_data))
        except Exception as exc:
            self._info.setText(f"Failed to read element {eid_data}: {exc}")
            return None
        order_3d = ["N1", "Vy1", "Vz1", "T1", "My1", "Mz1",
                    "N2", "Vy2", "Vz2", "T2", "My2", "Mz2"]
        order_2d = ["N1", "Vy1", "Mz1", "N2", "Vy2", "Mz2"]
        order = order_3d if forces.shape[1] >= 12 else order_2d
        if comp_name not in order:
            self._info.setText(
                f"Element {eid_data} has only {forces.shape[1]} force "
                f"components — '{comp_name}' not available.",
            )
            return None
        return forces[:, order.index(comp_name)]

    def _y_label(self) -> str:
        kind = self._y_kind.currentData()
        if kind == "element_force":
            return f"E{self._y_element.currentData()} {self._y_component.currentData()}"
        kind_label = {"node_disp": "disp", "node_vel": "vel", "node_accel": "accel"}.get(kind, "value")
        return f"N{self._y_node.currentData()} DOF {self._y_dof.value()} {kind_label}"

    def _clear_curve(self) -> None:
        if self._curve is not None:
            try:
                self._plot.removeItem(self._curve)
            except Exception:
                pass
            self._curve = None
