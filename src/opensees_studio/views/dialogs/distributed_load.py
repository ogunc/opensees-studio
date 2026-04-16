"""Assign Distributed Load dialog — uniform line-load for selected elements."""

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


class AssignDistributedLoadDialog(QDialog):
    """Modal dialog for entering uniform distributed loads (wy, wz, wx).

    Components are in the **element local frame** (local y / z / x axes).
    Convention: positive wy = force in +local-y direction per unit length.
    """

    def __init__(self, n_selected: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Distributed Load")
        self._build_ui(n_selected)

    def _build_ui(self, n_selected: int) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Apply to <b>{n_selected}</b> selected element(s)."))

        form = QFormLayout()
        self._spinboxes: dict[str, QDoubleSpinBox] = {}
        for label, tip in (
            ("wx", "Load per length in local-x (axial)"),
            ("wy", "Load per length in local-y (transverse, in-plane for 2D)"),
            ("wz", "Load per length in local-z (out-of-plane for 2D)"),
        ):
            sb = QDoubleSpinBox()
            sb.setRange(-1e12, 1e12)
            sb.setDecimals(4)
            sb.setSingleStep(1.0)
            sb.setValue(0.0)
            sb.setToolTip(tip)
            self._spinboxes[label] = sb
            form.addRow(f"{label}:", sb)
        layout.addLayout(form)

        layout.addWidget(QLabel(
            "<i>All values are force per unit length in the element's "
            "local frame. The load goes into the active Plain pattern; "
            "if none exists a default pattern is created.</i>",
        ))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[float, float, float]:
        """Return (wy, wz, wx)."""
        return (self._spinboxes["wy"].value(),
                self._spinboxes["wz"].value(),
                self._spinboxes["wx"].value())
