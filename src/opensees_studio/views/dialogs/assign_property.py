"""Frame assignment dialogs: section, material, geometric transformation, integration."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import BEAM_INTEGRATION_RULES, GEOM_TRANSF_TYPES
from opensees_studio.views.screen_fit import FittedDialog


class AssignSectionDialog(FittedDialog):
    def __init__(self, sections: list, n_elements: int, parent: QWidget | None = None) -> None:  # type: ignore[type-arg]
        super().__init__(parent)
        self.setWindowTitle("Assign Section")
        self._sections = sections
        self._build_ui(n_elements)

    def _build_ui(self, n_elements: int) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Apply section to <b>{n_elements}</b> selected frame element(s)."))

        if not self._sections:
            layout.addWidget(
                QLabel("<i>No sections defined. Open Define → Section Library first.</i>")
            )

        self._combo = QComboBox()
        for s in self._sections:
            self._combo.addItem(f"#{s.id}  {s.name or '(unnamed)'}  [{s.type}]", userData=s.id)
        layout.addWidget(self._combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setEnabled(bool(self._sections))

    def section_id(self) -> int:
        return int(self._combo.currentData())


class AssignMaterialDialog(FittedDialog):
    def __init__(self, materials: list, n_elements: int, parent: QWidget | None = None) -> None:  # type: ignore[type-arg]
        super().__init__(parent)
        self.setWindowTitle("Assign Material")
        self._materials = materials
        self._build_ui(n_elements)

    def _build_ui(self, n_elements: int) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(f"Apply material to <b>{n_elements}</b> selected truss/zero-length element(s).")
        )

        if not self._materials:
            layout.addWidget(
                QLabel("<i>No materials defined. Open Define → Material Library first.</i>")
            )

        self._combo = QComboBox()
        for m in self._materials:
            self._combo.addItem(f"#{m.id}  {m.name or '(unnamed)'}  [{m.type}]", userData=m.id)
        layout.addWidget(self._combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self._materials))

    def material_id(self) -> int:
        return int(self._combo.currentData())


class AssignGeomTransfDialog(FittedDialog):
    """Pick the ``geomTransf`` (Linear, PDelta, Corotational) for the selected frames."""

    def __init__(
        self,
        n_frames: int,
        ndm: int,
        current: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Geometric Transformation")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(f"Apply a geometric transformation to <b>{n_frames}</b> selected frame(s).")
        )
        self._combo = QComboBox()
        self._combo.addItems(list(GEOM_TRANSF_TYPES))
        self._combo.setCurrentText(current or "Linear")
        layout.addWidget(self._combo)
        if ndm == 3:
            note = QLabel(
                "vecxz is chosen per element from its axis: (1, 0, 0) for an element "
                "closer to global Z, else (0, 0, 1)."
            )
            note.setWordWrap(True)
            layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(n_frames > 0)

    def transf_type(self) -> str:
        return self._combo.currentText()


class AssignBeamIntegrationDialog(FittedDialog):
    """Pick the ``beamIntegration`` rule and point count for force/displacement beam-columns."""

    def __init__(
        self,
        n_frames: int,
        rule: str | None = None,
        points: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Beam Integration")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(f"Integration of <b>{n_frames}</b> selected force/displacement beam-column(s).")
        )
        form = QFormLayout()
        self._rule = QComboBox()
        self._rule.addItems(list(BEAM_INTEGRATION_RULES))
        self._rule.setCurrentText(rule or "Lobatto")
        form.addRow("Rule:", self._rule)
        self._points = QSpinBox()
        self._points.setRange(2, 10)
        self._points.setValue(points or 5)
        form.addRow("Integration points:", self._points)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(n_frames > 0)

    def rule(self) -> str:
        return self._rule.currentText()

    def points(self) -> int:
        return self._points.value()
