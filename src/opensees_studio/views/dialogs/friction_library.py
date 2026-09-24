"""Friction Model Library: the Material Library pattern for ``frictionModel``.

List on the left, parameter form on the right; every Add, Apply and Delete
is its own undoable command. Deleting a friction model that a sliding
bearing references is refused (the command raises and the dialog explains).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.commands import (
    AddFrictionModelsCommand,
    DeleteFrictionModelsCommand,
    UpdateFrictionModelCommand,
    friction_model_users,
)
from opensees_studio.core import (
    CoulombFriction,
    VelDependentFriction,
    VelNormalFrcDepFriction,
)
from opensees_studio.viewmodels import ProjectViewModel


def _spin(default: float, *, minimum: float = -1e15, decimals: int = 6) -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setLocale(QLocale(QLocale.Language.C))
    sb.setKeyboardTracking(False)
    sb.setRange(minimum, 1e15)
    sb.setDecimals(decimals)
    sb.setSingleStep(0.01)
    sb.setValue(default)
    return sb


class FrictionFormBase(QWidget):
    """Name field plus the concrete parameters; ``read`` returns the validated model."""

    type_label: str = "Friction model"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model_id: int | None = None
        self._layout = QFormLayout(self)
        self._name_edit = QLineEdit()
        self._layout.addRow("Name:", self._name_edit)

    def populate(self, model: Any) -> None:
        self._model_id = model.id
        self._name_edit.setText(model.name)
        self._populate_specific(model)

    def _populate_specific(self, model: Any) -> None: ...

    def read(self, model_id: int | None = None) -> Any:
        mid = self._model_id if self._model_id is not None else model_id
        if mid is None:
            raise ValueError("Friction model id required.")
        return self._read_specific(mid)

    def _read_specific(self, model_id: int) -> Any:
        raise NotImplementedError


class CoulombForm(FrictionFormBase):
    type_label = "Coulomb (constant mu)"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mu = _spin(0.1, minimum=0.0)
        self._layout.addRow("mu:", self._mu)

    def _populate_specific(self, m: CoulombFriction) -> None:
        self._mu.setValue(m.mu)

    def _read_specific(self, mid: int) -> CoulombFriction:
        return CoulombFriction(id=mid, name=self._name_edit.text(), mu=self._mu.value())


class VelDependentForm(FrictionFormBase):
    type_label = "VelDependent (muSlow to muFast with velocity)"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mu_slow = _spin(0.05, minimum=0.0)
        self._mu_fast = _spin(0.1, minimum=0.0)
        self._rate = _spin(0.5, minimum=0.0)
        self._layout.addRow("muSlow:", self._mu_slow)
        self._layout.addRow("muFast:", self._mu_fast)
        self._layout.addRow("transRate (time/length):", self._rate)

    def _populate_specific(self, m: VelDependentFriction) -> None:
        self._mu_slow.setValue(m.mu_slow)
        self._mu_fast.setValue(m.mu_fast)
        self._rate.setValue(m.trans_rate)

    def _read_specific(self, mid: int) -> VelDependentFriction:
        return VelDependentFriction(
            id=mid,
            name=self._name_edit.text(),
            mu_slow=self._mu_slow.value(),
            mu_fast=self._mu_fast.value(),
            trans_rate=self._rate.value(),
        )


class VelNormalFrcDepForm(FrictionFormBase):
    type_label = "VelNormalFrcDep (velocity and normal-force dependent)"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._a_slow = _spin(0.1, minimum=0.0)
        self._n_slow = _spin(0.0)
        self._a_fast = _spin(0.2, minimum=0.0)
        self._n_fast = _spin(0.0)
        self._alpha0 = _spin(0.0, minimum=0.0)
        self._alpha1 = _spin(0.0, minimum=0.0)
        self._alpha2 = _spin(0.0, minimum=0.0)
        self._max_mu_fact = _spin(1.0, minimum=0.0)
        self._layout.addRow("aSlow:", self._a_slow)
        self._layout.addRow("nSlow:", self._n_slow)
        self._layout.addRow("aFast:", self._a_fast)
        self._layout.addRow("nFast:", self._n_fast)
        self._layout.addRow("alpha0:", self._alpha0)
        self._layout.addRow("alpha1:", self._alpha1)
        self._layout.addRow("alpha2:", self._alpha2)
        self._layout.addRow("maxMuFact:", self._max_mu_fact)

    def _populate_specific(self, m: VelNormalFrcDepFriction) -> None:
        self._a_slow.setValue(m.a_slow)
        self._n_slow.setValue(m.n_slow)
        self._a_fast.setValue(m.a_fast)
        self._n_fast.setValue(m.n_fast)
        self._alpha0.setValue(m.alpha0)
        self._alpha1.setValue(m.alpha1)
        self._alpha2.setValue(m.alpha2)
        self._max_mu_fact.setValue(m.max_mu_fact)

    def _read_specific(self, mid: int) -> VelNormalFrcDepFriction:
        return VelNormalFrcDepFriction(
            id=mid,
            name=self._name_edit.text(),
            a_slow=self._a_slow.value(),
            n_slow=self._n_slow.value(),
            a_fast=self._a_fast.value(),
            n_fast=self._n_fast.value(),
            alpha0=self._alpha0.value(),
            alpha1=self._alpha1.value(),
            alpha2=self._alpha2.value(),
            max_mu_fact=self._max_mu_fact.value(),
        )


FRICTION_FORM_REGISTRY: dict[str, type[FrictionFormBase]] = {
    "Coulomb": CoulombForm,
    "VelDependent": VelDependentForm,
    "VelNormalFrcDep": VelNormalFrcDepForm,
}


def friction_form_for(model: Any) -> FrictionFormBase:
    form = FRICTION_FORM_REGISTRY[model.type]()
    form.populate(model)
    return form


class FrictionLibraryDialog(QDialog):
    """Manage the project's friction models: add, edit, delete."""

    def __init__(self, vm: ProjectViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Friction Model Library")
        self.resize(640, 420)
        self._vm = vm
        self._build_ui()
        self._refresh_list()
        self._vm.modelMutated.connect(self._refresh_list)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(
            QLabel(
                "<b>Friction models</b> for flat slider and single FP bearings; "
                "every change is undoable from the main window."
            )
        )
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
        self._type_label = QLabel("(no friction model selected)")
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
        selected_id = None
        if self._list.currentItem() is not None:
            selected_id = self._list.currentItem().data(Qt.ItemDataRole.UserRole)
        self._list.clear()
        for fm in self._vm.project.friction_models if self._vm.project else []:
            item = QListWidgetItem(f"#{fm.id}  {fm.name or '(unnamed)'}  [{fm.type}]")
            item.setData(Qt.ItemDataRole.UserRole, fm.id)
            self._list.addItem(item)
        if selected_id is not None:
            self._select_by_id(selected_id)
        if self._list.currentRow() < 0 and self._list.count():
            self._list.setCurrentRow(0)
        if self._list.count() == 0:
            self._stack.setCurrentIndex(-1)
            self._type_label.setText("(no friction model selected)")

    def _selected_model(self) -> Any | None:
        item = self._list.currentItem()
        if item is None or self._vm.project is None:
            return None
        fid = item.data(Qt.ItemDataRole.UserRole)
        return next((fm for fm in self._vm.project.friction_models if fm.id == fid), None)

    def _on_row_changed(self, _row: int) -> None:
        model = self._selected_model()
        if model is None:
            return
        while self._stack.count():
            old = self._stack.widget(0)
            self._stack.removeWidget(old)
            old.deleteLater()
        form = friction_form_for(model)
        self._stack.addWidget(form)
        self._stack.setCurrentWidget(form)
        self._type_label.setText(form.type_label)

    def _on_apply(self) -> None:
        if self._stack.count() == 0 or self._vm.project is None:
            return
        form = self._stack.currentWidget()
        try:
            self._vm.apply_command(UpdateFrictionModelCommand(self._vm, form.read()))
        except (ValidationError, ValueError) as exc:
            QMessageBox.critical(self, "Validation error", str(exc))

    def _on_add(self) -> None:
        if self._vm.project is None:
            return
        kinds = list(FRICTION_FORM_REGISTRY.keys())
        kind, ok = QInputDialog.getItem(
            self, "Add friction model", "Type:", kinds, current=0, editable=False
        )
        if not ok:
            return
        self.add_model(kind)

    def add_model(self, kind: str) -> Any | None:
        """Add a default-valued model of ``kind``; returns it, None when refused."""
        if self._vm.project is None:
            return None
        new_id = self._vm.project.next_friction_model_id()
        try:
            model = FRICTION_FORM_REGISTRY[kind]().read(new_id)
        except (ValidationError, ValueError) as exc:
            QMessageBox.critical(self, "Could not create friction model", str(exc))
            return None
        self._vm.apply_command(AddFrictionModelsCommand(self._vm, [model]))
        self._select_by_id(new_id)
        return model

    def _select_by_id(self, target_id: int) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == target_id:
                self._list.setCurrentRow(i)
                return

    def _on_delete(self) -> None:
        model = self._selected_model()
        if model is None or self._vm.project is None:
            return
        self.delete_model(model.id, confirm=True)

    def delete_model(self, friction_model_id: int, *, confirm: bool = False) -> bool:
        """Delete the model unless a sliding bearing uses it; returns True on success."""
        if self._vm.project is None:
            return False
        users = friction_model_users(self._vm.project, friction_model_id)
        if users:
            QMessageBox.warning(
                self,
                "Friction model in use",
                f"Friction model #{friction_model_id} is used by bearing element(s) "
                f"{', '.join(str(u) for u in users)}. Reassign or delete them first.",
            )
            return False
        if confirm:
            reply = QMessageBox.question(
                self, "Delete friction model", f"Delete friction model #{friction_model_id}?"
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False
        try:
            self._vm.apply_command(DeleteFrictionModelsCommand(self._vm, {friction_model_id}))
        except ValueError as exc:
            QMessageBox.warning(self, "Friction model in use", str(exc))
            return False
        return True
