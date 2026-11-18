"""Analysis Case Manager — library-style CRUD for analyses."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import ValidationError
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

from opensees_studio.commands import (
    AddAnalysisCasesCommand,
    DeleteAnalysisCasesCommand,
    RenameAnalysisCaseCommand,
    UpdateAnalysisCaseCommand,
)
from opensees_studio.core import (
    AnalysisCase,
    ConstructionStage,
    InfluenceLineCase,
    ModalCase,
    PushoverCase,
    ResponseSpectrumCase,
    StagedCase,
    StaticCase,
    TransientCase,
)
from opensees_studio.core.combinations import combinations_using_case
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.case_forms import form_for
from opensees_studio.views.screen_fit import FittedDialog, MessageArea, scroll_area

_DEFAULTS: dict[str, Callable[[int], AnalysisCase]] = {
    "Static": lambda cid: StaticCase(id=cid, name="Static", pattern_ids=[1]),
    "Staged": lambda cid: StagedCase(
        id=cid,
        name="Staged construction",
        stages=[ConstructionStage(name="Stage 1", pattern_ids=[1])],
    ),
    "Modal": lambda cid: ModalCase(id=cid, name="Modal", n_modes=3),
    "Transient": lambda cid: TransientCase(
        id=cid,
        name="Transient",
        pattern_ids=[1],
        dt=0.01,
        n_steps=1000,
    ),
    "Pushover": lambda cid: PushoverCase(
        id=cid,
        name="Pushover",
        pattern_ids=[1],
        control_node=1,
        control_dof=1,
        target_disp=0.1,
        step_size=0.001,
    ),
    "InfluenceLine": lambda cid: InfluenceLineCase(id=cid, name="Influence line", path=[1]),
    "ResponseSpectrum": lambda cid: ResponseSpectrumCase(
        id=cid,
        name="ResponseSpectrum",
        modal_case_id=1,
        spectrum_id=1,
        direction=1,
        combination="CQC",
        damping_ratio=None,
    ),
}


class AnalysisCaseManagerDialog(FittedDialog):
    def __init__(self, vm: ProjectViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Analysis Cases")
        self.resize(820, 580)
        self._vm = vm
        self._draft_case: AnalysisCase | None = None
        # True while a rename typed in a row is being applied: the row already
        # shows the new text, so the list must not be rebuilt under the editor.
        self._renaming = False
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
        self._list.itemChanged.connect(self._on_item_renamed)
        left.addWidget(self._list, stretch=1)

        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("Add…")
        self._rename_btn = QPushButton("Rename…")
        self._delete_btn = QPushButton("Delete")
        self._add_btn.clicked.connect(self._on_add)
        self._rename_btn.clicked.connect(self._on_rename)
        self._delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._rename_btn)
        btn_row.addWidget(self._delete_btn)
        left.addLayout(btn_row)
        body.addLayout(left, stretch=1)

        right = QVBoxLayout()
        self._type_label = QLabel("(no case selected)")
        self._type_label.setStyleSheet("font-weight: bold;")
        right.addWidget(self._type_label)
        self._stack = QStackedWidget()
        # A form taller or wider than the screen scrolls; Apply and the message stay put.
        self._scroll = scroll_area(self._stack, vertical_only=True)
        right.addWidget(self._scroll, stretch=1)
        self._message = MessageArea()
        right.addWidget(self._message)
        self._apply_btn = QPushButton("Apply changes")
        self._apply_btn.clicked.connect(self._on_apply)
        right.addWidget(self._apply_btn, alignment=Qt.AlignmentFlag.AlignRight)
        body.addLayout(right, stretch=2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)

    def _refresh_list(self) -> None:
        if self._renaming:
            return
        # Preserve selection by entity id (rows shift on add/delete).
        selected_id = None
        if self._list.currentItem() is not None:
            selected_id = self._list.currentItem().data(Qt.ItemDataRole.UserRole)
        self._list.blockSignals(True)
        self._list.clear()
        project = self._vm.project
        cases = list(project.analyses) if project else []
        if self._draft_case is not None:
            cases.append(self._draft_case)
        for c in cases:
            label = f"#{c.id}  {c.name or '(unnamed)'}  [{c.type}]"
            errors = project.case_reference_errors(c) if project else []
            if errors:
                label += " [Invalid references]"
            item = QListWidgetItem(label)
            item.setToolTip("\n".join(errors))
            item.setData(Qt.ItemDataRole.UserRole, c.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self._list.addItem(item)
        self._list.blockSignals(False)
        if selected_id is not None:
            self._select_by_id(selected_id)
        if self._list.currentRow() < 0 and self._list.count():
            self._list.setCurrentRow(0)
        if self._list.count() == 0:
            self._stack.setCurrentIndex(-1)
            self._type_label.setText("(no case selected)")

    def _selected_case(self) -> AnalysisCase | None:
        item = self._list.currentItem()
        if item is None or self._vm.project is None:
            return None
        cid = item.data(Qt.ItemDataRole.UserRole)
        if self._draft_case is not None and self._draft_case.id == cid:
            return self._draft_case
        return next((c for c in self._vm.project.analyses if c.id == cid), None)

    def _on_row_changed(self, _row: int) -> None:
        case = self._selected_case()
        if case is None or self._vm.project is None:
            return
        while self._stack.count():
            old = self._stack.widget(0)
            self._stack.removeWidget(old)
            old.deleteLater()
        form = form_for(case, self._vm.project.load_patterns, self._vm.project.analyses)
        self._stack.addWidget(form)
        self._stack.setCurrentWidget(form)
        self._type_label.setText(form.type_label)
        self._message.clear_message()

    def _on_rename(self) -> None:
        case = self._selected_case()
        if case is None:
            return
        item = self._list.currentItem()
        if item is not None:
            self._list.editItem(item)

    def _on_item_renamed(self, item: QListWidgetItem | None = None) -> None:
        """Apply a rename typed in the list (F2, double-click or Rename)."""
        if item is None:
            return
        case_id = item.data(Qt.ItemDataRole.UserRole)
        if case_id is None or self._vm.project is None:
            return
        text = item.text()
        prefix = f"#{case_id}  "
        name = text[len(prefix) :] if text.startswith(prefix) else text
        # Strip the decorations the row carries after the name, longest first:
        # "#7  Mode  [Modal] [Invalid references]".
        for suffix in (" [Invalid references]", f"  [{self._case_type(case_id)}]"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        name = name.strip()
        if not name:
            self._refresh_list()
            return
        if self._draft_case is not None and self._draft_case.id == case_id:
            if name != self._draft_case.name:
                self._draft_case = self._draft_case.model_copy(update={"name": name})
                self._refresh_list()
            return
        case = next((c for c in self._vm.project.analyses if c.id == case_id), None)
        if case is None:
            self._refresh_list()
            return
        if name == case.name:
            self._refresh_list()
            return
        self._renaming = True
        try:
            self._vm.apply_command(RenameAnalysisCaseCommand(self._vm, case.id, name))
        finally:
            self._renaming = False
        self._message.show_message(f"Case #{case.id} renamed to '{name}'.")

    def _case_type(self, case_id: int) -> str:
        """The ``type`` of a case id, from the project or the uncommitted draft."""
        if self._vm.project is not None:
            for case in self._vm.project.analyses:
                if case.id == case_id:
                    return str(case.type)
        if self._draft_case is not None and self._draft_case.id == case_id:
            return str(self._draft_case.type)
        return ""

    def _on_apply(self) -> None:
        project = self._vm.project
        if self._stack.count() == 0 or project is None:
            return
        form = self._stack.currentWidget()
        try:
            new_case = form.read()
            project.validate_case_references(new_case)
            if self._draft_case is not None and self._draft_case.id == new_case.id:
                self._draft_case = None
                self._vm.apply_command(AddAnalysisCasesCommand(self._vm, [new_case]))
            else:
                self._vm.apply_command(UpdateAnalysisCaseCommand(self._vm, new_case))
        except (ValidationError, ValueError) as exc:
            self._message.show_message(f"Case rejected: {exc}", "error")
            return
        self._message.show_message(f"Case #{new_case.id} updated.")

    def message_text(self) -> str:
        """The dialog's status or refusal line (empty when none)."""
        return self._message.text()

    def _on_add(self) -> None:
        if self._vm.project is None:
            return
        if not self._vm.project.load_patterns:
            QMessageBox.information(
                self,
                "No patterns",
                "Define at least one load pattern before adding a Static or Transient "
                "case (Modal works without patterns).",
            )
        kind, ok = QInputDialog.getItem(
            self,
            "Add analysis case",
            "Type:",
            list(_DEFAULTS.keys()),
            current=0,
            editable=False,
        )
        if not ok:
            return
        new_id = self._vm.project.next_analysis_id()
        try:
            new_case = _DEFAULTS[kind](new_id)
        except (ValidationError, ValueError) as exc:
            self._message.show_message(f"Case rejected: {exc}", "error")
            return
        errors = self._vm.project.case_reference_errors(new_case)
        if errors:
            self._draft_case = new_case
            self._refresh_list()
            self._select_by_id(new_id)
            self._message.show_message("New case not yet committed: " + "\n".join(errors), "error")
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
        if case is None or self._vm.project is None:
            return
        users = combinations_using_case(self._vm.project, case.id)
        if users:
            names = ", ".join(f"'{u.name}'" for u in users)
            self._message.show_message(
                f"Case #{case.id} is included in load combination(s) {names}: remove it there "
                "first (Define → Load Combinations…).",
                "error",
            )
            return
        reply = QMessageBox.question(
            self, "Delete case", f"Delete analysis case #{case.id} ({case.type})?"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self._draft_case is not None and self._draft_case.id == case.id:
            self._draft_case = None
            self._refresh_list()
            return
        self._vm.apply_command(DeleteAnalysisCasesCommand(self._vm, {case.id}))
