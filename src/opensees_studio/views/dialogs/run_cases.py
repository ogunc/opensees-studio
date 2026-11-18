"""Analyze → Run Selected Cases: pick which cases run, then run them together.

The single-case dialog (``RunAnalysisDialog``) is for watching one run with its
damping overrides. This one is the batch door: a checkbox per analysis case, a
Select all / none pair, and one child process that runs the ticked cases.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Project
from opensees_studio.views.screen_fit import FittedDialog


class RunCasesDialog(FittedDialog):
    """Choose analysis cases to run in one batch."""

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run Selected Cases")
        self.resize(520, 400)
        self._list = QListWidget()
        for case in project.analyses:
            item = QListWidgetItem(f"#{case.id}  {case.name or '(unnamed)'}  [{case.type}]")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, case.id)
            self._list.addItem(item)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Cases to run (all checked by default):"))
        layout.addWidget(self._list, stretch=1)

        row = QHBoxLayout()
        all_btn = QPushButton("Select all")
        all_btn.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        none_btn = QPushButton("Select none")
        none_btn.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        row.addWidget(all_btn)
        row.addWidget(none_btn)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, state: Qt.CheckState) -> None:
        for row in range(self._list.count()):
            self._list.item(row).setCheckState(state)

    def selected_case_ids(self) -> list[int]:
        """The ids of the ticked cases, in list order."""
        chosen: list[int] = []
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                chosen.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return chosen
