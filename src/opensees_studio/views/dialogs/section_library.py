"""Section Library — same shape as the Material Library."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
    AddSectionsCommand,
    DeleteSectionsCommand,
    UpdateSectionCommand,
)
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.section_forms import FORM_REGISTRY, form_for


class SectionLibraryDialog(QDialog):
    def __init__(self, vm: ProjectViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Section Library")
        self.resize(720, 480)
        self._vm = vm
        self._build_ui()
        self._refresh_list()
        self._vm.modelMutated.connect(self._refresh_list)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Sections</b> — every change is undoable from the main window."))

        body = QHBoxLayout()
        outer.addLayout(body, stretch=1)

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

        right = QVBoxLayout()
        self._type_label = QLabel("(no section selected)")
        self._type_label.setStyleSheet("font-weight: bold;")
        right.addWidget(self._type_label)
        self._stack = QStackedWidget()
        right.addWidget(self._stack, stretch=1)
        self._apply_btn = QPushButton("Apply changes")
        self._apply_btn.clicked.connect(self._on_apply)
        right.addWidget(self._apply_btn, alignment=Qt.AlignmentFlag.AlignRight)
        body.addLayout(right, stretch=2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)

    def _refresh_list(self) -> None:
        previous = self._list.currentRow()
        self._list.clear()
        for s in self._vm.project.sections if self._vm.project else []:
            label = f"#{s.id}  {s.name or '(unnamed)'}  [{s.type}]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, s.id)
            self._list.addItem(item)
        if previous >= 0 and previous < self._list.count():
            self._list.setCurrentRow(previous)
        elif self._list.count():
            self._list.setCurrentRow(0)
        else:
            self._stack.setCurrentIndex(-1)
            self._type_label.setText("(no section selected)")

    def _selected_section(self):  # type: ignore[no-untyped-def]
        item = self._list.currentItem()
        if item is None or self._vm.project is None:
            return None
        sid = item.data(Qt.ItemDataRole.UserRole)
        return next((s for s in self._vm.project.sections if s.id == sid), None)

    def _on_row_changed(self, _row: int) -> None:
        section = self._selected_section()
        if section is None:
            return
        while self._stack.count():
            old = self._stack.widget(0)
            self._stack.removeWidget(old)
            old.deleteLater()
        form = form_for(section)
        self._stack.addWidget(form)
        self._stack.setCurrentWidget(form)
        self._type_label.setText(form.type_label)

    def _on_apply(self) -> None:
        if self._stack.count() == 0 or self._vm.project is None:
            return
        form = self._stack.currentWidget()
        try:
            new_section = form.read()
            self._vm.apply_command(UpdateSectionCommand(self._vm, new_section))
        except (ValidationError, ValueError) as exc:
            QMessageBox.critical(self, "Validation error", str(exc))

    def _on_add(self) -> None:
        if self._vm.project is None:
            return
        kinds = list(FORM_REGISTRY.keys())
        kind, ok = QInputDialog.getItem(
            self, "Add section", "Type:", kinds, current=0, editable=False,
        )
        if not ok:
            return
        new_id = self._vm.project.next_section_id()
        form = FORM_REGISTRY[kind]()
        form._section_id = new_id  # type: ignore[attr-defined]
        try:
            new_section = form.read()
        except (ValidationError, ValueError) as exc:
            QMessageBox.critical(self, "Could not create section", str(exc))
            return
        self._vm.apply_command(AddSectionsCommand(self._vm, [new_section]))
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == new_id:
                self._list.setCurrentRow(i)
                break

    def _on_delete(self) -> None:
        section = self._selected_section()
        if section is None:
            return
        reply = QMessageBox.question(
            self, "Delete section",
            f"Delete section #{section.id} ({section.type})?\n"
            "Frame elements that reference it will be invalid until reassigned."
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._vm.apply_command(DeleteSectionsCommand(self._vm, {section.id}))
