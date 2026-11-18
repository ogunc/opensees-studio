"""Assign → Frame → RC Wall (MVLEM): the selected vertical members become wall segments.

The section is uniform over the selection: the wall length and thickness, the
number of vertical fibres, the steel ratio of the web and, optionally, of a
boundary element at each end, a concrete and a steel uniaxial material, and the
shear spring — elastic with a shear modulus (one material per segment height,
``G L t / h``) or an existing material. The conversion itself is
:func:`core.geometry.walls.walls_from_members`; the window applies it in one
undo step.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.geometry.walls import WallConversion, WallSpec, walls_from_members
from opensees_studio.core.materials.library import is_uniaxial
from opensees_studio.core.units import labels_for, mass_density_label
from opensees_studio.views.dialogs.section_designer import material_modulus
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea


class AssignWallDialog(FittedDialog):
    """The wall section, and a preview of how many members it converts."""

    def __init__(self, project: Any, element_ids: set[int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign RC Wall (MVLEM)")
        self._project = project
        self._element_ids = set(element_ids)
        self._conversion: WallConversion | None = None
        labels = labels_for(project.meta.units)
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "The selected <b>vertical</b> members become MVLEM wall segments (2D models). "
                "Use several segments per storey: the rotation of each is lumped at c·h."
            )
        )
        form = QFormLayout()
        self._length = self._float(1.0)
        self._thickness = self._float(0.2)
        form.addRow(f"Wall length L [{labels.length}]:", self._length)
        form.addRow(f"Thickness t [{labels.length}]:", self._thickness)
        self._fibres = QSpinBox()
        self._fibres.setRange(2, 100)
        self._fibres.setValue(8)
        self._fibres.valueChanged.connect(self._refresh)
        form.addRow("Vertical fibres:", self._fibres)
        self._web_ratio = self._float(0.003, minimum=0.0)
        form.addRow("Web steel ratio ρ:", self._web_ratio)
        self._boundary = self._float(0.0, minimum=0.0)
        form.addRow(f"Boundary element length [{labels.length}] (0 = none):", self._boundary)
        self._boundary_ratio = self._float(0.02, minimum=0.0)
        form.addRow("Boundary steel ratio ρ:", self._boundary_ratio)
        self._concrete = QComboBox()
        self._steel = QComboBox()
        self._shear_existing = QComboBox()
        for material in project.materials:
            if is_uniaxial(material):
                label = f"#{material.id} {material.name or material.type}"
                for combo in (self._concrete, self._steel, self._shear_existing):
                    combo.addItem(label, material.id)
        self._concrete.currentIndexChanged.connect(self._on_concrete)
        for combo in (self._steel, self._shear_existing):
            combo.currentIndexChanged.connect(self._refresh)
        form.addRow("Concrete material:", self._concrete)
        form.addRow("Steel material:", self._steel)
        self._elastic_shear = QRadioButton("Elastic shear, G:")
        self._elastic_shear.setChecked(True)
        self._elastic_shear.toggled.connect(self._refresh)
        self._shear_modulus = self._float(12.5e9)
        form.addRow(self._elastic_shear, self._shear_modulus)
        self._existing_shear = QRadioButton("Existing shear material:")
        form.addRow(self._existing_shear, self._shear_existing)
        self._c = self._float(0.4, minimum=0.0)
        self._c.setRange(0.0, 1.0)
        form.addRow("Centre of rotation c:", self._c)
        self._density = self._float(0.0, minimum=0.0)
        form.addRow(f"Density [{mass_density_label(project.meta.units)}]:", self._density)
        root.addLayout(form)
        self._message = MessageArea()
        root.addWidget(self._message)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)
        self._on_concrete()

    def _float(self, value: float, *, minimum: float = 1e-12) -> FloatField:
        field = FloatField()
        field.setRange(minimum, 1e18)
        field.setValue(value)
        field.valueChanged.connect(self._refresh)
        return field

    def _on_concrete(self) -> None:
        """G from the concrete's initial modulus (ν = 0.2) when it says one."""
        mid = self._concrete.currentData()
        material = next((m for m in self._project.materials if m.id == mid), None)
        modulus = material_modulus(material) if material is not None else None
        if modulus is not None:
            self._shear_modulus.blockSignals(True)
            self._shear_modulus.setValue(abs(modulus) / 2.4)
            self._shear_modulus.blockSignals(False)
        self._refresh()

    def spec(self) -> WallSpec | None:
        if self._concrete.currentData() is None or self._steel.currentData() is None:
            return None
        elastic = self._elastic_shear.isChecked()
        return WallSpec(
            length=self._length.value(),
            thickness=self._thickness.value(),
            fibres=self._fibres.value(),
            concrete_material_id=int(self._concrete.currentData()),
            steel_material_id=int(self._steel.currentData()),
            web_ratio=self._web_ratio.value(),
            boundary_length=self._boundary.value(),
            boundary_ratio=self._boundary_ratio.value(),
            shear_modulus=self._shear_modulus.value() if elastic else None,
            shear_material_id=None if elastic else int(self._shear_existing.currentData()),
            c=self._c.value(),
            density=self._density.value(),
        )

    def conversion(self) -> WallConversion | None:
        return self._conversion

    def _refresh(self) -> None:
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._shear_modulus.setEnabled(self._elastic_shear.isChecked())
        self._shear_existing.setEnabled(not self._elastic_shear.isChecked())
        spec = self.spec()
        if spec is None:
            self._conversion = None
            self._message.show_message(
                "Define a concrete and a steel uniaxial material first (Define → Material "
                "Library, or the Concrete Section Wizard).",
                "error",
            )
            ok.setEnabled(False)
            return
        if self._project.ndm != 2:
            self._conversion = None
            self._message.show_message("MVLEM walls need a 2D model.", "error")
            ok.setEnabled(False)
            return
        try:
            conversion = walls_from_members(
                self._project,
                self._element_ids,
                spec,
                first_material_id=self._project.next_material_id(),
            )
        except ValueError as exc:
            self._conversion = None
            self._message.show_message(str(exc), "error")
            ok.setEnabled(False)
            return
        self._conversion = conversion
        text = f"{len(conversion.elements)} member(s) become wall segments"
        if conversion.materials:
            text += f", with {len(conversion.materials)} shear material(s) created"
        if conversion.skipped:
            text += f"; {len(conversion.skipped)} not vertical two-joint members left as they are"
        self._message.show_message(text + ".", "info" if conversion.elements else "warning")
        ok.setEnabled(bool(conversion.elements))
