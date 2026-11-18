"""Table of the node reactions of the case currently displayed.

The bottom dock swaps with Console and Results, so the numbers are two clicks
away without covering the model. The rows come from ``core.reactions`` — the
same function the viewport arrows use, so the table and the picture cannot
disagree about which force belongs to which joint.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.project import Project
from opensees_studio.core.reactions import ReactionRow, reaction_rows

HEADERS = ("Node", "Fx", "Fy", "Fz", "Mx", "My", "Mz")


def _cell(value: float) -> QTableWidgetItem:
    """A read-only number, right aligned, short enough to read."""
    item = QTableWidgetItem(f"{value:.6g}")
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


class ReactionsPanel(QWidget):
    """Every restrained node of the shown case, with its six components."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._title = QLabel("<i>(no results yet)</i>")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)
        self._table = QTableWidget(0, len(HEADERS), self)
        self._table.setHorizontalHeaderLabels([str(header) for header in HEADERS])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table, 1)

    # ── data ────────────────────────────────────────────────────────
    def show_results(self, results: Any | None, project: Project | None) -> None:
        """Fill the table from the results the viewport is showing."""
        self.set_rows(
            reaction_rows(project, getattr(results, "node_reaction", None))
            if results is not None and project is not None
            else []
        )

    def set_rows(self, rows: list[ReactionRow]) -> None:
        self._table.setRowCount(0)
        if not rows:
            self._title.setText("<i>(no reactions in this case)</i>")
            return
        self._title.setText(
            f"{len(rows)} restrained node(s) · global units · final step of the case"
        )
        self._table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            self._table.setItem(index, 0, _cell(float(row.node_id)))
            for column, value in enumerate((*row.forces, *row.moments), start=1):
                self._table.setItem(index, column, _cell(float(value)))

    @property
    def rows(self) -> int:
        """How many reactions the table is showing (used by the tests)."""
        return self._table.rowCount()
