"""Assign Hinge dialog — convert selected elements to BeamWithHinges.

The user picks:
- Hinge section for end-i and end-j (from the project's sections list)
- Plastic-hinge lengths Lp_i and Lp_j
- Elastic interior properties are auto-read from the element's current
  section (if it's an ElasticSection) or entered manually.

On accept, the dialog returns the parameters needed to create a
:class:`BeamWithHingesElement` for each selected element.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Project


class AssignHingeDialog(QDialog):
    """Modal dialog: configure BeamWithHinges parameters."""

    def __init__(self, n_selected: int, project: Project,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Plastic Hinges")
        self._project = project
        self._build_ui(n_selected)

    def _build_ui(self, n_selected: int) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"Convert <b>{n_selected}</b> selected element(s) to BeamWithHinges.",
        ))

        form = QFormLayout()
        # Hinge section pickers
        self._sec_i = QComboBox()
        self._sec_j = QComboBox()
        for sec in self._project.sections:
            label = f"#{sec.id}  {sec.name or sec.type}"
            self._sec_i.addItem(label, sec.id)
            self._sec_j.addItem(label, sec.id)
        form.addRow("Section end-i:", self._sec_i)
        form.addRow("Section end-j:", self._sec_j)

        # Plastic-hinge lengths
        self._lp_i = QDoubleSpinBox()
        self._lp_i.setRange(1e-6, 100.0)
        self._lp_i.setDecimals(4)
        self._lp_i.setValue(0.1)
        self._lp_i.setSingleStep(0.01)
        form.addRow("Lp_i (hinge length i):", self._lp_i)

        self._lp_j = QDoubleSpinBox()
        self._lp_j.setRange(1e-6, 100.0)
        self._lp_j.setDecimals(4)
        self._lp_j.setValue(0.1)
        self._lp_j.setSingleStep(0.01)
        form.addRow("Lp_j (hinge length j):", self._lp_j)

        # Elastic interior properties
        form.addRow(QLabel("<b>Elastic interior:</b>"))
        self._E = self._dspin(200e9, 1e6)
        self._A = self._dspin(0.01, 0.001)
        self._Iz = self._dspin(1e-4, 1e-6)
        self._Iy = self._dspin(1e-4, 1e-6)
        self._G = self._dspin(80e9, 1e6)
        self._J = self._dspin(1e-5, 1e-7)
        form.addRow("E:", self._E)
        form.addRow("A:", self._A)
        form.addRow("Iz:", self._Iz)
        form.addRow("Iy:", self._Iy)
        form.addRow("G:", self._G)
        form.addRow("J:", self._J)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _dspin(default: float, step: float) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(1e-15, 1e15)
        sb.setDecimals(6)
        sb.setSingleStep(step)
        sb.setValue(default)
        return sb

    def values(self) -> dict:
        """Return hinge parameters as a dict."""
        return {
            "section_i_id": self._sec_i.currentData(),
            "section_j_id": self._sec_j.currentData(),
            "lp_i": self._lp_i.value(),
            "lp_j": self._lp_j.value(),
            "E": self._E.value(),
            "A": self._A.value(),
            "Iz": self._Iz.value(),
            "Iy": self._Iy.value(),
            "G": self._G.value(),
            "J": self._J.value(),
        }
