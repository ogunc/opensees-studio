"""Right-click → Object Information: one joint or element, in Location / Assignments / Loads tabs."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialogButtonBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.object_info import ObjectInfo
from opensees_studio.views.i18n import tr
from opensees_studio.views.screen_fit import FittedDialog


class ObjectInfoDialog(FittedDialog):
    """Read-only: what the model holds about the object that was right-clicked."""

    def __init__(self, info: ObjectInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{tr('Object Information')}: {info.title}")
        self.setProperty(TOPIC_PROPERTY, "display.object_info")
        self.resize(520, 380)
        self._tabs = QTabWidget()
        for tab in info.tabs:
            table = QTableWidget(len(tab.rows), 2)
            table.setHorizontalHeaderLabels(["Item", "Value"])
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.verticalHeader().setVisible(False)
            table.setWordWrap(True)
            header = table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            for row, (label, value) in enumerate(tab.rows):
                table.setItem(row, 0, QTableWidgetItem(label))
                table.setItem(row, 1, QTableWidgetItem(value))
            table.resizeRowsToContents()
            self._tabs.addTab(table, tab.title)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self._tabs)
        layout.addWidget(buttons)

    # ── public API (also used by tests) ──────────────────────────────
    def tab_titles(self) -> list[str]:
        return [self._tabs.tabText(i) for i in range(self._tabs.count())]

    def rows(self, tab: int) -> list[tuple[str, str]]:
        table = self._tabs.widget(tab)
        assert isinstance(table, QTableWidget)
        cells = [(table.item(row, 0), table.item(row, 1)) for row in range(table.rowCount())]
        return [(a.text(), b.text()) for a, b in cells if a is not None and b is not None]
