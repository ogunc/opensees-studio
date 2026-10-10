"""Check the model for duplicated nodes and elements, and repair what is safe.

The report is the point: it says what is twice, what will be kept, and — just
as important — what is *not* touched and why. Two coincident nodes under a
bearing, or a hinge made of two coincident nodes tied by ``equalDOF``, are
deliberate, and a tool that merged them would quietly delete every isolator in
the model. Those rows appear with the reason instead of a fix.

Fixing is the command's job (:class:`~opensees_studio.commands.FixDuplicatesCommand`),
not the dialog's: the dialog only decides the tolerance and hands it over.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Project
from opensees_studio.core.duplicates import DuplicateReport, check_duplicates, default_tolerance
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

SelectEntities = Callable[[Sequence[int], Sequence[int]], None]


class DuplicatesDialog(FittedDialog):
    """Show what the model defines twice, and fix it on OK."""

    def __init__(
        self,
        project: Project,
        *,
        on_select: SelectEntities | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._on_select = on_select
        self._report = check_duplicates(project, tolerance=default_tolerance(project))
        self.setWindowTitle("Check Model for Duplicates")
        self._build_ui()

    # ── ui ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Nodes at the same point and elements that describe the same member. "
                "<i>Deliberate coincidences — the two nodes of a zero-length element or a "
                "bearing, and nodes tied by an equalDOF constraint — are listed but left "
                "alone.</i>"
            )
        )

        controls = QFormLayout()
        self._tolerance = FloatField()
        self._tolerance.setRange(0.0, 1e9)
        self._tolerance.setValue(self._report.tolerance)
        self._tolerance.setToolTip(
            "Two nodes closer than this are the same node. The default is one part per "
            "million of the model's size."
        )
        self._recheck = QPushButton("Check again")
        self._recheck.clicked.connect(self._refresh)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self._tolerance)
        row_layout.addWidget(self._recheck)
        controls.addRow("Tolerance:", row)
        layout.addLayout(controls)

        self._nodes_table = self._make_table(
            ["Keep", "Duplicates", "Coordinates", "What happens"], self._nodes_changed
        )
        nodes_box = QGroupBox("Coincident nodes")
        nodes_layout = QVBoxLayout(nodes_box)
        nodes_layout.addWidget(self._nodes_table)
        layout.addWidget(nodes_box)

        self._elements_table = self._make_table(
            ["Keep", "Duplicates", "Type", "Nodes", "What happens"], self._elements_changed
        )
        elements_box = QGroupBox("Repeated elements")
        elements_layout = QVBoxLayout(elements_box)
        elements_layout.addWidget(self._elements_table)
        layout.addWidget(elements_box)

        self._summary = MessageArea()
        layout.addWidget(self._summary)

        buttons = QDialogButtonBox()
        self._select_button = buttons.addButton(
            "Select in canvas", QDialogButtonBox.ButtonRole.ActionRole
        )
        self._select_button.clicked.connect(self._select_current)
        self._fix_button = buttons.addButton(
            "Fix duplicates", QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh()

    def _make_table(self, headers: list[str], on_change: Callable[[], None]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.itemSelectionChanged.connect(on_change)
        table.setMinimumHeight(120)
        return table

    # ── data ────────────────────────────────────────────────────────
    def report(self) -> DuplicateReport:
        return self._report

    def tolerance(self) -> float:
        return self._tolerance.value()

    def _refresh(self) -> None:
        self._report = check_duplicates(self._project, tolerance=self._tolerance.value())
        self._fill_nodes()
        self._fill_elements()
        self._summary.show_message(self._report.summary())
        self._fix_button.setEnabled(not self._report.is_clean)
        self._nodes_changed()

    def _fill_nodes(self) -> None:
        rows = [*self._report.node_clusters, *self._report.exempt_clusters]
        table = self._nodes_table
        table.setRowCount(len(rows))
        for row, cluster in enumerate(rows):
            coords = ", ".join(f"{value:g}" for value in cluster.coords)
            note = cluster.exempt_reason or f"merge into node {cluster.keeper_id}"
            cells = [
                str(cluster.keeper_id),
                ", ".join(str(i) for i in cluster.duplicate_ids) or "—",
                coords,
                note,
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if cluster.exempt_reason is not None:
                    item.setForeground(QBrush(Qt.GlobalColor.darkYellow))
                table.setItem(row, column, item)

    def _fill_elements(self) -> None:
        rows = [*self._report.element_clusters, *self._report.parallel_clusters]
        table = self._elements_table
        table.setRowCount(len(rows))
        for row, cluster in enumerate(rows):
            note = (
                "check by hand: same nodes, different properties"
                if cluster.parallel_only
                else f"remove, keep element {cluster.keeper_id}"
            )
            cells = [
                str(cluster.keeper_id),
                ", ".join(str(i) for i in cluster.duplicate_ids) or "—",
                cluster.type,
                ", ".join(str(i) for i in cluster.nodes),
                note,
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if cluster.parallel_only:
                    item.setForeground(QBrush(Qt.GlobalColor.darkYellow))
                table.setItem(row, column, item)

    # ── selection in the canvas ─────────────────────────────────────
    def _current_entities(self) -> tuple[list[int], list[int]]:
        """The keeper and the duplicates of the selected row, if any."""

        def ids_of(table: QTableWidget, columns: tuple[int, ...]) -> list[int]:
            row = table.currentRow()
            if row < 0:
                return []
            found: list[int] = []
            for column in columns:
                item = table.item(row, column)
                if item is None or item.text() == "—":
                    continue
                # The duplicates cell holds a list ("2, 3").
                found.extend(int(part) for part in item.text().replace(",", " ").split())
            return found

        if self._nodes_table.selectedItems():
            return ids_of(self._nodes_table, (0, 1)), []
        if self._elements_table.selectedItems():
            return [], ids_of(self._elements_table, (0, 1))
        return [], []

    def _select_current(self) -> None:
        if self._on_select is None:
            return
        node_ids, element_ids = self._current_entities()
        self._on_select(node_ids, element_ids)

    def _nodes_changed(self) -> None:
        has_nodes = bool(self._nodes_table.selectedItems())
        self._select_button.setEnabled(has_nodes or bool(self._elements_table.selectedItems()))

    def _elements_changed(self) -> None:
        self._nodes_changed()
