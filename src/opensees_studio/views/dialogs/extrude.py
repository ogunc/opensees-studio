"""Edit → Extrude dialog: the offset of one step, how many steps, and the section."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog


class ExtrudeDialog(FittedDialog):
    """Joints into frames or frames into shells: ``(dx, dy, dz)``, steps, section."""

    def __init__(
        self,
        *,
        into_shells: bool,
        n_objects: int,
        sections: list[tuple[int, str]],
        parent: QWidget | None = None,
        length_unit: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extrude")
        layout = QVBoxLayout(self)
        what = (
            f"Extrude <b>{n_objects}</b> frame(s) into shells."
            if into_shells
            else f"Extrude <b>{n_objects}</b> joint(s) into frames."
        )
        layout.addWidget(QLabel(what))
        layout.addWidget(
            QLabel(
                "<i>Each step adds the offset; a point that falls on an existing joint "
                "uses that joint.</i>"
            )
        )
        form = QFormLayout()
        unit = f" ({length_unit})" if length_unit else ""
        self._fields: list[FloatField] = []
        for axis, value in (("dX", 0.0), ("dY", 0.0), ("dZ", 3.0)):
            field = FloatField()
            field.setRange(-1e9, 1e9)
            field.setSingleStep(1.0)
            field.setValue(value)
            self._fields.append(field)
            form.addRow(f"{axis}{unit}:", field)
        self._count = QSpinBox()
        self._count.setRange(1, 200)
        self._count.setValue(1)
        form.addRow("Number of steps:", self._count)
        self._section = QComboBox()
        for section_id, name in sections:
            self._section.addItem(name, section_id)
        form.addRow("Plate section:" if into_shells else "Frame section:", self._section)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not any(abs(v) > 0.0 for v in self.offset()):
            QMessageBox.warning(self, "Extrude", "Enter a non-zero offset.")
            return
        self.accept()

    def offset(self) -> tuple[float, float, float]:
        dx, dy, dz = (field.value() for field in self._fields)
        return (dx, dy, dz)

    def set_offset(self, dx: float, dy: float, dz: float) -> None:
        for field, value in zip(self._fields, (dx, dy, dz), strict=True):
            field.setValue(value)

    def count(self) -> int:
        return self._count.value()

    def set_count(self, count: int) -> None:
        self._count.setValue(count)

    def section_id(self) -> int:
        return int(self._section.currentData())
