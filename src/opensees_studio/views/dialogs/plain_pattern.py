"""Add Plain load pattern dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import PlainLoadPattern, Project


class PlainPatternDialog(QDialog):
    """Modal dialog: create an empty ``pattern Plain`` linked to a TimeSeries."""

    def __init__(
        self,
        project: Project,
        next_pattern_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Plain Load Pattern")
        self._project = project
        self._next_id = next_pattern_id
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit("Pattern")
        form.addRow("Name:", self._name_edit)

        self._ts_cb = QComboBox()
        for ts in self._project.time_series:
            label = f"#{ts.id}  {ts.name or ts.type}  [{ts.type}]"
            self._ts_cb.addItem(label, ts.id)
        form.addRow("TimeSeries:", self._ts_cb)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def pattern(self) -> PlainLoadPattern:
        ts_id = self._ts_cb.currentData()
        if ts_id is None:
            raise ValueError("No TimeSeries selected.")
        return PlainLoadPattern(
            id=self._next_id,
            name=self._name_edit.text().strip() or "Pattern",
            time_series_id=int(ts_id),
        )
