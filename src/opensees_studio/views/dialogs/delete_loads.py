"""Edit → Delete Loads: choose the load types, the patterns and the scope.

The counts next to each type are what would go with the current choice, so the
dialog says what it will do before it does it. The removal is in
:mod:`opensees_studio.core.load_removal`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.load_removal import LOAD_KINDS, Scope, count_loads
from opensees_studio.core.loads import PlainLoadPattern
from opensees_studio.core.project import Project
from opensees_studio.views.screen_fit import FittedDialog


class DeleteLoadsDialog(FittedDialog):
    """Pick load types, patterns and the selection or the whole model."""

    def __init__(
        self,
        project: Project,
        *,
        selected_nodes: set[int],
        selected_elements: set[int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Delete Loads")
        self.setProperty(TOPIC_PROPERTY, "edit.delete_loads")
        self._project = project
        self._nodes = frozenset(selected_nodes)
        self._elements = frozenset(selected_elements)
        layout = QVBoxLayout(self)

        scope_box = QGroupBox("Delete from")
        scope_layout = QVBoxLayout(scope_box)
        has_selection = bool(self._nodes or self._elements)
        self._scope_selection = QRadioButton(
            f"The selection ({len(self._nodes)} joint(s), {len(self._elements)} element(s))"
        )
        self._scope_all = QRadioButton("The entire model")
        self._scope_selection.setEnabled(has_selection)
        (self._scope_selection if has_selection else self._scope_all).setChecked(True)
        for button in (self._scope_selection, self._scope_all):
            button.toggled.connect(self._refresh)
            scope_layout.addWidget(button)
        layout.addWidget(scope_box)

        kinds_box = QGroupBox("Load types")
        kinds_layout = QVBoxLayout(kinds_box)
        self._kinds: dict[str, QCheckBox] = {}
        for kind in LOAD_KINDS:
            box = QCheckBox(kind.label)
            box.toggled.connect(self._refresh)
            self._kinds[kind.key] = box
            kinds_layout.addWidget(box)
        layout.addWidget(kinds_box)

        patterns_box = QGroupBox("Load patterns")
        patterns_layout = QVBoxLayout(patterns_box)
        self._patterns = QListWidget()
        for pattern in project.load_patterns:
            if not isinstance(pattern, PlainLoadPattern):
                continue
            item = QListWidgetItem(f"#{pattern.id} {pattern.name or 'Pattern'}")
            item.setData(Qt.ItemDataRole.UserRole, pattern.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._patterns.addItem(item)
        self._patterns.itemChanged.connect(self._refresh)
        patterns_layout.addWidget(self._patterns)
        layout.addWidget(patterns_box)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText("Delete")
        self._refresh()

    # ── the choice ──────────────────────────────────────────────────
    def kinds(self) -> set[str]:
        return {key for key, box in self._kinds.items() if box.isChecked()}

    def scope(self) -> Scope:
        patterns = frozenset(
            int(self._patterns.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self._patterns.count())
            if self._patterns.item(i).checkState() == Qt.CheckState.Checked
        )
        if self._scope_selection.isChecked():
            return Scope(pattern_ids=patterns, node_ids=self._nodes, element_ids=self._elements)
        return Scope(pattern_ids=patterns)

    def _refresh(self, *_: object) -> None:
        scope = self.scope()
        every = count_loads(self._project, self._kinds, scope)
        for key, box in self._kinds.items():
            label = next(kind.label for kind in LOAD_KINDS if kind.key == key)
            box.setText(f"{label} ({every[key]})")
        chosen = sum(every[key] for key in self.kinds())
        if not self.kinds():
            self._summary.setText("Tick the load types to delete.")
        elif chosen == 0:
            self._summary.setText("Nothing of those types in the chosen patterns and scope.")
        else:
            self._summary.setText(f"<b>{chosen}</b> load(s) will be deleted. Undo with Ctrl+Z.")
        self._ok.setEnabled(chosen > 0)
