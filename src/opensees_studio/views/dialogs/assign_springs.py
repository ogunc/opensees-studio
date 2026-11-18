"""Assign → Joint → Springs: elastic support springs to ground on the selected joints.

One stiffness per DOF of the model (a 2D frame: Ux, Uz, Ry), in force per length
or moment per radian. OK replaces the springs of every selected joint; all zero
removes them.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from opensees_studio.core.plane import dof_indices, dof_labels
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog


class AssignSpringsDialog(FittedDialog):
    """Stiffness of the support spring in each DOF of the model."""

    def __init__(
        self,
        n_selected: int,
        ndm: int,
        ndf: int,
        current: tuple[float, ...] | None = None,
        units: tuple[str, str] = ("force/length", "moment/rad"),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Support Springs")
        self._slots = dof_indices(ndm, ndf)
        current = current or (0.0,) * 6
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                f"Springs to ground on <b>{n_selected}</b> selected joint(s). "
                "Zero means no spring; a restrained DOF ignores its spring."
            )
        )
        form = QFormLayout()
        self.fields: dict[int, FloatField] = {}
        for slot, label in zip(self._slots, dof_labels(ndm, ndf), strict=True):
            field = FloatField()
            field.setRange(0.0, 1e300)
            field.setValue(float(current[slot]))
            unit = units[0] if label.startswith("U") else units[1]
            form.addRow(f"k {label} [{unit}]:", field)
            self.fields[slot] = field
        root.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def spring_vector(self) -> tuple[float, float, float, float, float, float]:
        """The 6-tuple (kx, ky, kz, krx, kry, krz); DOFs the model lacks are 0."""
        values = [0.0] * 6
        for slot, field in self.fields.items():
            values[slot] = float(field.value())
        return (values[0], values[1], values[2], values[3], values[4], values[5])
