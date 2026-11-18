"""Edit → Interactive Table Editing: joints, elements and joint loads as spreadsheets.

Each tab is a :class:`SpreadsheetTable` built from :func:`core.model_tables.model_tables`.
Cells are plain text; Ctrl+C copies the selected block and Ctrl+V pastes a
tab-separated block from Excel at the current cell, adding rows when the table
allows it. OK turns every tab back into a validated copy of the project
(:func:`core.model_tables.apply_tables`) and refuses a bad cell in the message
area; the main window applies ``edited`` as one undo step.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Project
from opensees_studio.core.model_tables import Table, apply_tables, model_tables
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

_GREY = Qt.GlobalColor.lightGray


class SpreadsheetTable(QTableWidget):
    """A table of text cells with Excel-style copy, paste, add and delete."""

    def __init__(self, table: Table, parent: QWidget | None = None) -> None:
        super().__init__(len(table.rows), len(table.columns), parent)
        self.spec = table
        self.setHorizontalHeaderLabels(list(table.columns))
        self.verticalHeader().setVisible(False)
        for r, row in enumerate(table.rows):
            for c, text in enumerate(row):
                self.setItem(r, c, self._item(c, text))
        self.resizeColumnsToContents()

    def _item(self, column: int, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if not self.spec.editable[column]:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setForeground(_GREY)
        return item

    def rows(self) -> list[list[str]]:
        out = []
        for r in range(self.rowCount()):
            row = []
            for c in range(self.columnCount()):
                item = self.item(r, c)
                row.append(item.text() if item is not None else "")
            out.append(row)
        return out

    def add_row(self) -> None:
        r = self.rowCount()
        self.insertRow(r)
        for c in range(self.columnCount()):
            self.setItem(r, c, self._item(c, ""))
        self.setCurrentCell(r, 0)

    def delete_rows(self) -> None:
        for r in sorted({i.row() for i in self.selectedIndexes()}, reverse=True):
            self.removeRow(r)

    def copy_selection(self) -> None:
        indexes = self.selectedIndexes()
        if not indexes:
            return
        rows = sorted({i.row() for i in indexes})
        cols = sorted({i.column() for i in indexes})
        lines = []
        for r in rows:
            cells = []
            for c in cols:
                item = self.item(r, c)
                cells.append(item.text() if item is not None else "")
            lines.append("\t".join(cells))
        QGuiApplication.clipboard().setText("\n".join(lines))

    def paste(self, text: str | None = None) -> None:
        """Paste a tab-separated block at the current cell, over editable cells only."""
        text = QGuiApplication.clipboard().text() if text is None else text
        lines = [line for line in text.replace("\r\n", "\n").split("\n")]
        while lines and not lines[-1]:
            lines.pop()
        top, left = max(self.currentRow(), 0), max(self.currentColumn(), 0)
        for k, line in enumerate(lines):
            r = top + k
            if r >= self.rowCount():
                if not self.spec.can_add_rows:
                    break
                self.add_row()
            for j, value in enumerate(line.split("\t")):
                c = left + j
                if c < self.columnCount() and self.spec.editable[c]:
                    self.setItem(r, c, self._item(c, value.strip()))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
        elif event.matches(QKeySequence.StandardKey.Paste):
            self.paste()
        elif event.key() == Qt.Key.Key_Delete and self.state() != self.State.EditingState:
            for index in self.selectedIndexes():
                if self.spec.editable[index.column()]:
                    self.setItem(index.row(), index.column(), self._item(index.column(), ""))
        else:
            super().keyPressEvent(event)


class ModelTablesDialog(FittedDialog):
    """Joints, elements and joint loads, edited as spreadsheets and applied at once."""

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Interactive Table Editing")
        self._project = project
        self.edited: Project | None = None
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "Edit cells, paste blocks from a spreadsheet (Ctrl+V), add or delete rows. "
                "Restraints are 1 (fixed) or 0 (free); a new joint with no ID gets the next one. "
                "Nothing changes until OK, and OK is one undo step."
            )
        )
        self.tabs = QTabWidget()
        self.tables: dict[str, SpreadsheetTable] = {}
        for table in model_tables(project):
            widget = SpreadsheetTable(table)
            self.tables[table.name] = widget
            self.tabs.addTab(widget, f"{table.name} ({len(table.rows)})")
        root.addWidget(self.tabs)

        row = QHBoxLayout()
        self.add_button = QPushButton("Add Row")
        self.add_button.clicked.connect(lambda: self.current.add_row())
        self.delete_button = QPushButton("Delete Rows")
        self.delete_button.clicked.connect(lambda: self.current.delete_rows())
        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(lambda: self.current.copy_selection())
        self.paste_button = QPushButton("Paste")
        self.paste_button.clicked.connect(lambda: self.current.paste())
        for button in (self.add_button, self.delete_button, self.copy_button, self.paste_button):
            row.addWidget(button)
        row.addStretch(1)
        root.addLayout(row)
        self.tabs.currentChanged.connect(self._on_tab)
        self._on_tab()

        self.message = MessageArea()
        root.addWidget(self.message)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        self.resize(900, 600)

    @property
    def current(self) -> SpreadsheetTable:
        widget = self.tabs.currentWidget()
        assert isinstance(widget, SpreadsheetTable)
        return widget

    def _on_tab(self) -> None:
        self.add_button.setEnabled(self.current.spec.can_add_rows)

    def accept(self) -> None:
        try:
            self.edited = apply_tables(
                self._project, {name: t.rows() for name, t in self.tables.items()}
            )
        except ValueError as exc:
            self.message.show_message(str(exc), "error")
            return
        super().accept()
