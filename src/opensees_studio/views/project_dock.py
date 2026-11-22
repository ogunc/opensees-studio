"""Project dock: the tree, the entity editor and the contextual help.

Three tabs, one dock:

* **Árbol** — every entity of the project, by category, with counts.
* **Editar** — the categories with their counts and the rows of the selected
  one; the buttons trigger the dialogs that already edit them.
* **Ayuda** — the help page of the current ribbon tab.

The dock is read-only: it never mutates the project. Editing goes through the
existing actions, so undo, validation and help stay the same.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPICS
from opensees_studio.views.i18n import tr

#: category id → (label, project attribute, row builder)
CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("nodes", "Nudos", "nodes"),
    ("elements", "Elementos", "elements"),
    ("materials", "Materiales", "materials"),
    ("sections", "Secciones", "sections"),
    ("patterns", "Patrones", "load_patterns"),
    ("analyses", "Casos", "analyses"),
    ("combinations", "Combinaciones", "combinations"),
    ("connections", "Conexiones", "connections"),
)


def _name(entity: Any) -> str:
    return str(getattr(entity, "name", "") or "")


def _detail(entity: Any, category: str) -> str:
    if category == "nodes":
        coords = ", ".join(f"{c:g}" for c in entity.coords)
        return f"{coords}  ·  {entity.type}" if hasattr(entity, "type") else coords
    if category == "elements":
        return str(getattr(entity, "type", ""))
    return str(getattr(entity, "type", ""))


class ProjectDock(QWidget):
    """Árbol / Editar / Ayuda for the open project."""

    editRequested = Signal(str, int)
    """``(category, entity id)``: the user asked to edit one row."""

    tableRequested = Signal()
    deleteRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project: Any = None
        self._category = "nodes"
        self._build()
        self.set_project(None)

    # ── construction ─────────────────────────────────────────────
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_tree(), tr("Tree"))
        self._tabs.addTab(self._build_edit(), tr("Edit"))
        self._tabs.addTab(self._build_help(), tr("Help"))
        layout.addWidget(self._tabs)

    def _build_tree(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        self._tree = QTreeWidget(page)
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Object", "Type"])
        self._tree.itemSelectionChanged.connect(self._on_tree_selection)
        self._tree.itemDoubleClicked.connect(self._on_tree_double_click)
        layout.addWidget(self._tree)
        return page

    def _build_edit(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)

        self._cats = QListWidget(page)
        self._cats.currentRowChanged.connect(self._on_category_changed)
        layout.addWidget(self._cats, 1)

        self._rows = QTableWidget(0, 3, page)
        self._rows.setHorizontalHeaderLabels(["#", "Object", "Detail"])
        self._rows.horizontalHeader().setStretchLastSection(True)
        self._rows.verticalHeader().setVisible(False)
        self._rows.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._rows.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._rows.doubleClicked.connect(self._on_row_double_click)
        layout.addWidget(self._rows, 2)

        buttons = QHBoxLayout()
        for label, slot in (
            ("Editar", self.editRequested.emit),
            ("Eliminar", self._emit_delete),
            ("Tabla", self._emit_table),
        ):
            button = QPushButton(label, page)
            button.clicked.connect(lambda _=False, fn=slot: fn())
            buttons.addWidget(button)
        layout.addLayout(buttons)
        return page

    def _build_help(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        self._help = QTextBrowser(page)
        self._help.setOpenExternalLinks(False)
        layout.addWidget(self._help)
        return page

    # ── data ─────────────────────────────────────────────────────
    def set_project(self, project: Any) -> None:
        self._project = project
        self.refresh()

    def refresh(self) -> None:
        self._fill_tree()
        self._fill_categories()
        self._fill_rows()

    def _entities(self, category: str) -> list[Any]:
        if self._project is None:
            return []
        attr = dict((c[0], c[2]) for c in CATEGORIES).get(category, "")
        return list(getattr(self._project, attr, []) or [])

    def _fill_tree(self) -> None:
        self._tree.clear()
        if self._project is None:
            return
        for category, label, _attr in CATEGORIES:
            items = self._entities(category)
            parent = QTreeWidgetItem([label, str(len(items))])
            self._tree.addTopLevelItem(parent)
            for entity in items:
                child = QTreeWidgetItem(
                    [f"#{entity.id}  {_name(entity)}", _detail(entity, category)]
                )
                child.setData(0, Qt.ItemDataRole.UserRole, (category, entity.id))
                parent.addChild(child)
            parent.setExpanded(True)

    def _fill_categories(self) -> None:
        self._cats.blockSignals(True)
        self._cats.clear()
        for category, label, _attr in CATEGORIES:
            item = QListWidgetItem(f"{label}  ({len(self._entities(category))})")
            item.setData(Qt.ItemDataRole.UserRole, category)
            self._cats.addItem(item)
        for row in range(self._cats.count()):
            if self._cats.item(row).data(Qt.ItemDataRole.UserRole) == self._category:
                self._cats.setCurrentRow(row)
                break
        self._cats.blockSignals(False)

    def _fill_rows(self) -> None:
        items = self._entities(self._category)
        self._rows.setRowCount(0)
        for entity in items:
            row = self._rows.rowCount()
            self._rows.insertRow(row)
            self._rows.setItem(row, 0, QTableWidgetItem(str(entity.id)))
            self._rows.setItem(row, 1, QTableWidgetItem(_name(entity)))
            self._rows.setItem(row, 2, QTableWidgetItem(_detail(entity, self._category)))
            row_item = self._rows.item(row, 0)
            if row_item is not None:
                row_item.setData(Qt.ItemDataRole.UserRole, entity.id)

    # ── help ─────────────────────────────────────────────────────
    def show_topic(self, topic_id: str) -> None:
        topic = TOPICS.get(topic_id)
        self._help.setHtml(topic.html() if topic is not None else "<p>Sin ayuda.</p>")

    def show_help_tab(self) -> None:
        self._tabs.setCurrentIndex(2)

    # ── signals ──────────────────────────────────────────────────
    def _on_category_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self._cats.item(row)
        if item is not None:
            self._category = str(item.data(Qt.ItemDataRole.UserRole) or "nodes")
            self._fill_rows()

    def _on_tree_selection(self) -> None:
        for item in self._tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data:
                self._category, entity_id = data
                self._select_category(self._category)
                self._select_row(int(entity_id))
                return

    def _on_tree_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data:
            self.editRequested.emit(str(data[0]), int(data[1]))

    def _on_row_double_click(self, index: Any) -> None:
        row = index.row() if hasattr(index, "row") else int(index)
        item = self._rows.item(row, 0)
        if item is not None:
            self.editRequested.emit(self._category, int(item.text()))

    def _selected_entity_id(self) -> int:
        rows = self._rows.selectionModel().selectedRows() if self._rows.selectionModel() else []
        if not rows:
            return 0
        item = self._rows.item(rows[0].row(), 0)
        return int(item.text()) if item is not None else 0

    def _emit_delete(self) -> None:
        self.deleteRequested.emit()

    def _emit_table(self) -> None:
        self.tableRequested.emit()

    def _select_category(self, category: str) -> None:
        for row in range(self._cats.count()):
            item = self._cats.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == category:
                self._cats.setCurrentRow(row)
                return

    def _select_row(self, entity_id: int) -> None:
        for row in range(self._rows.rowCount()):
            item = self._rows.item(row, 0)
            if item is not None and item.text() == str(entity_id):
                self._rows.selectRow(row)
                return


def project_dock(title: str = "Project", parent: QWidget | None = None) -> QDockWidget:
    """A QDockWidget wrapping :class:`ProjectDock`."""
    dock = QDockWidget(title, parent)
    dock.setObjectName("projectDock")
    dock.setWidget(ProjectDock(dock))
    return dock
