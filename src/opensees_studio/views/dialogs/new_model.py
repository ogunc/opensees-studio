"""File → New Model: pick the units and a template, as SAP2000's New Model does.

Blank, Grid Only, Beam, 2D Truss, 2D Frame and 3D Frame. The Beam and 3D Frame
ask their numbers here; Grid Only, 2D Truss and 2D Frame open their wizard
after the model is created, so this dialog only collects the choice.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.templates import TEMPLATES
from opensees_studio.core.units import UnitSystem, labels_for
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog

#: What each template does after the model is created.
_HINTS = {
    "blank": "An empty 3D model (ndm 3, ndf 6) with the Dead load case.",
    "grid": "An empty 3D model, then the Grid Wizard to lay out its grid lines.",
    "beam": "A continuous 2D beam: equal spans on a pin and rollers, with its grid.",
    "truss2d": "A 2D truss model (two translations per joint), then the Truss Wizard.",
    "frame2d": "A 2D frame model, then the Portal Frame Wizard and its grid.",
    "frame3d": "A 3D frame: fixed column bases and beams both ways on every floor.",
}


def _count(value: int, maximum: int = 100) -> QSpinBox:
    box = QSpinBox()
    box.setRange(1, maximum)
    box.setValue(value)
    return box


def _length(value: float) -> FloatField:
    field = FloatField()
    field.setRange(1e-9, 1e9)
    field.setValue(value)
    return field


class NewModelDialog(FittedDialog):
    """Units, template and, for the Beam and 3D Frame, their numbers."""

    def __init__(self, units: UnitSystem = UnitSystem.SI_M_N, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("New Model")
        root = QVBoxLayout(self)

        form = QFormLayout()
        self.units_combo = QComboBox()
        for system in UnitSystem:
            self.units_combo.addItem(system.value, system)
        self.units_combo.setCurrentIndex(list(UnitSystem).index(units))
        form.addRow("Units:", self.units_combo)
        root.addLayout(form)

        templates = QGroupBox("Template")
        layout = QVBoxLayout(templates)
        self.template_list = QListWidget()
        for key, name in TEMPLATES.items():
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setToolTip(_HINTS[key])
            self.template_list.addItem(item)
        self.template_list.setCurrentRow(0)
        layout.addWidget(self.template_list)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        root.addWidget(templates)

        self.pages = QStackedWidget()
        self.pages.addWidget(QWidget())  # nothing to ask
        beam = QWidget()
        beam_form = QFormLayout(beam)
        self.beam_spans = _count(3)
        self.beam_span = _length(6.0)
        beam_form.addRow("Number of spans:", self.beam_spans)
        self._beam_span_label = QLabel()
        beam_form.addRow(self._beam_span_label, self.beam_span)
        self.pages.addWidget(beam)
        frame = QWidget()
        frame_form = QFormLayout(frame)
        self.bays_x = _count(3)
        self.bays_y = _count(2)
        self.storeys = _count(3)
        self.spacing_x = _length(6.0)
        self.spacing_y = _length(6.0)
        self.storey_height = _length(3.0)
        self._frame_labels = [QLabel(), QLabel(), QLabel()]
        frame_form.addRow("Bays along X:", self.bays_x)
        frame_form.addRow("Bays along Y:", self.bays_y)
        frame_form.addRow("Storeys:", self.storeys)
        frame_form.addRow(self._frame_labels[0], self.spacing_x)
        frame_form.addRow(self._frame_labels[1], self.spacing_y)
        frame_form.addRow(self._frame_labels[2], self.storey_height)
        self.pages.addWidget(frame)
        root.addWidget(self.pages)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.template_list.currentRowChanged.connect(self._on_template)
        self.template_list.itemDoubleClicked.connect(lambda _item: self.accept())
        self.units_combo.currentIndexChanged.connect(self._on_units)
        self._on_template()
        self._on_units()

    def _on_template(self, _row: int = 0) -> None:
        key = self.template()
        self.hint.setText(_HINTS[key])
        self.pages.setCurrentIndex({"beam": 1, "frame3d": 2}.get(key, 0))

    def _on_units(self, _index: int = 0) -> None:
        unit = labels_for(self.units()).length
        self._beam_span_label.setText(f"Span length ({unit}):")
        for label, text in zip(
            self._frame_labels, ("Bay width X", "Bay width Y", "Storey height"), strict=True
        ):
            label.setText(f"{text} ({unit}):")

    # ── answers ──────────────────────────────────────────────────────
    def template(self) -> str:
        item = self.template_list.currentItem()
        return "blank" if item is None else str(item.data(Qt.ItemDataRole.UserRole))

    def select_template(self, key: str) -> None:
        self.template_list.setCurrentRow(list(TEMPLATES).index(key))

    def units(self) -> UnitSystem:
        return UnitSystem(self.units_combo.currentData())

    def beam_numbers(self) -> tuple[int, float]:
        return self.beam_spans.value(), self.beam_span.value()

    def frame_numbers(self) -> tuple[int, int, int, float, float, float]:
        return (
            self.bays_x.value(),
            self.bays_y.value(),
            self.storeys.value(),
            self.spacing_x.value(),
            self.spacing_y.value(),
            self.storey_height.value(),
        )
