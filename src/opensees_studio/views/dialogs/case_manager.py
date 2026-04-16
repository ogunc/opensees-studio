"""Analysis Case Manager — library-style CRUD for analyses."""

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
    AddAnalysisCasesCommand,
    DeleteAnalysisCasesCommand,
    UpdateAnalysisCaseCommand,
)
from opensees_studio.core import ModalCase, PushoverCase, StaticCase, TransientCase
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.case_forms import FORM_REGISTRY, form_for


_DEFAULTS = {
    "Static": lambda cid: StaticCase(id=cid, name="Static", pattern_ids=[1]),
    "Modal":  lambda cid: ModalCase(id=cid, name="Modal", n_modes=3),
    "Transient": lambda cid: TransientCase(
        id=cid, name="Transient", pattern_ids=[1], dt=0.01, n_steps=1000,
    ),
    "Pushover": lambda cid: PushoverCase(
        id=cid, name="Pushover", pattern_ids=[1],
        control_node=1, control_dof=1, target_disp=0.1, step_size=0.001,
    ),
}


class AnalysisCaseManagerDialog(QDialog):
    def __init__(self, vm: ProjectViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Analysis Cases")
        self.resize(820, 580)
        self._vm = vm
        self._build_ui()
        self._refresh_list()
        self._vm.modelMutated.connect(self._refresh_list)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Analysis Cases</b> — define what to run later from File → Run."))

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
        self._type_label = QLabel("(no case selected)")
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
        # Preserve selection by entity id (rows shift on add/delete).
        selected_id = None
        if self._list.currentItem() is not None:
            selected_id = self._list.currentItem().data(Qt.ItemDataRole.UserRole)
        self._list.clear()
        for c in (self._vm.project.analyses if self._vm.project else []):
            label = f"#{c.id}  {c.name or '(unnamed)'}  [{c.type}]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, c.id)
            self._list.addItem(item)
        if selected_id is not None:
            self._select_by_id(selected_id)
        if self._list.currentRow() < 0 and self._list.count():
            self._list.setCurrentRow(0)
        if self._list.count() == 0:
            self._stack.setCurrentIndex(-1)
            self._type_label.setText("(no case selected)")

    def _selected_case(self):  # type: ignore[no-untyped-def]
        item = self._list.currentItem()
        if item is None or self._vm.project is None:
            return None
        cid = item.data(Qt.ItemDataRole.UserRole)
        return next((c for c in self._vm.project.analyses if c.id == cid), None)

    def _on_row_changed(self, _row: int) -> None:
        case = self._selected_case()
        if case is None or self._vm.project is None:
            return
        while self._stack.count():
            old = self._stack.widget(0)
            self._stack.removeWidget(old)
            old.deleteLater()
        form = form_for(case, self._vm.project.load_patterns)
        self._stack.addWidget(form)
        self._stack.setCurrentWidget(form)
        self._type_label.setText(form.type_label)

    def _on_apply(self) -> None:
        if self._stack.count() == 0:
            return
        form = self._stack.currentWidget()
        try:
            new_case = form.read()
            self._vm.apply_command(UpdateAnalysisCaseCommand(self._vm, new_case))
        except (ValidationError, ValueError) as exc:
            QMessageBox.critical(self, "Validation error", str(exc))

    def _on_add(self) -> None:
        if self._vm.project is None:
            return
        if not self._vm.project.load_patterns:
            QMessageBox.information(
                self, "No patterns",
                "Define at least one load pattern before adding a Static or Transient "
                "case (Modal works without patterns).",
            )
        kind, ok = QInputDialog.getItem(
            self, "Add analysis case", "Type:",
            list(_DEFAULTS.keys()), current=0, editable=False,
        )
        if not ok:
            return
        new_id = self._vm.project.next_analysis_id()
        try:
            new_case = _DEFAULTS[kind](new_id)
        except (ValidationError, ValueError) as exc:
            QMessageBox.critical(self, "Could not create case", str(exc))
            return
        self._vm.apply_command(AddAnalysisCasesCommand(self._vm, [new_case]))
        # _refresh_list ran via modelMutated and restored the previous row.
        # Override that and select the freshly-added one.
        self._select_by_id(new_id)

    def _select_by_id(self, target_id: int) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == target_id:
                self._list.setCurrentRow(i)
                return

    def _on_delete(self) -> None:
        case = self._selected_case()
        if case is None:
            return
        reply = QMessageBox.question(
            self, "Delete case", f"Delete analysis case #{case.id} ({case.type})?"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._vm.apply_command(DeleteAnalysisCasesCommand(self._vm, {case.id}))
