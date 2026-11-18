"""File → Project Information: the cover data of the calculation report."""

from __future__ import annotations

import datetime as _dt

from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.project import ProjectMeta, Revision
from opensees_studio.views.screen_fit import FittedDialog


class ProjectInfoDialog(FittedDialog):
    """Edits the project, author, company, date and revision table."""

    def __init__(self, meta: ProjectMeta, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._units = meta.units
        self.setWindowTitle("Project Information")
        self.setProperty(TOPIC_PROPERTY, "file.project_info")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "These values are the cover of the calculation report: project, "
                "author, company, date and the revision history."
            )
        )
        form = QFormLayout()
        self._name = QLineEdit(meta.name)
        form.addRow("Project:", self._name)
        self._author = QLineEdit(meta.author)
        form.addRow("Author:", self._author)
        self._company = QLineEdit(meta.company)
        form.addRow("Company:", self._company)
        self._date = QLineEdit(meta.date or _dt.date.today().isoformat())
        self._date.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Date:", self._date)
        self._description = QPlainTextEdit(meta.description)
        self._description.setFixedHeight(60)
        form.addRow("Description:", self._description)
        layout.addLayout(form)

        layout.addWidget(QLabel("Revisions:"))
        self._revisions = QTableWidget(0, 4)
        self._revisions.setHorizontalHeaderLabels(["Rev", "Date", "By", "Description"])
        self._revisions.horizontalHeader().setStretchLastSection(True)
        self._revisions.setMinimumHeight(110)
        layout.addWidget(self._revisions)
        row = QHBoxLayout()
        add = QPushButton("Add revision")
        add.clicked.connect(self._add_revision)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove_revision)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for revision in meta.revisions:
            self._append(revision)

    def _append(self, revision: Revision | None = None) -> None:
        row = self._revisions.rowCount()
        self._revisions.insertRow(row)
        values = (
            revision.code if revision else "",
            revision.date if revision else "",
            revision.by if revision else "",
            revision.description if revision else "",
        )
        for column, value in enumerate(values):
            self._revisions.setItem(row, column, QTableWidgetItem(value))

    def _add_revision(self) -> None:
        self._append()

    def _remove_revision(self) -> None:
        row = self._revisions.currentRow()
        if row >= 0:
            self._revisions.removeRow(row)

    def _cell(self, row: int, column: int) -> str:
        item = self._revisions.item(row, column)
        return item.text().strip() if item is not None else ""

    def meta(self) -> ProjectMeta:
        """The metadata as the dialog shows it, with the units untouched."""
        revisions = []
        for row in range(self._revisions.rowCount()):
            code = self._cell(row, 0)
            if not code:
                continue
            revisions.append(
                Revision(
                    code=code,
                    date=self._cell(row, 1),
                    by=self._cell(row, 2),
                    description=self._cell(row, 3),
                )
            )
        return ProjectMeta(
            name=self._name.text().strip() or "Untitled",
            description=self._description.toPlainText().strip(),
            author=self._author.text().strip(),
            company=self._company.text().strip(),
            date=self._date.text().strip(),
            revisions=revisions,
            units=self._units,
        )
