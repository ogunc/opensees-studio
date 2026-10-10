"""Pick a typical construction material — concrete, steel or masonry.

The library's table is SI: strengths in MPa, densities in kg/m³, each row tied
to the clause it comes from (ACI 318, AISC 360, TMS 402, ASCE 7). The project
has its own unit system, so the dialog makes the difference visible instead of
hiding it: the published value and the value that will be inserted are shown
side by side, and nothing reaches the model until Insert is pressed.

The material that comes back is a real project material — ``Concrete01``,
``Steel02``, ``ElasticIsotropic`` or ``ElasticUniaxial`` — so it can be edited,
referenced and undone like any other.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.material_catalog import (
    FAMILY_LABELS,
    TypicalMaterial,
    families,
    field_summary,
    load_materials,
    materials_of,
    preview_rows,
    search,
    to_material,
    unit_note,
)
from opensees_studio.core.units import UnitSystem, labels_for
from opensees_studio.views.screen_fit import FittedDialog

#: Columns of the material list: (heading, what it shows).
_LIST_COLUMNS = ("Material", "Family", "Key values (as published)")


class TypicalMaterialsDialog(FittedDialog):
    """A library picker; :meth:`result_material` is what the caller inserts."""

    def __init__(
        self,
        *,
        units: UnitSystem,
        next_id: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Typical Materials")
        self.resize(900, 560)
        self._units = units
        self._next_id = next_id
        self._entries: list[TypicalMaterial] = []
        self._material: Any | None = None
        self._build_ui()
        self._refresh_list()
        # F1 anywhere in this dialog shows the Material Library page.
        self.setProperty(TOPIC_PROPERTY, "define.material_library")

    # ── public API ───────────────────────────────────────────────────
    def result_material(self) -> Any | None:
        """The project material chosen, or ``None`` if nothing was picked."""
        return self._material

    def _selected_entry(self) -> TypicalMaterial | None:
        row = self._list.currentRow()
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    # ── UI ───────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        labels = labels_for(self._units)
        outer.addWidget(
            QLabel(
                "<b>Typical construction materials</b> — concrete, reinforcing and "
                "structural steel, and masonry. Values are published in SI (MPa, kg/m³) "
                f"and converted to this project's units ({labels.stress}, {labels.force}, "
                f"{labels.length}) when inserted.",
            ),
        )

        picker = QHBoxLayout()
        picker.addWidget(QLabel("Family:"))
        self._family = QComboBox()
        self._family.addItem("All families", "")
        for family in families():
            self._family.addItem(FAMILY_LABELS.get(family, family), family)
        self._family.currentIndexChanged.connect(self._refresh_list)
        picker.addWidget(self._family)

        picker.addWidget(QLabel("Search:"))
        self._query = QLineEdit()
        self._query.setPlaceholderText("f'c, A992, masonry, ACI 318 …")
        self._query.textChanged.connect(self._refresh_list)
        picker.addWidget(self._query, stretch=1)
        outer.addLayout(picker)

        self._list = QTableWidget(0, len(_LIST_COLUMNS))
        self._list.setHorizontalHeaderLabels(list(_LIST_COLUMNS))
        self._list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._list.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._list.verticalHeader().setVisible(False)
        self._list.currentCellChanged.connect(lambda *_a: self._show_details())
        outer.addWidget(self._list, stretch=3)

        details = QGroupBox("What will be inserted")
        form = QVBoxLayout(details)
        self._standard = QLabel("")
        self._standard.setWordWrap(True)
        self._standard.setStyleSheet("color: #555;")
        form.addWidget(self._standard)

        self._preview = QTableWidget(0, 3)
        self._preview.setHorizontalHeaderLabels(
            ["Parameter", "As published", f"In this project ({labels.stress})"],
        )
        self._preview.verticalHeader().setVisible(False)
        self._preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._preview.setMaximumHeight(180)
        form.addWidget(self._preview)

        self._notes = QLabel("")
        self._notes.setWordWrap(True)
        form.addWidget(self._notes)
        outer.addWidget(details, stretch=2)

        buttons = QDialogButtonBox(self)
        self._insert = buttons.addButton("Insert material", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_insert)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # ── list and details ─────────────────────────────────────────────
    def _refresh_list(self, *_args: Any) -> None:
        family = self._family.currentData() or ""
        query = self._query.text()
        entries = search(query) if query.strip() else list(load_materials().values())
        if family:
            entries = [entry for entry in entries if entry.family == family]
        # Keep the family grouping of the table even after a search.
        order = list(FAMILY_LABELS)
        entries.sort(key=lambda entry: order.index(entry.family) if entry.family in order else 99)
        self._entries = entries

        self._list.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            cells = (entry.name, entry.family_label, field_summary(entry))
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(entry.standard)
                self._list.setItem(row, column, item)
        self._list.resizeColumnsToContents()
        if entries:
            self._list.setCurrentCell(0, 0)
        else:
            self._standard.setText("No material matches that search.")
            self._preview.setRowCount(0)
            self._notes.setText("")
            self._insert.setEnabled(False)

    def _show_details(self) -> None:
        entry = self._selected_entry()
        self._insert.setEnabled(entry is not None)
        if entry is None:
            return
        self._standard.setText(f"<b>{entry.name}</b><br>Source: {entry.standard}")
        rows = preview_rows(entry, self._units)
        self._preview.setRowCount(len(rows))
        for row, (parameter, published, converted) in enumerate(rows):
            for column, text in enumerate((parameter, published, converted)):
                self._preview.setItem(row, column, QTableWidgetItem(text))
        self._preview.resizeColumnsToContents()
        units_hint = unit_note(entry)
        footer = f"{units_hint}"
        if entry.model == "Concrete01":
            footer += (
                ". Concrete01 stores compression as a negative stress and strain, "
                "so f'c, f'cu, εc0 and εcu are inserted with a minus sign."
            )
        if entry.family == "masonry":
            footer += (
                ". Masonry enters as an elastic material: a nonlinear wall needs its own "
                "backbone from ASCE 41 Chapter 11."
            )
        if entry.notes:
            footer += f"\n\n{entry.notes}"
        self._notes.setText(footer)

    # ── slots ────────────────────────────────────────────────────────
    def _on_insert(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        self._material = to_material(entry, self._next_id, self._units)
        self.accept()


def materials_for_family(family: str) -> list[TypicalMaterial]:
    """The library's entries of one family (convenience for tests and callers)."""
    return materials_of(family)
