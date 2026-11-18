"""Design → Column Splices: the SCBF column splices of the project."""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.design.column_splice_model import ColumnSplice
from opensees_studio.core.geometry.elements import FRAME_ELEMENT_CLASSES
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog


class ColumnSplicesDialog(FittedDialog):
    """Lists, adds, edits and removes SCBF column splices."""

    def __init__(self, project: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._items = [splice.model_copy() for splice in project.column_splices]
        self._sections = {s.id: s for s in project.sections}
        self._elements = {e.id: e for e in project.elements if isinstance(e, FRAME_ELEMENT_CLASSES)}
        self._coords = {n.id: n.coords for n in project.nodes}
        self._columns = {
            element_id: element
            for element_id, element in self._elements.items()
            if self._is_column(element)
        }
        self.setWindowTitle("Column Splices - AISC 341-22")
        self.setProperty(TOPIC_PROPERTY, "design.column_splices")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "SCBF column splices (AISC 341-22 F2.6d). The splice develops at "
                "least 50% of the lesser plastic moment of the two column segments "
                "divided by alpha_s, and carries (Mp_top + Mp_bottom)/(alpha_s Hc)."
            )
        )
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Splice", "Node", "Top", "Bottom", "Hc"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setMinimumHeight(130)
        self._table.itemSelectionChanged.connect(self._load_selected)
        layout.addWidget(self._table)

        form = QFormLayout()
        self._node = QComboBox()
        for node in sorted(project.nodes, key=lambda n: n.id):
            self._node.addItem(str(node.id), node.id)
        self._node.currentIndexChanged.connect(self._on_node_changed)
        form.addRow("Splice node:", self._node)
        self._top = QComboBox()
        self._bottom = QComboBox()
        form.addRow("Top column element:", self._top)
        form.addRow("Bottom column element:", self._bottom)
        self._height = FloatField()
        self._height.setRange(1e-6, 1e9)
        form.addRow("Clear height Hc:", self._height)
        layout.addLayout(form)

        row = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        update = QPushButton("Update selected")
        update.clicked.connect(self._update)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(update)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()
        self._on_node_changed()

    def _is_column(self, element: Any) -> bool:
        start = self._coords[element.nodes[0]]
        end = self._coords[element.nodes[1]]
        delta = [float(end[k]) - float(start[k]) for k in range(3)]
        length = math.hypot(*delta)
        return length > 0.0 and abs(delta[2]) / length >= 0.8

    def _section_name(self, element_id: int) -> str:
        element = self._elements.get(element_id)
        section = self._sections.get(getattr(element, "section_id", -1))
        return getattr(section, "name", "") or "no section"

    def _at_node(self, node_id: int) -> list[int]:
        return sorted(
            element_id for element_id, element in self._columns.items() if node_id in element.nodes
        )

    def _on_node_changed(self) -> None:
        node_id = int(self._node.currentData()) if self._node.count() else 0
        candidates = self._at_node(node_id)
        for combo in (self._top, self._bottom):
            combo.blockSignals(True)
            combo.clear()
            for element_id in candidates:
                combo.addItem(f"{element_id} ({self._section_name(element_id)})", element_id)
            combo.blockSignals(False)
        if len(candidates) >= 2:
            self._top.setCurrentIndex(0)
            self._bottom.setCurrentIndex(1)
        if candidates:
            element = self._elements[candidates[0]]
            start = self._coords[element.nodes[0]]
            end = self._coords[element.nodes[1]]
            self._height.setValue(math.dist(start, end))

    def _next_id(self) -> int:
        used = {item.id for item in self._items}
        return max(used, default=0) + 1

    def _candidate(self) -> ColumnSplice | None:
        if not self._top.count() or not self._bottom.count():
            QMessageBox.warning(
                self,
                "Column splices",
                "The selected node needs two column elements.",
            )
            return None
        top_id = int(self._top.currentData())
        bottom_id = int(self._bottom.currentData())
        if top_id == bottom_id:
            QMessageBox.warning(self, "Column splices", "The top and bottom are the same element.")
            return None
        return ColumnSplice(
            id=self._next_id(),
            node_id=int(self._node.currentData()),
            top_element_id=top_id,
            bottom_element_id=bottom_id,
            clear_height=self._height.value(),
        )

    def _add(self) -> None:
        candidate = self._candidate()
        if candidate is not None:
            self._items.append(candidate)
            self._refresh()

    def _update(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        candidate = self._candidate()
        if candidate is None:
            return
        candidate.id = self._items[row].id
        self._items[row] = candidate
        self._refresh()

    def _remove(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            del self._items[row]
            self._refresh()

    def _refresh(self) -> None:
        self._table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            values = (
                item.id,
                item.node_id,
                f"{item.top_element_id} ({self._section_name(item.top_element_id)})",
                f"{item.bottom_element_id} ({self._section_name(item.bottom_element_id)})",
                item.clear_height,
            )
            for column, value in enumerate(values):
                self._table.setItem(row, column, QTableWidgetItem(str(value)))
        self._summary.setText(f"{len(self._items)} column splice(s).")

    def _load_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._items):
            return
        item = self._items[row]
        index = self._node.findData(item.node_id)
        if index >= 0:
            self._node.setCurrentIndex(index)
        self._on_node_changed()
        for combo, value in (
            (self._top, item.top_element_id),
            (self._bottom, item.bottom_element_id),
        ):
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        self._height.setValue(item.clear_height)

    def splices(self) -> list[ColumnSplice]:
        """The splices as the dialog shows them."""
        return [item.model_copy() for item in self._items]
