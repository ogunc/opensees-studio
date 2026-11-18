"""Define → Load Combinations: factored sums and envelopes of analysis-case results.

The list on the left holds the project's combinations; the form on the right
edits the selected one (name, type, and a table of included cases or
combinations with their scale factors). Every change goes through an undoable
command. A combination is checked before it is applied: a missing or
non-combinable case, an empty list or a cycle of combinations is refused, and
adding a possibly nonlinear case is applied with a warning.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.commands import (
    AddAnalysisCasesCommand,
    AddCombinationsCommand,
    AddLoadPatternCommand,
    AddTimeSeriesCommand,
    DeleteCombinationsCommand,
    UpdateCombinationCommand,
)
from opensees_studio.core import (
    COMBINATION_LABELS,
    COMBINATION_TYPES,
    CombinationTerm,
    LoadCombination,
    Project,
    make_load_cases,
)
from opensees_studio.core.code_combinations import (
    CODES,
    DEFAULT_CODE,
    GeneratorOption,
    default_options,
    envelope_groups,
    generate_for_code,
    missing_load_cases,
    unused_roles,
)
from opensees_studio.core.combinations import (
    COMBINABLE_CASE_TYPES,
    LOAD_ROLE_LABELS,
    LOAD_ROLES,
    combination_problems,
    combinations_using_combination,
    guess_load_role,
    superposition_warnings,
)
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

ENVELOPE_NAME = "LRFD envelope"
"""Name of the envelope the ASCE 7-16 LRFD generator adds over what it generated."""


def envelope_name(group: str) -> str:
    """Name of the envelope over one generated group (``LRFD`` → ``LRFD envelope``)."""
    return f"{group} envelope"


def _key(source: str, ref_id: int) -> str:
    """Item data of a term source: ``case:3`` or ``combination:2``."""
    return f"{source}:{ref_id}"


def _combinable_cases(project: Project) -> list[Any]:
    return [c for c in project.analyses if c.type in COMBINABLE_CASE_TYPES]


class _TermRow:
    """The two cell widgets of one term row."""

    def __init__(self, source: QComboBox, factor: FloatField) -> None:
        self.source = source
        self.factor = factor


class LoadCombinationsDialog(FittedDialog):
    """Library-style editor for ``project.combinations``."""

    def __init__(self, vm: ProjectViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Load Combinations")
        self.resize(860, 560)
        self._vm = vm
        self._rows: list[_TermRow] = []
        self._build_ui()
        self._refresh_list()
        self._vm.modelMutated.connect(self._refresh_list)

    # ── UI ───────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        intro = QLabel(
            "<b>Load Combinations</b> combine the stored results of analysis cases "
            "(Static and Response Spectrum) or of other combinations. Nothing is re-run: "
            "pick a combination in Analyze → Run, which runs only the cases without "
            "current results."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        body = QHBoxLayout()
        outer.addLayout(body, stretch=1)

        left = QVBoxLayout()
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        left.addWidget(self._list, stretch=1)
        row = QHBoxLayout()
        self._add_btn = QPushButton("Add")
        self._copy_btn = QPushButton("Copy")
        self._delete_btn = QPushButton("Delete")
        self._add_btn.clicked.connect(self._on_add)
        self._copy_btn.clicked.connect(self._on_copy)
        self._delete_btn.clicked.connect(self._on_delete)
        for btn in (self._add_btn, self._copy_btn, self._delete_btn):
            row.addWidget(btn)
        left.addLayout(row)
        self._generate_btn = QPushButton("Generate from a design code…")
        self._generate_btn.setToolTip(
            "Add the combinations of ASCE 7-16 (LRFD or ASD), EN 1990 or TS 500 / TBDY 2018 "
            "from cases tagged Dead, Live, Roof live, Snow, Rain, Wind and Earthquake. "
            "They are ordinary combinations: edit them freely."
        )
        self._generate_btn.clicked.connect(self._on_generate)
        left.addWidget(self._generate_btn)
        body.addLayout(left, stretch=1)

        right = QVBoxLayout()
        form = QFormLayout()
        self._name = QLineEdit()
        form.addRow("Name:", self._name)
        self._type = QComboBox()
        for kind in COMBINATION_TYPES:
            self._type.addItem(COMBINATION_LABELS[kind], kind)
        self._type.setToolTip(
            "Linear Add: factored sum. Envelope: maximum and minimum over the terms. "
            "Absolute Add: sum of magnitudes. SRSS: square root of the sum of squares."
        )
        form.addRow("Type:", self._type)
        right.addLayout(form)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Case / combination", "Scale factor"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        right.addWidget(self._table, stretch=1)

        term_row = QHBoxLayout()
        self._add_term_btn = QPushButton("Add term")
        self._remove_term_btn = QPushButton("Remove term")
        self._add_term_btn.clicked.connect(lambda: self.add_term())
        self._remove_term_btn.clicked.connect(self._on_remove_term)
        term_row.addWidget(self._add_term_btn)
        term_row.addWidget(self._remove_term_btn)
        term_row.addStretch(1)
        right.addLayout(term_row)

        self._message = MessageArea()
        right.addWidget(self._message)
        self._apply_btn = QPushButton("Apply changes")
        self._apply_btn.clicked.connect(self.apply)
        right.addWidget(self._apply_btn, alignment=Qt.AlignmentFlag.AlignRight)
        self._editor = QWidget()
        self._editor.setLayout(right)
        body.addWidget(self._editor, stretch=2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # ── list ─────────────────────────────────────────────────────────
    def _refresh_list(self) -> None:
        selected = self.selected_id()
        self._list.blockSignals(True)
        self._list.clear()
        project = self._vm.project
        for combo in project.combinations if project is not None else []:
            label = f"{combo.name or '(unnamed)'}  [{COMBINATION_LABELS[combo.combination_type]}]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, combo.id)
            self._list.addItem(item)
        self._list.blockSignals(False)
        if selected is not None:
            self.select(selected)
        if self._list.currentRow() < 0 and self._list.count():
            self._list.setCurrentRow(0)
        else:
            self._on_row_changed(self._list.currentRow())
        has_project = project is not None
        self._add_btn.setEnabled(has_project)
        self._generate_btn.setEnabled(has_project)
        self._copy_btn.setEnabled(self._list.count() > 0)
        self._delete_btn.setEnabled(self._list.count() > 0)

    def selected_id(self) -> int | None:
        item = self._list.currentItem()
        return None if item is None else int(item.data(Qt.ItemDataRole.UserRole))

    def select(self, combination_id: int) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == combination_id:
                self._list.setCurrentRow(i)
                return

    def _selected(self) -> LoadCombination | None:
        cid = self.selected_id()
        project = self._vm.project
        if cid is None or project is None:
            return None
        return next((c for c in project.combinations if c.id == cid), None)

    def _on_row_changed(self, _row: int) -> None:
        combo = self._selected()
        self._editor.setEnabled(combo is not None)
        self._message.clear_message()
        self._table.setRowCount(0)
        self._rows = []
        if combo is None:
            self._name.clear()
            return
        self._name.setText(combo.name)
        self._type.setCurrentIndex(max(0, self._type.findData(combo.combination_type)))
        for term in combo.terms:
            self.add_term(term)

    # ── terms ────────────────────────────────────────────────────────
    def _source_choices(self, current: CombinationTerm | None) -> QComboBox:
        box = QComboBox()
        project = self._vm.project
        own_id = self.selected_id()
        if project is not None:
            for case in _combinable_cases(project):
                box.addItem(f"Case: {case.name or case.id}  [{case.type}]", _key("case", case.id))
            for combo in project.combinations:
                if combo.id != own_id:
                    box.addItem(
                        f"Combination: {combo.name or combo.id}", _key("combination", combo.id)
                    )
        if current is not None:
            key = _key(current.source, current.ref_id)
            index = box.findData(key)
            if index < 0:
                # A reference the list cannot offer (deleted, or not combinable):
                # shown as is, and refused when applied.
                box.addItem(f"(unavailable {current.source} {current.ref_id})", key)
                index = box.count() - 1
            box.setCurrentIndex(index)
        return box

    def add_term(self, term: CombinationTerm | None = None) -> None:
        """Append a term row (the first offered case at factor 1 when ``term`` is None)."""
        source = self._source_choices(term)
        factor = FloatField()
        factor.setRange(-1e12, 1e12)
        factor.setSingleStep(0.1)
        factor.setValue(term.factor if term is not None else 1.0)
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setCellWidget(row, 0, source)
        self._table.setCellWidget(row, 1, factor)
        self._rows.append(_TermRow(source, factor))

    def _on_remove_term(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            row = self._table.rowCount() - 1
        if row < 0:
            return
        self._table.removeRow(row)
        del self._rows[row]

    def term_count(self) -> int:
        return len(self._rows)

    def set_term(self, row: int, source: str, ref_id: int, factor: float) -> None:
        """Point term ``row`` at ``source`` ``ref_id`` with ``factor`` (for scripts and tests)."""
        cells = self._rows[row]
        index = cells.source.findData(_key(source, ref_id))
        if index < 0:
            raise ValueError(f"{source} {ref_id} is not offered.")
        cells.source.setCurrentIndex(index)
        cells.factor.setValue(factor)

    def set_name(self, name: str) -> None:
        self._name.setText(name)

    def set_type(self, combination_type: str) -> None:
        self._type.setCurrentIndex(self._type.findData(combination_type))

    # ── apply ────────────────────────────────────────────────────────
    def read(self) -> LoadCombination:
        """The combination the form describes (raises ``ValidationError``)."""
        cid = self.selected_id()
        if cid is None:
            raise ValueError("No combination is selected.")
        terms = []
        for cells in self._rows:
            data = cells.source.currentData()
            if data is None:
                continue
            source, ref_id = str(data).split(":")
            terms.append(
                CombinationTerm(
                    source=source,  # type: ignore[arg-type]
                    ref_id=int(ref_id),
                    factor=float(cells.factor.value()),
                )
            )
        return LoadCombination(
            id=cid,
            name=self._name.text().strip(),
            combination_type=self._type.currentData(),
            terms=terms,
        )

    def apply(self) -> bool:
        """Check the form and apply it as one undo step; False when refused."""
        project = self._vm.project
        if project is None or self.selected_id() is None:
            return False
        try:
            combo = self.read()
        except (ValidationError, ValueError) as exc:
            self._message.show_message(f"Combination rejected: {exc}", "error")
            return False
        trial = project.model_copy(
            update={
                "combinations": [combo if c.id == combo.id else c for c in project.combinations]
            }
        )
        problems = combination_problems(trial, combo)
        if problems:
            self._message.show_message("Combination rejected:\n" + "\n".join(problems), "error")
            return False
        self._vm.apply_command(UpdateCombinationCommand(self._vm, combo))
        warnings = superposition_warnings(project, combo)
        if warnings:
            self._message.show_message("\n".join(warnings), "warning")
        else:
            self._message.show_message(f"Combination '{combo.name}' updated.")
        return True

    def message_text(self) -> str:
        return self._message.text()

    def message_level(self) -> str:
        return self._message.level

    # ── add / copy / delete ─────────────────────────────────────────
    def _on_add(self) -> None:
        project = self._vm.project
        if project is None:
            return
        cases = _combinable_cases(project)
        if not cases:
            self._message.show_message(
                "Define a Static or Response Spectrum case first (Analyze → Cases…): "
                "a combination combines their results.",
                "error",
            )
            return
        new_id = project.next_combination_id()
        combo = LoadCombination(
            id=new_id, name=f"COMB{new_id}", terms=[CombinationTerm(ref_id=cases[0].id)]
        )
        self._vm.apply_command(AddCombinationsCommand(self._vm, [combo]))
        self.select(new_id)

    def _on_copy(self) -> None:
        project = self._vm.project
        combo = self._selected()
        if project is None or combo is None:
            return
        new_id = project.next_combination_id()
        copy = combo.model_copy(update={"id": new_id, "name": f"{combo.name} copy"}, deep=True)
        self._vm.apply_command(
            AddCombinationsCommand(self._vm, [copy], text=f"Copy load combination '{combo.name}'")
        )
        self.select(new_id)

    def _on_delete(self) -> None:
        project = self._vm.project
        combo = self._selected()
        if project is None or combo is None:
            return
        users = combinations_using_combination(project, combo.id)
        if users:
            names = ", ".join(f"'{u.name}'" for u in users)
            self._message.show_message(
                f"'{combo.name}' is included in {names}: remove it there first.", "error"
            )
            return
        self._vm.apply_command(DeleteCombinationsCommand(self._vm, {combo.id}))

    # ── design-code generators ──────────────────────────────────────
    def _on_generate(self) -> None:
        project = self._vm.project
        if project is None:
            return
        cases = _combinable_cases(project)
        dlg = CodeGeneratorDialog(cases, self, ndm=project.ndm)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.generate(
            dlg.code(),
            dlg.roles(),
            dlg.options(),
            envelope=dlg.envelope_wanted(),
            create_missing=dlg.create_missing_wanted(),
        )

    def generate(
        self,
        code: str,
        roles: dict[str, list[int]],
        options: dict[str, Any] | None = None,
        *,
        envelope: bool = True,
        create_missing: bool = False,
    ) -> int:
        """Add the combinations of design ``code`` for ``roles`` as one undo step.

        With ``envelope`` each generated group of more than one combination
        also gets an envelope over it. With ``create_missing`` every load the
        code uses that ``roles`` has no case for first gets an empty load
        case of its own (see :func:`missing_load_cases`; a missing dead load
        gets the self weight), in the same undo step. Returns how many
        combinations were added (the envelopes included).
        """
        project = self._vm.project
        if project is None:
            return 0
        spec = CODES[code]
        roles = {role: list(ids) for role, ids in roles.items()}
        missing = missing_load_cases(code, roles, project.ndm) if create_missing else []
        if not missing:
            return self._generate(code, roles, options, envelope, missing)
        stack = self._vm.undo_stack
        stack.beginMacro(f"Generate {spec.label} combinations")
        try:
            return self._generate(code, roles, options, envelope, missing)
        finally:
            stack.endMacro()

    def _generate(
        self,
        code: str,
        roles: dict[str, list[int]],
        options: dict[str, Any] | None,
        envelope: bool,
        missing: list[tuple[str, str]],
    ) -> int:
        project = self._vm.project
        assert project is not None
        spec = CODES[code]
        created: list[str] = []
        if missing:
            new_names = [name for _role, name in missing]
            dead = frozenset(name for role, name in missing if role == "D")
            series, patterns, cases = make_load_cases(project, new_names, self_weight=dead)
            for ts in series:
                self._vm.apply_command(AddTimeSeriesCommand(self._vm, ts))
            for pattern in patterns:
                self._vm.apply_command(AddLoadPatternCommand(self._vm, pattern))
            self._vm.apply_command(AddAnalysisCasesCommand(self._vm, list(cases)))
            for (role, name), case in zip(missing, cases, strict=True):
                roles.setdefault(role, []).append(case.id)
                created.append(name)
        peaks = [c.id for c in project.analyses if c.type == "ResponseSpectrum"]
        names = {c.id: c.name or str(c.id) for c in project.analyses}
        generated = generate_for_code(
            code, roles, peak_cases=peaks, case_names=names, options=options
        )
        if not generated:
            self._message.show_message(
                f"Nothing generated: every {spec.label} combination needs a Dead case.",
                "error",
            )
            return 0
        next_id = project.next_combination_id()
        combos: list[LoadCombination] = []
        group_ids: dict[str, list[int]] = {g: [] for g in envelope_groups(generated)}
        for combo in generated:
            new_id = next_id + len(combos)
            combos.append(LoadCombination(id=new_id, name=combo.name, terms=combo.terms))
            group_ids[combo.group].append(new_id)
        if envelope:
            for group, ids in group_ids.items():
                if len(ids) > 1:
                    combos.append(
                        LoadCombination(
                            id=next_id + len(combos),
                            name=envelope_name(group),
                            combination_type="Envelope",
                            terms=[CombinationTerm(source="combination", ref_id=i) for i in ids],
                        )
                    )
        self._vm.apply_command(
            AddCombinationsCommand(
                self._vm, combos, text=f"Generate {len(combos)} {spec.label} combination(s)"
            )
        )
        self.select(combos[-1].id)
        text = f"Added {len(combos)} {spec.label} combination(s)."
        if created:
            text += (
                " Created the load case(s) " + ", ".join(created) + ": their patterns are "
                "empty (the dead load carries the self weight), assign their loads before "
                "running."
            )
        left_out = unused_roles(code, roles)
        if left_out:
            text += (
                " Not used by this code: " + ", ".join(LOAD_ROLE_LABELS[r] for r in left_out) + "."
            )
        self._message.show_message(text)
        return len(combos)


class CodeGeneratorDialog(FittedDialog):
    """Pick a design code and tag each case with its load role."""

    def __init__(self, cases: list[Any], parent: QWidget | None = None, *, ndm: int = 3) -> None:
        super().__init__(parent)
        self._ndm = ndm
        self.setWindowTitle("Generate Code Combinations")
        layout = QVBoxLayout(self)
        top = QFormLayout()
        self._code = QComboBox()
        for key, spec in CODES.items():
            self._code.addItem(spec.label, key)
        top.addRow("Design code:", self._code)
        layout.addLayout(top)
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        self._options_form = QFormLayout()
        layout.addLayout(self._options_form)
        self._option_widgets: dict[str, QWidget] = {}

        intro = QLabel(
            "Give each case the load it carries. Wind and static earthquake cases are "
            "applied in both signs."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self._boxes: dict[int, QComboBox] = {}
        for case in cases:
            box = QComboBox()
            box.addItem("(not used)", None)
            for role in LOAD_ROLES:
                box.addItem(LOAD_ROLE_LABELS[role], role)
            guess = guess_load_role(case.name)
            if guess is not None:
                box.setCurrentIndex(box.findData(guess))
            form.addRow(f"{case.name or case.id} [{case.type}]:", box)
            self._boxes[case.id] = box
            box.currentIndexChanged.connect(self._update_missing)
        layout.addLayout(form)
        self._create_missing = QCheckBox("Create the missing load cases")
        self._create_missing.setChecked(True)
        self._create_missing.setToolTip(
            "Every load the code uses that no case is tagged with gets an empty "
            "pattern and a static case of its own (wind and earthquake one per "
            "horizontal axis); assign their loads afterwards."
        )
        layout.addWidget(self._create_missing)
        self._missing_label = QLabel()
        self._missing_label.setWordWrap(True)
        layout.addWidget(self._missing_label)
        self._envelope = QCheckBox("Also add an envelope over each generated group")
        self._envelope.setChecked(True)
        layout.addWidget(self._envelope)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._code.currentIndexChanged.connect(self._on_code_changed)
        self.set_code(DEFAULT_CODE)

    # ── design code and its options ──────────────────────────────────
    def code(self) -> str:
        return str(self._code.currentData())

    def set_code(self, key: str) -> None:
        self._code.setCurrentIndex(self._code.findData(key))
        self._on_code_changed()

    def _on_code_changed(self) -> None:
        spec = CODES[self.code()]
        self._summary.setText(spec.summary)
        self._update_missing()
        while self._options_form.rowCount():
            self._options_form.removeRow(0)
        self._option_widgets.clear()
        for option in spec.options:
            widget = self._option_widget(option)
            self._option_widgets[option.key] = widget
            if option.kind == "bool":
                self._options_form.addRow(widget)
            else:
                self._options_form.addRow(option.label + ":", widget)

    @staticmethod
    def _option_widget(option: GeneratorOption) -> QWidget:
        widget: QWidget
        if option.kind == "bool":
            check = QCheckBox(option.label)
            check.setChecked(bool(option.default))
            widget = check
        elif option.kind == "choice":
            box = QComboBox()
            for value, label in option.choices:
                box.addItem(label, value)
            box.setCurrentIndex(box.findData(option.default))
            widget = box
        else:
            field = FloatField()
            field.setRange(0.0, 10.0)
            field.setValue(float(option.default))
            widget = field
        widget.setToolTip(option.tip)
        return widget

    def options(self) -> dict[str, Any]:
        """The current value of every option of the selected code."""
        out = default_options(self.code())
        for key, widget in self._option_widgets.items():
            if isinstance(widget, QCheckBox):
                out[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                out[key] = widget.currentData()
            elif isinstance(widget, FloatField):
                out[key] = float(widget.value())
        return out

    def set_option(self, key: str, value: Any) -> None:
        widget = self._option_widgets[key]
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QComboBox):
            widget.setCurrentIndex(widget.findData(value))
        elif isinstance(widget, FloatField):
            widget.setValue(float(value))

    # ── case roles ───────────────────────────────────────────────────
    def set_role(self, case_id: int, role: str | None) -> None:
        box = self._boxes[case_id]
        box.setCurrentIndex(0 if role is None else box.findData(role))

    def roles(self) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for case_id, box in self._boxes.items():
            role = box.currentData()
            if role is not None:
                out.setdefault(str(role), []).append(case_id)
        return out

    def envelope_wanted(self) -> bool:
        return self._envelope.isChecked()

    def create_missing_wanted(self) -> bool:
        return self._create_missing.isChecked()

    def set_create_missing(self, on: bool) -> None:
        self._create_missing.setChecked(on)

    def missing_names(self) -> list[str]:
        """Names of the load cases "Create the missing load cases" would add."""
        return [name for _role, name in missing_load_cases(self.code(), self.roles(), self._ndm)]

    def _update_missing(self) -> None:
        if not hasattr(self, "_missing_label"):
            return  # still building the dialog
        names = self.missing_names()
        self._create_missing.setEnabled(bool(names))
        self._missing_label.setText(
            "Would create: " + ", ".join(names) if names else "Every load of this code has a case."
        )
