"""Assign Zero-Length Section dialog — wrap two coincident joints
with a Section.

SAP2000 has no direct equivalent (it uses link elements), but for
OpenSees this is how moment-curvature fibres and some base-isolator
models are built: select two nodes sharing the same coordinates,
pick a section, commit.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Project


class AssignZeroLengthSectionDialog(QDialog):
    """Modal dialog: pick a section, confirm creation between 2 nodes."""

    def __init__(self, project: Project, node_ids: tuple[int, int],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Zero-Length Section")
        self._project = project
        self._node_ids = node_ids
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            f"Connect node <b>{self._node_ids[0]}</b> and "
            f"<b>{self._node_ids[1]}</b> through a zero-length "
            "section element. The two nodes must share the same "
            "coordinates."
        ))

        form = QFormLayout()
        self._section_cb = QComboBox()
        for sec in self._project.sections:
            self._section_cb.addItem(f"#{sec.id}  {sec.name or sec.type}", sec.id)
        if not self._project.sections:
            self._section_cb.addItem("(no sections defined)", None)
            self._section_cb.setEnabled(False)
        form.addRow("Section:", self._section_cb)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def section_id(self) -> int | None:
        return self._section_cb.currentData()
