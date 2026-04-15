"""Assign Load dialog — apply nodal force/moment vector to selected nodes."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class AssignLoadDialog(QDialog):
    """Modal dialog for entering a 6-component force vector."""

    def __init__(self, n_selected: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Nodal Load")
        self._build_ui(n_selected)

    def _build_ui(self, n_selected: int) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Apply to <b>{n_selected}</b> selected node(s)."))

        form = QFormLayout()
        self._spinboxes: dict[str, QDoubleSpinBox] = {}
        for label in ("Fx", "Fy", "Fz", "Mx", "My", "Mz"):
            sb = QDoubleSpinBox()
            sb.setRange(-1e12, 1e12)
            sb.setDecimals(4)
            sb.setSingleStep(1.0)
            sb.setValue(0.0)
            self._spinboxes[label] = sb
            form.addRow(f"{label}:", sb)
        layout.addLayout(form)

        layout.addWidget(QLabel(
            "<i>The load goes into the active Plain pattern; if none "
            "exists a default pattern + LinearTimeSeries are created.</i>"
        ))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def forces(self) -> tuple[float, float, float, float, float, float]:
        return tuple(self._spinboxes[k].value() for k in ("Fx", "Fy", "Fz", "Mx", "My", "Mz"))  # type: ignore[return-value]
