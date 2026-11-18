"""Display → Influence Line: one response of an influence-line case, and a vehicle on it.

The case walked a load along a path; this dialog plots any joint displacement,
reaction or member end force against the distance along that path (for a unit
load in the sense of the case's load) and moves a vehicle — axle loads and
their distances behind the front axle — across it in both directions, reporting
the largest and smallest effect and where the front axle stood.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.analysis import Axle, InfluenceLineCase
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import labels_for
from opensees_studio.services.influence import (
    FORCE_COMPONENTS,
    dof_labels,
    influence_line,
    vehicle_envelope,
)
from opensees_studio.services.results import InfluenceLineResults
from opensees_studio.views.plot_style import axis_label, readable_plot
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

_QUANTITIES = [
    ("Joint displacement", "displacement"),
    ("Reaction", "reaction"),
    ("Member end force", "force"),
]


class InfluenceLineDialog(FittedDialog):
    """Plot an influence line and envelope a vehicle on it."""

    def __init__(
        self, project: Any, results: InfluenceLineResults, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._results = results
        self._line: Any = None
        self.setWindowTitle(f"Influence Line — {results.case_name}")
        self.setProperty(TOPIC_PROPERTY, "display.influence_line")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"A unit load along {results.direction} walked over {results.n_steps} stops. "
                "Pick a response; the curve is its value with the load at each distance "
                "along the path."
            )
        )
        form = QFormLayout()
        self._quantity = QComboBox()
        for label, key in _QUANTITIES:
            self._quantity.addItem(label, key)
        self._quantity.currentIndexChanged.connect(self._on_quantity)
        form.addRow("Response:", self._quantity)
        row = QHBoxLayout()
        self._target = QSpinBox()
        self._target.setRange(1, 10**9)
        self._component = QComboBox()
        self._end = QComboBox()
        self._end.addItems(["i", "j"])
        row.addWidget(QLabel("Joint / member:"))
        row.addWidget(self._target)
        row.addWidget(QLabel("Component:"))
        row.addWidget(self._component)
        row.addWidget(QLabel("End:"))
        row.addWidget(self._end)
        form.addRow(row)
        layout.addLayout(form)
        for widget in (self._target, self._component, self._end):
            signal = (
                widget.valueChanged if isinstance(widget, QSpinBox) else widget.currentIndexChanged
            )
            signal.connect(self.refresh)

        self._plot = readable_plot()
        length = labels_for(project.meta.units).length
        self._plot.setLabel("bottom", axis_label("Distance along the path", length))
        self._plot.setMinimumHeight(240)
        layout.addWidget(self._plot, 1)

        layout.addWidget(
            QLabel(
                "<b>Vehicle</b> (axle load in the sense of the case's load; "
                "offset behind the front axle)"
            )
        )
        self._axles = QTableWidget(0, 2)
        self._axles.setHorizontalHeaderLabels(["Axle load", f"Offset [{length}]"])
        self._axles.setMaximumHeight(140)
        layout.addWidget(self._axles)
        buttons_row = QHBoxLayout()
        add = QPushButton("Add axle")
        add.clicked.connect(lambda: self._add_axle(1.0, 0.0))
        remove = QPushButton("Remove axle")
        remove.clicked.connect(self._remove_axle)
        run = QPushButton("Envelope")
        run.clicked.connect(self.envelope)
        for button in (add, remove, run):
            buttons_row.addWidget(button)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)
        self._summary = MessageArea()
        layout.addWidget(self._summary)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

        case = next((c for c in project.analyses if c.id == results.case_id), None)
        axles = (
            case.axles if isinstance(case, InfluenceLineCase) and case.axles else [Axle(load=1.0)]
        )
        for axle in axles:
            self._add_axle(axle.load, axle.offset)
        if isinstance(case, InfluenceLineCase):
            self._target.setValue(case.path[0])
        self._quantity.setCurrentIndex(2)
        self._on_quantity()

    # ── controls ────────────────────────────────────────────────────
    def _on_quantity(self) -> None:
        key = self._quantity.currentData()
        self._component.blockSignals(True)
        self._component.clear()
        if key == "force":
            three_d = self._project.ndm == 3
            names = [
                k for k, (i3, i2) in FORCE_COMPONENTS.items() if (i3 if three_d else i2) is not None
            ]
            self._component.addItems(names)
            self._component.setCurrentText("M2" if three_d else "M3")
        else:
            self._component.addItems(dof_labels(self._project))
        self._component.blockSignals(False)
        self._end.setEnabled(key == "force")
        self.refresh()

    def _add_axle(self, load: float, offset: float) -> None:
        row = self._axles.rowCount()
        self._axles.insertRow(row)
        self._axles.setItem(row, 0, QTableWidgetItem(f"{load:g}"))
        self._axles.setItem(row, 1, QTableWidgetItem(f"{offset:g}"))

    def _remove_axle(self) -> None:
        if self._axles.rowCount() > 1:
            self._axles.removeRow(self._axles.rowCount() - 1)

    def axles(self) -> list[Axle]:
        out = []
        for row in range(self._axles.rowCount()):
            load_item, offset_item = self._axles.item(row, 0), self._axles.item(row, 1)
            try:
                load = float(load_item.text()) if load_item else 0.0
                offset = float(offset_item.text()) if offset_item else 0.0
            except ValueError:
                continue
            out.append(Axle(load=load, offset=max(offset, 0.0)))
        return out

    # ── computing ───────────────────────────────────────────────────
    def line(self) -> Any:
        return self._line

    def refresh(self) -> None:
        self._plot.clear()
        try:
            self._line = influence_line(
                self._project,
                self._results,
                self._quantity.currentData(),
                self._target.value(),
                self._component.currentText(),
                end=self._end.currentText(),  # type: ignore[arg-type]
            )
        except KeyError as exc:
            self._line = None
            self._summary.show_message(str(exc.args[0] if exc.args else exc), level="warning")
            return
        self._plot.plot(self._results.distances, self._line, symbol="o", symbolSize=4)
        self._plot.setLabel("left", f"{self._component.currentText()} per unit load")
        self._summary.show_message(
            f"Largest {self._line.max():.6g} at {self._results.distances[self._line.argmax()]:g}, "
            f"smallest {self._line.min():.6g} at {self._results.distances[self._line.argmin()]:g}."
        )

    def envelope(self) -> Any:
        if self._line is None:
            return None
        axles = self.axles()
        if not axles:
            self._summary.show_message("The vehicle has no axles.", level="warning")
            return None
        found = vehicle_envelope(self._results, self._line, axles)
        way = {False: "forward", True: "backward"}
        self._summary.show_message(
            f"Vehicle of {len(axles)} axle(s): maximum {found.maximum:.6g} with the front axle "
            f"at {found.front_at_maximum:g} ({way[found.reversed_at_maximum]}), minimum "
            f"{found.minimum:.6g} at {found.front_at_minimum:g} "
            f"({way[found.reversed_at_minimum]})."
        )
        return found
