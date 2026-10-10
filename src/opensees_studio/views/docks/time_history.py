"""Time-history plotter dock — node displacement vs time using pyqtgraph.

Lets the user pick one or more (node, DOF) pairs and overlays their
displacement traces on a single plot. pyqtgraph is used because it
handles 100k-point traces interactively without breaking a sweat.

Currently plots displacement only; velocity/acceleration require the
runner to record additional series (planned for a later phase).
"""

from __future__ import annotations

import contextlib
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import UnitConverter
from opensees_studio.services.results import TransientResults
from opensees_studio.views.plot_style import add_legend, axis_label, readable_plot

#: Axis title and unit suffix per plotted quantity. Every one of them is a
#: length per a power of time, so all three convert with the length factor.
_QUANTITY_LABEL = {
    "disp": ("Displacement", ""),
    "vel": ("Velocity", "/s"),
    "accel": ("Acceleration", "/s^2"),
}

# A small palette that reads well on dark + light themes.
_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]


class TimeHistoryView(QWidget):
    """Dock contents: plot + per-trace controls.

    Public API:
    - ``set_results(results)`` — bind to a new analysis run.
    - ``set_available_nodes(node_ids)`` — populate the node picker.
    """

    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._results: TransientResults | None = None
        self._traces: list[tuple[int, int, str, Any]] = []  # (node_id, dof, quantity, plot_item)
        self._converter = UnitConverter()
        self._build_ui()

    # ── public ──────────────────────────────────────────────────────
    def set_units(self, converter: UnitConverter) -> None:
        """Re-plot every trace in ``converter``'s display units."""
        self._converter = converter
        self._replot_all()

    def set_results(self, results: TransientResults | None) -> None:
        self._results = results
        self._clear_traces()
        if results is None:
            self._info.setText("No transient results loaded.")
            return
        self._info.setText(
            f"Case '{results.case_name}': {results.steps_summary()}, dt={results.dt}",
        )

    def set_available_nodes(self, node_ids: list[int]) -> None:
        self._node_picker.clear()
        for nid in node_ids:
            self._node_picker.addItem(str(nid), nid)

    # ── ui ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Node:"))
        self._node_picker = QComboBox()
        self._node_picker.setMinimumWidth(80)
        controls.addWidget(self._node_picker)

        controls.addWidget(QLabel("DOF:"))
        self._dof_spin = QSpinBox()
        self._dof_spin.setRange(1, 6)
        self._dof_spin.setValue(1)
        controls.addWidget(self._dof_spin)

        controls.addWidget(QLabel("Quantity:"))
        self._quantity = QComboBox()
        self._quantity.addItem("Displacement", "disp")
        self._quantity.addItem("Velocity", "vel")
        self._quantity.addItem("Acceleration", "accel")
        controls.addWidget(self._quantity)

        self._add_btn = QPushButton("Add trace")
        self._add_btn.clicked.connect(self._on_add_trace)
        controls.addWidget(self._add_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._clear_traces)
        controls.addWidget(self._clear_btn)
        controls.addStretch(1)

        self._hide_btn = QPushButton("Hide")
        self._hide_btn.clicked.connect(self.closed.emit)
        controls.addWidget(self._hide_btn)
        root.addLayout(controls)

        self._info = QLabel("")
        self._info.setStyleSheet("color: #888;")
        root.addWidget(self._info)

        # pyqtgraph setup. Use a white-on-dark theme that matches Claude.
        pg.setConfigOptions(antialias=True)
        self._plot = readable_plot()
        self._plot.setLabel("left", self._quantity_axis_label("disp"))
        self._plot.setLabel("bottom", axis_label("Time", "s"))
        add_legend(self._plot)
        root.addWidget(self._plot, 1)

        self._trace_list = QListWidget()
        self._trace_list.setMaximumHeight(80)
        root.addWidget(self._trace_list)

    # ── slots ───────────────────────────────────────────────────────
    def _on_add_trace(self) -> None:
        if self._results is None:
            return
        nid_data = self._node_picker.currentData()
        if nid_data is None:
            return
        nid = int(nid_data)
        dof = int(self._dof_spin.value())
        quantity = self._quantity.currentData() or "disp"
        self._add_trace(nid, dof, quantity)

    def _add_trace(self, nid: int, dof: int, quantity: str, index: int | None = None) -> None:
        """Plot one (node, DOF, quantity) trace; ``index`` keeps a redraw in place."""
        if self._results is None:
            return
        accessor = {
            "disp": self._results.node_disp_history,
            "vel": self._results.node_vel_history,
            "accel": self._results.node_accel_history,
        }[quantity]
        try:
            history = accessor(nid)
        except Exception as exc:
            self._info.setText(f"Failed to read {quantity} for node {nid}: {exc}")
            return
        if dof - 1 >= history.shape[1]:
            self._info.setText(f"Node {nid} has no DOF {dof} (only {history.shape[1]}).")
            return
        time = self._results.time()
        n = min(len(time), history.shape[0])
        position = len(self._traces) if index is None else index
        color = _COLORS[position % len(_COLORS)]
        pen = pg.mkPen(color=color, width=2)
        label = f"N{nid}/D{dof} {quantity}"
        values = history[:n, dof - 1] * self._converter.factor("length")
        item = self._plot.plot(time[:n], values, pen=pen, name=label)
        if index is None:
            self._traces.append((nid, dof, quantity, item))
            self._trace_list.addItem(QListWidgetItem(label))
        else:
            self._traces[index] = (nid, dof, quantity, item)
        self._plot.setLabel("left", self._quantity_axis_label(quantity))

    def _quantity_axis_label(self, quantity: str) -> str:
        title, per_time = _QUANTITY_LABEL[quantity]
        return axis_label(title, f"{self._converter.labels.length}{per_time}")

    def _replot_all(self) -> None:
        """Redraw every trace with the current display units (keeps the selection)."""
        traces = list(self._traces)
        self._clear_traces()
        for nid, dof, quantity, _item in traces:
            self._add_trace(nid, dof, quantity)
        if traces:
            self._plot.setLabel("left", self._quantity_axis_label(traces[-1][2]))
        else:
            self._plot.setLabel("left", self._quantity_axis_label("disp"))

    def _clear_traces(self) -> None:
        for _, _, _, item in self._traces:
            with contextlib.suppress(Exception):
                self._plot.removeItem(item)
        self._traces.clear()
        self._trace_list.clear()
