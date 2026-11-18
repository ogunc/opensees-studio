"""Group dialogs: Define → Groups, Assign → Assign to Group and Define → Section Cuts.

Both edit copies and hand back plain core models (``groups()``) or a choice
(``group_id``, ``mode``, ``new_name``); the main window wraps the result in an
undoable command.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Group, Project, SectionCut
from opensees_studio.core.groups import colour_for
from opensees_studio.views.screen_fit import FittedDialog, MessageArea


def _buttons(dialog: FittedDialog) -> QDialogButtonBox:
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        parent=dialog,
    )
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def _swatch(button: QPushButton, colour: str) -> None:
    button.setText(colour)
    button.setStyleSheet(f"background-color: {colour}; color: {_text_on(colour)};")


def _text_on(colour: str) -> str:
    c = QColor(colour)
    return (
        "#000000" if (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) > 150 else "#ffffff"
    )


# ─────────────────────────── Define → Groups ───────────────────────────
class GroupsDialog(FittedDialog):
    """Name and colour of every group, with the joints and elements each holds."""

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Define Groups")
        self._groups: list[Group] = [g.model_copy() for g in project.groups]
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "Named sets of joints and elements. Fill them with Assign → Assign to Group "
                "and select them again with Select → By Group."
            )
        )
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Colour", "Joints", "Elements"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table)

        row = QHBoxLayout()
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self._on_add)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._on_remove)
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        root.addLayout(row)

        self.message = MessageArea()
        root.addWidget(self.message)
        root.addWidget(_buttons(self))
        for group in self._groups:
            self._append_row(group)

    def _append_row(self, group: Group) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(group.name))
        button = QPushButton()
        _swatch(button, group.colour)
        button.clicked.connect(lambda _checked=False, b=button: self._pick_colour(b))
        self.table.setCellWidget(r, 1, button)
        for column, count in ((2, len(group.node_ids)), (3, len(group.element_ids))):
            item = QTableWidgetItem(str(count))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, column, item)

    def _pick_colour(self, button: QPushButton) -> None:
        colour = QColorDialog.getColor(QColor(button.text()), self, "Group Colour")
        if colour.isValid():
            _swatch(button, colour.name())

    def _on_add(self) -> None:
        used = {g.id for g in self._groups}
        group_id = max(used, default=0) + 1
        names = {self._name(r).casefold() for r in range(self.table.rowCount())}
        k = len(self._groups) + 1
        while f"group{k}" in names:
            k += 1
        group = Group(id=group_id, name=f"GROUP{k}", colour=colour_for(len(self._groups)))
        self._groups.append(group)
        self._append_row(group)

    def _on_remove(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
            del self._groups[r]

    def _name(self, row: int) -> str:
        item = self.table.item(row, 0)
        return item.text().strip() if item is not None else ""

    def groups(self) -> list[Group]:
        """The groups as edited (raises ``ValueError`` on a bad or repeated name)."""
        out: list[Group] = []
        seen: set[str] = set()
        for r, group in enumerate(self._groups):
            name = self._name(r)
            if not name:
                raise ValueError(f"Row {r + 1}: the group needs a name.")
            if name.casefold() in seen:
                raise ValueError(f"Two groups are called {name!r}.")
            seen.add(name.casefold())
            button = self.table.cellWidget(r, 1)
            colour = button.text() if isinstance(button, QPushButton) else group.colour
            out.append(group.model_copy(update={"name": name, "colour": colour}))
        return out

    def accept(self) -> None:
        try:
            self.groups()
        except ValueError as exc:
            self.message.show_message(str(exc), "error")
            return
        super().accept()


# ─────────────────────────── Assign → Assign to Group ───────────────────────────
NEW_GROUP = 0
"""``group_id`` of the "new group" entry: the main window creates it first."""


class AssignGroupDialog(FittedDialog):
    """Pick a group (or name a new one) and add, remove or replace its members."""

    def __init__(
        self, project: Project, n_nodes: int, n_elements: int, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign to Group")
        self._project = project
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Selection: {n_nodes} joint(s), {n_elements} element(s)."))
        form = QFormLayout()
        self.group_combo = QComboBox()
        for group in project.groups:
            self.group_combo.addItem(
                f"{group.name} ({len(group.node_ids)} joint(s), "
                f"{len(group.element_ids)} element(s))",
                group.id,
            )
        self.group_combo.addItem("New group…", NEW_GROUP)
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        form.addRow("Group:", self.group_combo)
        self.new_name = QLineEdit()
        k = len(project.groups) + 1
        names = {g.name.casefold() for g in project.groups}
        while f"group{k}" in names:
            k += 1
        self.new_name.setText(f"GROUP{k}")
        form.addRow("New group name:", self.new_name)
        root.addLayout(form)

        self.mode_buttons = QButtonGroup(self)
        modes = QHBoxLayout()
        for mode, label in (
            ("add", "Add to group"),
            ("remove", "Remove from group"),
            ("replace", "Replace members"),
        ):
            radio = QRadioButton(label)
            radio.setProperty("mode", mode)
            self.mode_buttons.addButton(radio)
            modes.addWidget(radio)
            if mode == "add":
                radio.setChecked(True)
        root.addLayout(modes)
        self.message = MessageArea()
        root.addWidget(self.message)
        root.addWidget(_buttons(self))
        self._on_group_changed()

    def _on_group_changed(self) -> None:
        is_new = self.group_id == NEW_GROUP
        self.new_name.setEnabled(is_new)
        for button in self.mode_buttons.buttons():
            button.setEnabled(not is_new or button.property("mode") == "add")
        if is_new:
            self.mode_buttons.buttons()[0].setChecked(True)

    @property
    def group_id(self) -> int:
        return int(self.group_combo.currentData())

    @property
    def mode(self) -> str:
        checked = self.mode_buttons.checkedButton()
        return str(checked.property("mode")) if checked is not None else "add"

    def accept(self) -> None:
        if self.group_id == NEW_GROUP:
            name = self.new_name.text().strip()
            if not name:
                self.message.show_message("Name the new group.", "error")
                return
            if any(g.name.casefold() == name.casefold() for g in self._project.groups):
                self.message.show_message(f"A group is already called {name!r}.", "error")
                return
        super().accept()


# ─────────────────────────── Define → Section Cuts ───────────────────────────
class SectionCutsDialog(FittedDialog):
    """Name, group and moment centre of every section cut."""

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Define Section Cuts")
        self._project = project
        self._ids: list[int] = []
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "A cut sums the end forces of a group's elements at the group's joints, with "
                "moments about the centroid of those joints (or the X, Y, Z typed). Results: "
                "the Section cuts tab of a static case."
            )
        )
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "Group", "Centre X", "Centre Y", "Centre Z"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table)
        row = QHBoxLayout()
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self._on_add)
        self.add_button.setEnabled(bool(project.groups))
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._on_remove)
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        root.addLayout(row)
        self.message = MessageArea()
        root.addWidget(self.message)
        if not project.groups:
            self.message.show_message(
                "Define a group first (Define → Groups, Assign → Assign to Group).", "warning"
            )
        root.addWidget(_buttons(self))
        for cut in project.section_cuts:
            self._append(cut)

    def _append(self, cut: SectionCut) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(cut.name))
        combo = QComboBox()
        for group in self._project.groups:
            combo.addItem(group.name, group.id)
        combo.setCurrentIndex(max(combo.findData(cut.group_id), 0))
        self.table.setCellWidget(r, 1, combo)
        for k in range(3):
            text = "" if cut.centre is None else repr(float(cut.centre[k]))
            self.table.setItem(r, 2 + k, QTableWidgetItem(text))
        self._ids.append(cut.id)

    def _on_add(self) -> None:
        cut_id = max(self._ids, default=0) + 1
        self._append(
            SectionCut(id=cut_id, name=f"SCUT{cut_id}", group_id=self._project.groups[0].id)
        )

    def _on_remove(self) -> None:
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)
            del self._ids[r]

    def section_cuts(self) -> list[SectionCut]:
        """The cuts as typed (raises ``ValueError`` on a bad centre or a repeated name)."""
        out: list[SectionCut] = []
        names: set[str] = set()
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            name = item.text().strip() if item is not None else ""
            if not name:
                raise ValueError(f"Row {r + 1}: the cut needs a name.")
            if name.casefold() in names:
                raise ValueError(f"Two section cuts are called {name!r}.")
            names.add(name.casefold())
            combo = self.table.cellWidget(r, 1)
            assert isinstance(combo, QComboBox)
            texts = []
            for k in range(3):
                cell = self.table.item(r, 2 + k)
                texts.append(cell.text().strip() if cell is not None else "")
            if not any(texts):
                centre = None
            else:
                try:
                    x, y, z = (float(t.replace(",", ".")) for t in texts)
                except ValueError:
                    raise ValueError(
                        f"Row {r + 1}: type all three centre coordinates, or none."
                    ) from None
                centre = (x, y, z)
            out.append(
                SectionCut(
                    id=self._ids[r], name=name, group_id=int(combo.currentData()), centre=centre
                )
            )
        return out

    def accept(self) -> None:
        try:
            self.section_cuts()
        except ValueError as exc:
            self.message.show_message(str(exc), "error")
            return
        super().accept()
