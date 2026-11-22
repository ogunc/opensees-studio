"""Move dialog — translate selected nodes in place by an offset vector."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.views.float_field import FloatField, format_float
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

if TYPE_CHECKING:
    from opensees_studio.views.tools.measure import Measurement


class MoveDialog(FittedDialog):
    """Dialog for an (dx, dy, dz) translation."""

    measureRequested = Signal()

    def __init__(
        self,
        n_nodes: int,
        parent: QWidget | None = None,
        *,
        length_unit: str = "",
    ) -> None:
        super().__init__(parent)
        self._length_unit = length_unit
        self.setWindowTitle("Move")
        self._build_ui(n_nodes)

    def _build_ui(self, n_nodes: int) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Move <b>{n_nodes}</b> selected node(s)."))
        layout.addWidget(QLabel("<i>Element connectivity is preserved.</i>"))

        form = QFormLayout()

        def _spin() -> FloatField:
            sb = FloatField()
            sb.setRange(-1e9, 1e9)
            sb.setSingleStep(1.0)
            return sb

        self._dx, self._dy, self._dz = _spin(), _spin(), _spin()
        form.addRow("dX:", self._dx)
        form.addRow("dY:", self._dy)
        form.addRow("dZ:", self._dz)
        layout.addLayout(form)

        self._message = MessageArea()
        self._message.show_message(
            "Tip: Measure… picks two joints in the viewport; their ΔX, ΔY, ΔZ fill the fields."
        )
        layout.addWidget(self._message)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._measure_button = buttons.addButton("Measure…", QDialogButtonBox.ButtonRole.ActionRole)
        self._measure_button.setToolTip(
            "Pick two joints on the canvas (also F7 with the viewport focused); "
            "their ΔX, ΔY, ΔZ fill the fields."
        )
        self._measure_button.clicked.connect(lambda _checked=False: self.measureRequested.emit())
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def offset(self) -> tuple[float, float, float]:
        return (self._dx.value(), self._dy.value(), self._dz.value())

    def set_offset(self, dx: float, dy: float, dz: float) -> None:
        """Put an offset in the fields (the Measure button fills them this way)."""
        for field, value in zip((self._dx, self._dy, self._dz), (dx, dy, dz), strict=True):
            field.setValue(value)

    def set_measurement(self, measurement: Measurement) -> None:
        """Fill the fields with the vector between the two measured joints."""
        dx, dy, dz = measurement.delta
        self.set_offset(dx, dy, dz)
        unit = f" {self._length_unit}" if self._length_unit else ""
        self._message.show_message(
            f"Measured {measurement.distance:.10g}{unit}: "
            f"dX={format_float(dx)}, dY={format_float(dy)}, dZ={format_float(dz)}."
        )
