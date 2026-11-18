"""Section Library forms for the shells' nonlinear sections: LayeredShell and PlateFiber.

Both take plate nD materials (PlateFiber, PlateFromPlaneStress, PlateRebar) from
the project, so the library builds them with ``project``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QWidget,
)

from opensees_studio.core import LayeredShellSection, PlateFiberSection, Project, ShellLayer
from opensees_studio.core.materials.library import (
    PlateFiberMaterial,
    PlateFromPlaneStress,
    PlateRebar,
)
from opensees_studio.views.dialogs.section_forms import SectionFormBase
from opensees_studio.views.float_field import FloatField

_PLATE = (PlateFiberMaterial, PlateFromPlaneStress, PlateRebar)


def plate_materials(project: Project | None) -> list[Any]:
    """The project's materials a shell layer can use."""
    return [m for m in project.materials if isinstance(m, _PLATE)] if project is not None else []


def _material_combo(materials: list[Any], current: int | None = None) -> QComboBox:
    combo = QComboBox()
    for m in materials:
        combo.addItem(f"#{m.id} {m.name or m.type} [{m.type}]", m.id)
    index = combo.findData(current)
    if index >= 0:
        combo.setCurrentIndex(index)
    return combo


def _thickness(value: float) -> FloatField:
    field = FloatField()
    field.setRange(1e-12, 1e300)
    field.setValue(value)
    return field


class LayeredShellForm(SectionFormBase):
    type_label = "LayeredShell — layers through the thickness (RC walls and slabs)"
    needs_project = True

    def __init__(self, parent: QWidget | None = None, *, project: Project | None = None) -> None:
        super().__init__(parent)
        self._materials = plate_materials(project)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Plate material", "Thickness"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._layout.addRow(self.table)
        row = QHBoxLayout()
        add, remove = QPushButton("Add layer"), QPushButton("Remove layer")
        add.clicked.connect(lambda: self._append(None, 0.01))
        remove.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(remove)
        self._layout.addRow(row)
        if self._materials:
            for t in (0.07, 0.06, 0.07):
                self._append(self._materials[0].id, t)

    def _append(self, material_id: int | None, thickness: float) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setCellWidget(r, 0, _material_combo(self._materials, material_id))
        self.table.setCellWidget(r, 1, _thickness(thickness))

    def _remove(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def _populate_specific(self, section: LayeredShellSection) -> None:
        self.table.setRowCount(0)
        for layer in section.layers:
            self._append(layer.material_id, layer.thickness)

    def _read_specific(self, section_id: int) -> LayeredShellSection:
        if not self._materials:
            raise ValueError(
                "Define a plate material first (Material Library: PlateFiber, "
                "PlateFromPlaneStress or PlateRebar)."
            )
        layers = []
        for r in range(self.table.rowCount()):
            combo, field = self.table.cellWidget(r, 0), self.table.cellWidget(r, 1)
            assert isinstance(combo, QComboBox) and isinstance(field, FloatField)
            layers.append(ShellLayer(material_id=int(combo.currentData()), thickness=field.value()))
        return LayeredShellSection(id=section_id, name=self._name_edit.text(), layers=layers)


class PlateFiberSectionForm(SectionFormBase):
    type_label = "PlateFiber — one plate material through the thickness"
    needs_project = True

    def __init__(self, parent: QWidget | None = None, *, project: Project | None = None) -> None:
        super().__init__(parent)
        self._materials = plate_materials(project)
        self.material = _material_combo(self._materials)
        self.h = _thickness(0.2)
        self._layout.addRow("Plate material:", self.material)
        self._layout.addRow("Thickness h:", self.h)

    def _populate_specific(self, section: PlateFiberSection) -> None:
        index = self.material.findData(section.material_id)
        if index >= 0:
            self.material.setCurrentIndex(index)
        self.h.setValue(section.h)

    def _read_specific(self, section_id: int) -> PlateFiberSection:
        if self.material.currentData() is None:
            raise ValueError("Define a plate material first (Material Library: PlateFiber).")
        return PlateFiberSection(
            id=section_id,
            name=self._name_edit.text(),
            material_id=int(self.material.currentData()),
            h=self.h.value(),
        )
