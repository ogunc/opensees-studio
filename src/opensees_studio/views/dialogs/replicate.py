"""Replicate dialog — copy selection by an offset, N times.

The classic "story copy" workflow: select the floor's nodes and
beams, set offset = (0, 0, story_height), n_copies = number_of_floors.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog


class ReplicateDialog(FittedDialog):
    """Dialog for offset (dx, dy, dz) and number of copies."""

    def __init__(self, n_nodes: int, n_elements: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Replicate")
        self._build_ui(n_nodes, n_elements)

    def _build_ui(self, n_nodes: int, n_elements: int) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(f"Replicate <b>{n_nodes}</b> node(s) and <b>{n_elements}</b> element(s).")
        )
        layout.addWidget(
            QLabel("<i>Only elements whose endpoints are both in the selection are copied.</i>")
        )
        layout.addWidget(
            QLabel(
                "<i>Nodal and element loads on the copied nodes and elements come with them; "
                "restraints, masses and ground motions are left where they are.</i>"
            )
        )

        form = QFormLayout()

        def _spin(default: float = 0.0) -> FloatField:
            sb = FloatField()
            sb.setRange(-1e9, 1e9)
            sb.setSingleStep(1.0)
            sb.setValue(default)
            return sb

        self._dx = _spin()
        self._dy = _spin()
        self._dz = _spin(3.0)
        self._n = QSpinBox()
        self._n.setRange(1, 200)
        self._n.setValue(1)

        form.addRow("dX:", self._dx)
        form.addRow("dY:", self._dy)
        form.addRow("dZ:", self._dz)
        form.addRow("Number of copies:", self._n)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def offset(self) -> tuple[float, float, float]:
        return (self._dx.value(), self._dy.value(), self._dz.value())

    def n_copies(self) -> int:
        return self._n.value()
