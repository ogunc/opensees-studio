"""Design → Connections: the AISC 358-22 RBS connections of the project."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.aisc import SOURCE_UNITS
from opensees_studio.core.design.connections import RbsConnection, rbs_geometry
from opensees_studio.core.geometry.elements import FRAME_ELEMENT_CLASSES
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import length_scale, stress_scale
from opensees_studio.services.steel_design import shape_in_units
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog


class ConnectionsDialog(FittedDialog):
    """Lists, adds, edits and removes RBS connections."""

    def __init__(self, project: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._items = [connection.model_copy() for connection in project.connections]
        self._sections = {s.id: s for s in project.sections}
        self._elements = {e.id: e for e in project.elements if isinstance(e, FRAME_ELEMENT_CLASSES)}
        self.setWindowTitle("Connections - AISC 358-22")
        self.setProperty(TOPIC_PROPERTY, "design.connections")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "A reduced beam section (RBS) moves the plastic hinge away from the "
                "column face. The cut is checked against AISC 358-22 Section 5.7: "
                "0.5bf <= a <= 0.75bf, 0.65d <= b <= 0.85d and 0.1bf <= c <= 0.25bf. "
                "The optional web connection checks the 5.5 plate, bolts and weld."
            )
        )
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Connection", "Beam", "Column", "a", "b", "c", "Web"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setMinimumHeight(130)
        self._table.itemSelectionChanged.connect(self._load_selected)
        layout.addWidget(self._table)

        form = QFormLayout()
        self._beam = QComboBox()
        self._column = QComboBox()
        for element_id, element in sorted(self._elements.items()):
            label = f"{element_id} ({self._section_name(element)})"
            self._beam.addItem(label, element_id)
            self._column.addItem(label, element_id)
        self._beam.currentIndexChanged.connect(self._prefill)
        form.addRow("Beam element:", self._beam)
        form.addRow("Column element:", self._column)
        self._a = FloatField()
        self._a.setRange(1e-6, 1e9)
        form.addRow("a (cut start):", self._a)
        self._b = FloatField()
        self._b.setRange(1e-6, 1e9)
        form.addRow("b (cut length):", self._b)
        self._c = FloatField()
        self._c.setRange(1e-6, 1e9)
        form.addRow("c (cut depth):", self._c)
        self._web_check = QCheckBox("Check web connection (AISC 358-22 5.5)")
        form.addRow("Web connection:", self._web_check)
        self._web_type = QComboBox()
        self._web_type.addItem("CJP groove weld (SMF)", "cjp")
        self._web_type.addItem("Bolted single plate (IMF)", "bolted")
        form.addRow("Web type:", self._web_type)
        self._web_t = FloatField()
        self._web_t.setRange(1e-6, 1e9)
        form.addRow("Plate thickness tp:", self._web_t)
        self._web_h = FloatField()
        self._web_h.setRange(1e-6, 1e9)
        form.addRow("Plate height hp:", self._web_h)
        self._web_n = FloatField()
        self._web_n.setRange(1.0, 1e6)
        form.addRow("Bolt count:", self._web_n)
        self._web_db = FloatField()
        self._web_db.setRange(1e-6, 1e9)
        form.addRow("Bolt diameter:", self._web_db)
        self._web_fnv = FloatField()
        self._web_fnv.setRange(1e-6, 1e9)
        self._web_fnv.setValue(54.0 * stress_scale(SOURCE_UNITS, project.meta.units))
        form.addRow("Bolt Fnv:", self._web_fnv)
        self._web_leg = FloatField()
        self._web_leg.setRange(1e-6, 1e9)
        form.addRow("Weld leg:", self._web_leg)
        self._web_fexx = FloatField()
        self._web_fexx.setRange(1e-6, 1e9)
        self._web_fexx.setValue(70.0 * stress_scale(SOURCE_UNITS, project.meta.units))
        form.addRow("Electrode Fexx:", self._web_fexx)
        layout.addLayout(form)

        row = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        update = QPushButton("Update selected")
        update.clicked.connect(self._update)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(update)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()
        self._prefill()

    def _section_name(self, element: Any) -> str:
        section = self._sections.get(getattr(element, "section_id", -1))
        return getattr(section, "name", "") or "no section"

    def _shape(self, element_id: int) -> Any:
        element = self._elements.get(element_id)
        if element is None:
            return None
        name = self._section_name(element)
        try:
            return shape_in_units(name, self._project.meta.units)
        except (KeyError, ValueError):
            return None

    def _next_id(self) -> int:
        used = {item.id for item in self._items}
        return max(used, default=0) + 1

    def _prefill(self) -> None:
        """Suggest the midpoints of the 5.7 limits for the selected beam."""
        shape = self._shape(int(self._beam.currentData())) if self._beam.count() else None
        if shape is None or not hasattr(shape, "bf"):
            return
        if self._a.value() and self._b.value() and self._c.value():
            return
        self._a.setValue(0.625 * shape.bf)
        self._b.setValue(0.75 * shape.d)
        self._c.setValue(0.175 * shape.bf)
        unit = length_scale(SOURCE_UNITS, self._project.meta.units)
        if self._web_t.value() <= 1e-6 * 1.001:
            self._web_t.setValue(0.375 * unit)
        if self._web_h.value() <= 1e-6 * 1.001:
            depth = float(getattr(shape, "d", getattr(shape, "H", getattr(shape, "D", 10.0))))
            flange = float(getattr(shape, "tf", 0.0) or 0.0)
            self._web_h.setValue(max(depth - 2.0 * flange, 0.1 * depth))
        if self._web_n.value() <= 1.0:
            self._web_n.setValue(4.0)
        if self._web_db.value() <= 1e-6 * 1.001:
            self._web_db.setValue(0.75 * unit)
        if self._web_leg.value() <= 1e-6 * 1.001:
            self._web_leg.setValue(0.625 * self._web_t.value())

    def _candidate(self) -> RbsConnection | None:
        if not self._beam.count() or not self._column.count():
            QMessageBox.warning(self, "Connections", "The project has no frame elements.")
            return None
        beam_id = int(self._beam.currentData())
        column_id = int(self._column.currentData())
        if beam_id == column_id:
            QMessageBox.warning(self, "Connections", "Beam and column are the same element.")
            return None
        shape = self._shape(beam_id)
        if shape is None:
            QMessageBox.warning(self, "Connections", "The beam section is not an AISC shape.")
            return None
        web = self._web_check.isChecked()
        try:
            connection = RbsConnection(
                id=self._next_id(),
                beam_element_id=beam_id,
                column_element_id=column_id,
                a=self._a.value(),
                b=self._b.value(),
                c=self._c.value(),
                web_connection_type=self._web_type.currentData(),
                web_plate_thickness=self._web_t.value() if web else None,
                web_plate_height=self._web_h.value() if web else None,
                web_bolt_count=int(self._web_n.value()) if web else None,
                web_bolt_diameter=self._web_db.value() if web else None,
                web_bolt_fnv=self._web_fnv.value() if web else None,
                web_weld_leg=self._web_leg.value() if web else None,
                web_weld_fexx=self._web_fexx.value() if web else None,
            )
            rbs_geometry(connection, shape)
        except ValueError as exc:
            QMessageBox.warning(self, "Connections", str(exc))
            return None
        return connection

    def _add(self) -> None:
        connection = self._candidate()
        if connection is None:
            return
        self._items.append(connection)
        self._refresh()

    def _update(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        connection = self._candidate()
        if connection is None:
            return
        connection.id = self._items[row].id
        self._items[row] = connection
        self._refresh()

    def _remove(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            del self._items[row]
            self._refresh()

    def _refresh(self) -> None:
        self._table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            values = (
                item.id,
                item.beam_element_id,
                item.column_element_id,
                item.a,
                item.b,
                item.c,
                item.web_connection_type if item.web_plate_thickness is not None else "-",
            )
            for column, value in enumerate(values):
                self._table.setItem(row, column, QTableWidgetItem(str(value)))
        webs = sum(1 for item in self._items if item.web_plate_thickness is not None)
        self._summary.setText(
            f"{len(self._items)} connection(s), {webs} web check(s). "
            "Invalid cuts are refused when added."
        )

    def _load_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._items):
            return
        item = self._items[row]
        for combo, value in (
            (self._beam, item.beam_element_id),
            (self._column, item.column_element_id),
        ):
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        self._a.setValue(item.a)
        self._b.setValue(item.b)
        self._c.setValue(item.c)
        unit = length_scale(SOURCE_UNITS, self._project.meta.units)
        self._web_check.setChecked(item.web_plate_thickness is not None)
        index = self._web_type.findData(item.web_connection_type)
        if index >= 0:
            self._web_type.setCurrentIndex(index)
        self._web_t.setValue(item.web_plate_thickness or 0.375 * unit)
        self._web_h.setValue(item.web_plate_height or 1.0)
        self._web_n.setValue(float(item.web_bolt_count or 4))
        self._web_db.setValue(item.web_bolt_diameter or 0.75 * unit)
        self._web_fnv.setValue(
            item.web_bolt_fnv or 54.0 * stress_scale(SOURCE_UNITS, self._project.meta.units)
        )
        self._web_leg.setValue(item.web_weld_leg or 0.625 * self._web_t.value())
        self._web_fexx.setValue(
            item.web_weld_fexx or 70.0 * stress_scale(SOURCE_UNITS, self._project.meta.units)
        )

    def connections(self) -> list[RbsConnection]:
        """The connections as the dialog shows them."""
        return [item.model_copy() for item in self._items]
