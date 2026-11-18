"""Design → Gussets: the SCBF gusset plates of the project."""

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
from opensees_studio.core.design.gusset_model import Gusset
from opensees_studio.core.design.gussets import whitmore_width
from opensees_studio.core.geometry.elements import FRAME_ELEMENT_CLASSES
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import stress_scale
from opensees_studio.services.steel_design import shape_in_units
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog


class GussetsDialog(FittedDialog):
    """Lists, adds, edits and removes SCBF gusset plates."""

    def __init__(self, project: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._items = [gusset.model_copy() for gusset in project.gussets]
        self._sections = {s.id: s for s in project.sections}
        self._elements = {e.id: e for e in project.elements if isinstance(e, FRAME_ELEMENT_CLASSES)}
        self.setWindowTitle("Gussets - AISC 341-22")
        self.setProperty(TOPIC_PROPERTY, "design.gussets")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "SCBF gusset plates (AISC 341-22 F2.6c). The plate is checked for "
                "Whitmore width, yielding and plate buckling against the expected "
                "brace force Ry Fy Ag. The brace connection demands and the "
                "gusset-to-flange fillet weld (F2.6c.4) are reported with the plate."
            )
        )
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(["Gusset", "Brace", "t", "b", "Lw", "Lc", "Weld"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setMinimumHeight(130)
        self._table.itemSelectionChanged.connect(self._load_selected)
        layout.addWidget(self._table)

        form = QFormLayout()
        self._brace = QComboBox()
        for element_id, element in sorted(self._elements.items()):
            section = self._sections.get(getattr(element, "section_id", -1))
            name = getattr(section, "name", "") or "no section"
            self._brace.addItem(f"{element_id} ({name})", element_id)
        self._brace.currentIndexChanged.connect(self._prefill)
        form.addRow("Brace element:", self._brace)
        self._t = FloatField()
        self._t.setRange(1e-6, 1e9)
        form.addRow("Plate thickness t:", self._t)
        self._b = FloatField()
        self._b.setRange(1e-6, 1e9)
        form.addRow("Plate width b:", self._b)
        self._lw = FloatField()
        self._lw.setRange(1e-6, 1e9)
        form.addRow("Whitmore length Lw:", self._lw)
        self._lc = FloatField()
        self._lc.setRange(1e-6, 1e9)
        form.addRow("Free length Lc:", self._lc)
        self._weld_check = QCheckBox("Check gusset-to-flange weld (F2.6c.4)")
        self._weld_check.toggled.connect(self._prefill_weld)
        form.addRow("Weld:", self._weld_check)
        self._weld_leg = FloatField()
        self._weld_leg.setRange(1e-6, 1e9)
        form.addRow("Fillet weld leg:", self._weld_leg)
        self._weld_both = QCheckBox("Both sides")
        self._weld_both.setChecked(True)
        form.addRow("Weld sides:", self._weld_both)
        self._weld_fexx = FloatField()
        self._weld_fexx.setRange(1e-6, 1e9)
        self._weld_fexx.setValue(70.0 * stress_scale(SOURCE_UNITS, project.meta.units))
        form.addRow("Electrode Fexx:", self._weld_fexx)
        self._t.valueChanged.connect(self._on_thickness_changed)
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

    def _prefill(self) -> None:
        """Suggest a plate from the selected brace when the fields are empty."""
        shape = self._shape(int(self._brace.currentData())) if self._brace.count() else None
        if shape is None:
            return
        if self._t.value() and self._b.value() and self._lw.value() and self._lc.value():
            return
        thickness = float(getattr(shape, "tf", 0.0) or 0.0) or 0.5
        depth = float(getattr(shape, "d", 0.0) or 0.0) or 10.0
        self._t.setValue(thickness)
        self._lw.setValue(depth)
        self._lc.setValue(depth)
        self._b.setValue(whitmore_width(depth, thickness))

    def _prefill_weld(self, checked: bool = False) -> None:
        """Suggest 0.74 t (A572 Gr 50, E70) when the weld check is enabled."""
        if not checked:
            return
        thickness = self._t.value()
        if thickness > 0.0:
            self._weld_leg.setValue(0.74 * thickness)

    def _on_thickness_changed(self, value: float) -> None:
        """Keep the suggested weld leg in step while the user has not set it."""
        if not self._weld_check.isChecked():
            return
        if self._weld_leg.value() <= 1e-6 * 1.001:
            self._weld_leg.setValue(0.74 * value)

    def _next_id(self) -> int:
        used = {item.id for item in self._items}
        return max(used, default=0) + 1

    def _candidate(self) -> Gusset | None:
        if not self._brace.count():
            QMessageBox.warning(self, "Gussets", "The project has no frame elements.")
            return None
        brace_id = int(self._brace.currentData())
        shape = self._shape(brace_id)
        if shape is None:
            QMessageBox.warning(self, "Gussets", "The brace section is not an AISC shape.")
            return None
        try:
            weld_leg = self._weld_leg.value() if self._weld_check.isChecked() else None
            candidate = Gusset(
                id=self._next_id(),
                brace_element_id=brace_id,
                t=self._t.value(),
                b=self._b.value(),
                lw=self._lw.value(),
                free_length=self._lc.value(),
                weld_leg=weld_leg,
                weld_both_sides=self._weld_both.isChecked(),
                weld_fexx=self._weld_fexx.value() if weld_leg is not None else None,
            )
            whitmore_width(candidate.lw, float(getattr(shape, "tf", 0.0) or 0.0))
        except ValueError as exc:
            QMessageBox.warning(self, "Gussets", str(exc))
            return None
        return candidate

    def _add(self) -> None:
        candidate = self._candidate()
        if candidate is not None:
            self._items.append(candidate)
            self._refresh()

    def _update(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        candidate = self._candidate()
        if candidate is None:
            return
        candidate.id = self._items[row].id
        self._items[row] = candidate
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
                item.brace_element_id,
                item.t,
                item.b,
                item.lw,
                item.free_length,
                item.weld_leg if item.weld_leg is not None else "-",
            )
            for column, value in enumerate(values):
                self._table.setItem(row, column, QTableWidgetItem(str(value)))
        welds = sum(1 for item in self._items if item.weld_leg is not None)
        self._summary.setText(f"{len(self._items)} gusset(s), {welds} weld(s).")

    def _load_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._items):
            return
        item = self._items[row]
        index = self._brace.findData(item.brace_element_id)
        if index >= 0:
            self._brace.setCurrentIndex(index)
        self._t.setValue(item.t)
        self._b.setValue(item.b)
        self._lw.setValue(item.lw)
        self._lc.setValue(item.free_length)
        self._weld_check.setChecked(item.weld_leg is not None)
        self._weld_leg.setValue(item.weld_leg if item.weld_leg is not None else 0.74 * item.t)
        self._weld_both.setChecked(item.weld_both_sides)
        default_fexx = 70.0 * stress_scale(SOURCE_UNITS, self._project.meta.units)
        self._weld_fexx.setValue(item.weld_fexx or default_fexx)

    def gussets(self) -> list[Gusset]:
        """The gussets as the dialog shows them."""
        return [item.model_copy() for item in self._items]
