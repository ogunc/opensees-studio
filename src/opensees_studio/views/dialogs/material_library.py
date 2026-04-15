"""Material Library — list on the left, parameter form on the right.

The dialog operates directly on the project's materials list via
commands; closing it doesn't "apply" anything that wasn't already
committed. Each Add/Edit/Delete is its own undoable step.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from pydantic import ValidationError

from opensees_studio.commands import (
    AddMaterialsCommand,
    DeleteMaterialsCommand,
    UpdateMaterialCommand,
)
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.material_forms import FORM_REGISTRY, form_for


class MaterialLibraryDialog(QDialog):
    """Manage all materials in the project: add, edit, delete."""

    def __init__(self, vm: ProjectViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Material Library")
        self.resize(720, 480)
        self._vm = vm
        self._build_ui()
        self._refresh_list()

        # Re-render whenever a command runs.
        self._vm.modelMutated.connect(self._refresh_list)

    # ── construction ─────────────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Materials</b> — every change is undoable from the main window."))

        body = QHBoxLayout()
        outer.addLayout(body, stretch=1)

        # Left panel
        left = QVBoxLayout()
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        left.addWidget(self._list, stretch=1)

        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("Add…")
        self._delete_btn = QPushButton("Delete")
        self._add_btn.clicked.connect(self._on_add)
        self._delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._delete_btn)
        left.addLayout(btn_row)

        body.addLayout(left, stretch=1)

        # Right panel — stacked forms
        right = QVBoxLayout()
        self._type_label = QLabel("(no material selected)")
        self._type_label.setStyleSheet("font-weight: bold;")
        right.addWidget(self._type_label)

        self._stack = QStackedWidget()
        right.addWidget(self._stack, stretch=1)

        self._apply_btn = QPushButton("Apply changes")
        self._apply_btn.clicked.connect(self._on_apply)
        right.addWidget(self._apply_btn, alignment=Qt.AlignmentFlag.AlignRight)

        body.addLayout(right, stretch=2)

        # Close button row
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)

    # ── helpers ──────────────────────────────────────────────────────
    def _refresh_list(self) -> None:
        selected_id = None
        if self._list.currentItem() is not None:
            selected_id = self._list.currentItem().data(Qt.ItemDataRole.UserRole)
        self._list.clear()
        for m in self._vm.project.materials if self._vm.project else []:
            label = f"#{m.id}  {m.name or '(unnamed)'}  [{m.type}]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, m.id)
            self._list.addItem(item)
        if selected_id is not None:
            self._select_by_id(selected_id)
        if self._list.currentRow() < 0 and self._list.count():
            self._list.setCurrentRow(0)
        if self._list.count() == 0:
            self._stack.setCurrentIndex(-1)
            self._type_label.setText("(no material selected)")

    def _selected_material(self):  # type: ignore[no-untyped-def]
        item = self._list.currentItem()
        if item is None or self._vm.project is None:
            return None
        mid = item.data(Qt.ItemDataRole.UserRole)
        return next((m for m in self._vm.project.materials if m.id == mid), None)

    # ── slots ────────────────────────────────────────────────────────
    def _on_row_changed(self, _row: int) -> None:
        material = self._selected_material()
        if material is None:
            return
        # Replace any old form with a fresh, populated one.
        while self._stack.count():
            old = self._stack.widget(0)
            self._stack.removeWidget(old)
            old.deleteLater()
        form = form_for(material)
        self._stack.addWidget(form)
        self._stack.setCurrentWidget(form)
        self._type_label.setText(form.type_label)

    def _on_apply(self) -> None:
        if self._stack.count() == 0 or self._vm.project is None:
            return
        form = self._stack.currentWidget()
        try:
            new_material = form.read()
            self._vm.apply_command(UpdateMaterialCommand(self._vm, new_material))
        except (ValidationError, ValueError) as exc:
            QMessageBox.critical(self, "Validation error", str(exc))

    def _on_add(self) -> None:
        if self._vm.project is None:
            return
        kinds = list(FORM_REGISTRY.keys())
        kind, ok = QInputDialog.getItem(
            self, "Add material", "Type:", kinds, current=0, editable=False,
        )
        if not ok:
            return
        new_id = self._vm.project.next_material_id()
        # Build a default-valued instance using the form: instantiate, populate
        # nothing (defaults shown in the form), then read with the new id.
        form_cls = FORM_REGISTRY[kind]
        form = form_cls()
        form._material_id = new_id  # type: ignore[attr-defined]
        try:
            new_material = form.read()
        except (ValidationError, ValueError) as exc:
            QMessageBox.critical(self, "Could not create material", str(exc))
            return
        self._vm.apply_command(AddMaterialsCommand(self._vm, [new_material]))
        self._select_by_id(new_id)

    def _select_by_id(self, target_id: int) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == target_id:
                self._list.setCurrentRow(i)
                return

    def _on_delete(self) -> None:
        material = self._selected_material()
        if material is None:
            return
        reply = QMessageBox.question(
            self, "Delete material",
            f"Delete material #{material.id} ({material.type})?\n"
            "Elements that reference it will be invalid until reassigned."
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._vm.apply_command(DeleteMaterialsCommand(self._vm, {material.id}))
