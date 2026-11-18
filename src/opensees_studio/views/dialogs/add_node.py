"""Add Node dialog — create a single node at an arbitrary (x, y, z).

Used for manual node placement when the user wants a node somewhere
that isn't already a grid intersection. The 'Snap to nearest grid
intersection' checkbox rounds the entered coordinates to the closest
values in the project's :class:`GridSystem` — handy for precise
placement without having to type exact numbers.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Node
from opensees_studio.core.geometry import GridSystem
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog


class AddNodeDialog(FittedDialog):
    """Create one :class:`Node` at (x, y, z) optionally snapped to grid."""

    def __init__(
        self, next_node_id: int, grid: GridSystem, ndm: int = 3, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Node")
        self._next_id = next_node_id
        self._grid = grid
        self._ndm = ndm
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"<b>Node {self._next_id}</b> — enter coordinates:"))

        form = QFormLayout()
        self._x = self._spin()
        self._y = self._spin()
        self._z = self._spin()
        form.addRow("X:", self._x)
        if self._ndm == 3:
            form.addRow("Y:", self._y)
        else:
            # A 2D model lives in the X-Z plane (core.plane): no Y.
            self._y.setVisible(False)
        form.addRow("Z:", self._z)
        root.addLayout(form)

        self._snap_cb = QCheckBox("Snap to nearest grid intersection")
        self._snap_cb.setChecked(
            bool(self._grid.x_lines or self._grid.y_lines or self._grid.z_lines)
        )
        root.addWidget(self._snap_cb)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _spin() -> FloatField:
        sb = FloatField()
        sb.setRange(-1e9, 1e9)
        sb.setSingleStep(0.5)
        sb.setValue(0.0)
        return sb

    def node(self) -> Node:
        """Return the constructed Node (snapped if requested)."""
        x, y, z = self._x.value(), self._y.value(), self._z.value()
        if self._snap_cb.isChecked():
            x, y, z = self._grid.snap_local((x, y, z))
        if self._ndm == 2:
            y = 0.0
        return Node(id=self._next_id, coords=(x, y, z))
