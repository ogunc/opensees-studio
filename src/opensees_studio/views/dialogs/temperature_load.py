"""Assign → Frame → Temperature Load: a uniform change and gradients across the section."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog

#: Coefficient of thermal expansion of structural steel and of concrete, 1/°C.
DEFAULT_ALPHA = 1.2e-5


class AssignTemperatureLoadDialog(FittedDialog):
    """Enter α, the uniform temperature change and the gradients along local y and z."""

    def __init__(self, n_selected: int, *, ndm: int = 3, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Temperature Load")
        self.setProperty(TOPIC_PROPERTY, "assign.temperature_load")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Apply to <b>{n_selected}</b> selected member(s)."))
        form = QFormLayout()
        self._alpha = FloatField()
        self._alpha.setRange(1e-12, 1.0)
        self._alpha.setValue(DEFAULT_ALPHA)
        self._alpha.setToolTip(
            "Coefficient of thermal expansion (steel and concrete: about 1.2e-5 /°C)."
        )
        form.addRow("α (1/°):", self._alpha)
        self._uniform = FloatField()
        self._uniform.setRange(-1e4, 1e4)
        self._uniform.setToolTip("Temperature change of the whole section (positive = heating).")
        form.addRow("Uniform ΔT (°):", self._uniform)
        self._gradient_y = FloatField()
        self._gradient_y.setRange(-1e9, 1e9)
        self._gradient_y.setToolTip(
            "Temperature difference per unit depth along local y (+y face minus -y face). "
            "A horizontal member's top face is +y in 2D, +z in 3D."
        )
        form.addRow("Gradient along local y (°/length):", self._gradient_y)
        self._gradient_z = FloatField()
        self._gradient_z.setRange(-1e9, 1e9)
        self._gradient_z.setToolTip("Temperature difference per unit depth along local z.")
        if ndm == 3:
            form.addRow("Gradient along local z (°/length):", self._gradient_z)
        layout.addLayout(form)
        layout.addWidget(
            QLabel(
                "<i>Elastic members without releases or end offsets, in static cases. The "
                "load goes into the active Plain pattern (a default one is created if there "
                "is none).</i>"
            )
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, float]:
        return {
            "alpha": self._alpha.value(),
            "uniform": self._uniform.value(),
            "gradient_y": self._gradient_y.value(),
            "gradient_z": self._gradient_z.value(),
        }
