"""Move dialog — translate selected nodes in place by an offset vector."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog


class MoveDialog(FittedDialog):
    """Dialog for an (dx, dy, dz) translation."""

    def __init__(self, n_nodes: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def offset(self) -> tuple[float, float, float]:
        return (self._dx.value(), self._dy.value(), self._dz.value())
