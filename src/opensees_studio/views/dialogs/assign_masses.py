"""Assign Masses dialog — set translational (+ rotational) mass on selected nodes.

SAP2000 parity: the Assign → Joint → Masses menu item accumulates the
entered values onto each selected node. We follow the simpler "replace"
semantics (set the mass on each selected node to these values) because
it maps cleanly onto our existing :class:`SetMassCommand`.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class AssignMassesDialog(QDialog):
    """Modal dialog: enter translational + rotational mass components."""

    def __init__(
        self,
        n_selected: int,
        ndf: int = 6,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Masses")
        self._ndf = ndf
        self._build_ui(n_selected)

    def _build_ui(self, n_selected: int) -> None:
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            f"Assign mass values to <b>{n_selected}</b> selected node(s).",
        ))

        form = QFormLayout()
        self._mx = self._spin(); form.addRow("Translation X:", self._mx)
        self._my = self._spin(); form.addRow("Translation Y:", self._my)
        if self._ndf >= 3:
            self._mz = self._spin(); form.addRow("Translation Z:", self._mz)
        else:
            self._mz = self._spin()
        if self._ndf == 6:
            self._mxx = self._spin(); form.addRow("Rotation X (Ixx):", self._mxx)
            self._myy = self._spin(); form.addRow("Rotation Y (Iyy):", self._myy)
            self._mzz = self._spin(); form.addRow("Rotation Z (Izz):", self._mzz)
        else:
            self._mxx = self._spin()
            self._myy = self._spin()
            self._mzz = self._spin()
        root.addLayout(form)

        self._xy_link = QCheckBox("Tie translation Y to X (lumped horizontal mass)")
        self._xy_link.toggled.connect(self._on_xy_link)
        root.addWidget(self._xy_link)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _spin() -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(0.0, 1e15)
        sb.setDecimals(6)
        sb.setSingleStep(100.0)
        sb.setValue(0.0)
        return sb

    def _on_xy_link(self, checked: bool) -> None:
        if checked:
            self._my.setValue(self._mx.value())
            self._mx.valueChanged.connect(self._my.setValue)
        else:
            try:
                self._mx.valueChanged.disconnect(self._my.setValue)
            except (RuntimeError, TypeError):
                pass

    def mass_vector(self) -> tuple[float, float, float, float, float, float]:
        """Return the 6-tuple (Mx, My, Mz, Mxx, Myy, Mzz)."""
        return (
            self._mx.value(), self._my.value(), self._mz.value(),
            self._mxx.value(), self._myy.value(), self._mzz.value(),
        )
