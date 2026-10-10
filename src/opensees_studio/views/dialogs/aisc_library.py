"""Pick an AISC v16 shape and turn it into a section.

The table is US customary as published, and the project has its own unit
system, so the dialog's job is to make that difference visible rather than to
hide it: the table shows the published values, and the preview shows exactly
what will be inserted once converted. Nothing is added to the model until OK.

Two routes, because they answer different questions:

- **Elastic section** — A, Iz, Iy and J, which is what a frame analysis needs.
  E and G are asked for here because they are material properties the library
  does not carry.
- **Fibre section** — the real profile as OpenSees ``WFSection2d`` patches, for
  a member that has to yield or crack fibre by fibre. Only offered for the
  flange-and-web families, and it needs a material to assign the patches to.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import ElasticSection, FiberSection
from opensees_studio.core.aisc import (
    FAMILY_LABELS,
    AISCShape,
    converted_geometry,
    families,
    shapes_of,
)
from opensees_studio.core.units import UnitSystem, labels_for
from opensees_studio.views.float_field import FloatField, format_float
from opensees_studio.views.screen_fit import FittedDialog

#: Columns of the shape table: (heading, attribute, format).
_COLUMNS: list[tuple[str, str, str]] = [
    ("Shape", "name", ""),
    ("lb/ft", "weight", ".1f"),
    ("A (in²)", "area", ".2f"),
    ("d (in)", "d", ".3f"),
    ("Ix (in⁴)", "ix", ".1f"),
    ("Zx (in³)", "zx", ".1f"),
    ("Iy (in⁴)", "iy", ".1f"),
    ("ry (in)", "ry", ".2f"),
]

#: Steel's elastic modulus in each system, as the dialog's starting point.
_DEFAULT_E: dict[UnitSystem, float] = {
    UnitSystem.SI_M_N: 200e9,
    UnitSystem.SI_MM_N: 200e3,
    UnitSystem.US_IN_KIP: 29000.0,
    UnitSystem.US_FT_KIP: 29000.0 * 144.0,
}


class AiscLibraryDialog(FittedDialog):
    """A shape picker; :meth:`result_section` is what the caller inserts."""

    def __init__(
        self,
        *,
        units: UnitSystem,
        materials: list[Any] | None = None,
        next_id: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("AISC v16 shapes")
        self.resize(980, 620)
        self._units = units
        self._labels = labels_for(units)
        self._materials = materials or []
        self._section_id = next_id
        self._shapes: list[AISCShape] = []
        self._build_ui()
        self._reload()

    # ── construction ─────────────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(
            QLabel(
                "<b>AISC v16 shapes</b> — properties as published (US customary). "
                "The preview shows the values in this project's units."
            )
        )

        picker = QHBoxLayout()
        self._family = QComboBox()
        for code in families():
            self._family.addItem(FAMILY_LABELS.get(code, code), code)
        self._family.currentIndexChanged.connect(self._reload)
        picker.addWidget(QLabel("Family:"))
        picker.addWidget(self._family)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter by name, e.g. W14")
        self._filter.textChanged.connect(self._reload)
        picker.addWidget(self._filter, stretch=1)
        outer.addLayout(picker)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([c[0] for c in _COLUMNS])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._update_preview)
        outer.addWidget(self._table, stretch=1)

        outer.addWidget(self._build_route_group())
        self._preview = QLabel("")
        self._preview.setWordWrap(True)
        self._preview.setStyleSheet("color: #2c3e50;")
        outer.addWidget(self._preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _build_route_group(self) -> QGroupBox:
        box = QGroupBox("Insert as")
        layout = QVBoxLayout(box)

        self._elastic_radio = QRadioButton("Elastic section (A, Iz, Iy, J)")
        self._elastic_radio.setChecked(True)
        self._elastic_radio.toggled.connect(self._update_preview)
        layout.addWidget(self._elastic_radio)

        elastic_form = QFormLayout()
        self._e_field = FloatField()
        self._e_field.setRange(1e-9, 1e15)
        self._e_field.setValue(_DEFAULT_E[self._units])
        self._e_field.valueChanged.connect(self._update_preview)
        elastic_form.addRow(f"E ({self._labels.stress}):", self._e_field)
        self._g_field = FloatField()
        self._g_field.setRange(0.0, 1e15)
        self._g_field.setValue(round(_DEFAULT_E[self._units] / 2.6, 6))
        self._g_field.valueChanged.connect(self._update_preview)
        elastic_form.addRow(f"G ({self._labels.stress}):", self._g_field)
        layout.addLayout(elastic_form)

        self._fiber_radio = QRadioButton("Fibre section (real profile, WFSection2d patches)")
        self._fiber_radio.toggled.connect(self._update_preview)
        layout.addWidget(self._fiber_radio)

        fiber_form = QFormLayout()
        self._material = QComboBox()
        for material in self._materials:
            self._material.addItem(f"#{material.id} {material.name}", material.id)
        self._material.currentIndexChanged.connect(self._update_preview)
        fiber_form.addRow("Material:", self._material)
        layout.addLayout(fiber_form)
        if not self._materials:
            self._fiber_radio.setEnabled(False)
            self._fiber_radio.setToolTip("The project has no materials to assign the fibres to.")
        return box

    # ── table ────────────────────────────────────────────────────────
    def _reload(self) -> None:
        family = self._family.currentData()
        text = self._filter.text().strip().upper()
        self._shapes = [s for s in shapes_of(family) if text in s.name.upper()]
        self._table.setRowCount(len(self._shapes))
        for row, shape in enumerate(self._shapes):
            for column, (_, attribute, fmt) in enumerate(_COLUMNS):
                value = getattr(shape, attribute)
                text_value = "" if value is None else (format(value, fmt) if fmt else str(value))
                item = QTableWidgetItem(text_value)
                if column:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self._table.setItem(row, column, item)
        self._table.resizeColumnsToContents()
        if self._shapes:
            self._table.selectRow(0)
        self._update_preview()

    def selected_shape(self) -> AISCShape | None:
        """The highlighted shape, or None when the table is empty."""
        row = self._table.currentRow()
        if 0 <= row < len(self._shapes):
            return self._shapes[row]
        return None

    # ── preview and result ───────────────────────────────────────────
    def _update_preview(self) -> None:
        shape = self.selected_shape()
        if shape is None:
            self._preview.setText("No shape selected.")
            return
        geometry = converted_geometry(shape, self._units)
        parts = [f"{key} = {format_float(round(value, 12))}" for key, value in geometry.items()]
        note = (
            f"<b>{shape.name}</b> — will insert {', '.join(parts)} "
            f"in {self._labels.length}, {self._labels.force}."
        )
        if self._fiber_radio.isChecked():
            if not shape.has_ishape_geometry:
                note += " <span style='color:#c0392b'>This family has no flange-and-web geometry.</span>"
            else:
                note = (
                    f"<b>{shape.name}</b> — fibre patches at the published dimensions "
                    f"(d={shape.d}, bf={shape.bf}, tf={shape.tf}, tw={shape.tw} in), "
                    "in this project's units."
                )
        self._preview.setText(note)

    def result_section(self) -> ElasticSection | FiberSection:
        """The section to insert; call only after the dialog was accepted."""
        shape = self.selected_shape()
        if shape is None:
            raise ValueError("No shape selected.")
        if self._fiber_radio.isChecked():
            from opensees_studio.core.aisc import shape_to_fiber_section

            material_id = self._material.currentData()
            if material_id is None:
                raise ValueError("A fibre section needs a material to assign its fibres to.")
            return shape_to_fiber_section(
                shape, material_id=int(material_id), section_id=self._section_id
            )
        from opensees_studio.core.aisc import shape_to_elastic_section

        return shape_to_elastic_section(
            shape,
            elastic_modulus=self._e_field.value(),
            shear_modulus=self._g_field.value(),
            section_id=self._section_id,
            units=self._units,
        )
