"""Design → Design Basis (AISC) and Design → Direct Analysis Method.

The design basis is where a steel design starts: the code and its method (LRFD or
ASD), how stability is designed for (AISC 360 Chapter C or Appendix 7), the
lateral system of each direction with its ASCE 7 coefficients, and the steel grade
of each shape family. It is kept in ``Project.design`` and every later check reads
it.

The direct analysis dialog turns the ASCE 7 LRFD combinations into the analysis
cases of the method (:mod:`core.design.direct_analysis`), from the load role of
each case, and once they have run shows the second- to first-order drift ratio
of every storey, which decides where the notional loads act (C2.2b(d)).

Neither dialog changes the project: the window stores what they hand back with
one undoable command.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.analysis import ResponseSpectrumCase, StaticCase
from opensees_studio.core.combinations import LOAD_ROLE_LABELS, LOAD_ROLES, guess_load_role
from opensees_studio.core.design.direct_analysis import (
    DRIFT_RATIO_LIMIT,
    DriftRatio,
    GeneratedCases,
    direct_analysis_cases,
    drift_ratios,
    is_direct_analysis_case,
    notional_everywhere_required,
)
from opensees_studio.core.design.settings import (
    SEISMIC_SYSTEM_LABELS,
    STABILITY_METHOD_LABELS,
    SYSTEM_COEFFICIENTS,
    DesignSettings,
)
from opensees_studio.core.design.steel_grades import (
    DEFAULT_GRADES,
    FAMILY_LABELS,
    STEEL_GRADES,
    grade_stresses,
)
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import labels_for
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog

PROJECT_STEEL = "Project Fy / Fu"
"""The grade choice that leaves a family on the project's Fy and Fu."""


def _ok_cancel(dialog: FittedDialog) -> QDialogButtonBox:
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    return buttons


class DesignBasisDialog(FittedDialog):
    """Code, method, stability method, lateral systems and steel grades of a project."""

    def __init__(self, project: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._base = project.design or DesignSettings()
        self.setWindowTitle("Design Basis (AISC)")
        self.setProperty(TOPIC_PROPERTY, "design.basis")
        layout = QVBoxLayout(self)

        code = QGroupBox("Code and method")
        form = QFormLayout(code)
        form.addRow("Code:", QLabel("AISC 360-16, AISC 341-22, ASCE 7-16/22 combinations"))
        self._method = QComboBox()
        self._method.addItems(["LRFD", "ASD"])
        self._method.setCurrentText(self._base.method)
        form.addRow("Design method:", self._method)
        self._stability = QComboBox()
        for key, label in STABILITY_METHOD_LABELS.items():
            self._stability.addItem(label, key)
        self._stability.setCurrentIndex(self._stability.findData(self._base.stability_method))
        self._stability.setToolTip(
            "Direct Analysis Method: second-order analysis with reduced stiffness and "
            "notional loads, every member checked with K = 1 (generate its cases with "
            "Design → Direct Analysis Method)."
        )
        form.addRow("Stability design:", self._stability)
        layout.addWidget(code)

        lateral = QGroupBox("Lateral system (ASCE 7 Table 12.2-1)")
        form = QFormLayout(lateral)
        self._system_x = QComboBox()
        for key, label in SEISMIC_SYSTEM_LABELS.items():
            self._system_x.addItem(label, key)
        self._system_x.setCurrentIndex(self._system_x.findData(self._base.seismic_system))
        form.addRow("Along X:", self._system_x)
        self._system_y = QComboBox()
        self._system_y.addItem("Same as X", None)
        for key, label in SEISMIC_SYSTEM_LABELS.items():
            self._system_y.addItem(label, key)
        self._system_y.setCurrentIndex(max(0, self._system_y.findData(self._base.seismic_system_y)))
        if project.ndm == 3:
            form.addRow("Along Y:", self._system_y)
        else:
            self._system_y.setVisible(False)
        self._coefficients = QLabel()
        form.addRow("R, Ω0, Cd:", self._coefficients)
        self._sds = FloatField()
        self._sds.setRange(1e-6, 10.0)
        self._sds.setValue(self._base.sds or 1.0)
        self._sds.setToolTip("SDS (g) of the 0.2 SDS D term of the overstrength combinations.")
        form.addRow("SDS:", self._sds)
        self._ry = FloatField()
        self._ry.setRange(0.1, 3.0)
        self._ry.setValue(self._base.ry)
        self._ry.setToolTip("AISC 341 Table A3.1: 1.1 for A992 and A572 Gr. 50, 1.5 for A36.")
        form.addRow("Ry:", self._ry)
        layout.addWidget(lateral)

        steel = QGroupBox("Steel by shape family")
        box = QVBoxLayout(steel)
        self._grades = QTableWidget(len(FAMILY_LABELS), 3)
        stress = labels_for(project.meta.units).stress
        self._grades.setHorizontalHeaderLabels(["Family", "Grade", f"Fy / Fu [{stress}]"])
        self._grade_boxes: dict[str, QComboBox] = {}
        for row, (family, label) in enumerate(FAMILY_LABELS.items()):
            self._grades.setItem(row, 0, QTableWidgetItem(label))
            combo = QComboBox()
            combo.addItem(PROJECT_STEEL, None)
            for key, grade in STEEL_GRADES.items():
                combo.addItem(grade.label, key)
            combo.setCurrentIndex(max(0, combo.findData(self._base.steel_grades.get(family))))
            combo.currentIndexChanged.connect(self._update_stresses)
            self._grades.setCellWidget(row, 1, combo)
            self._grade_boxes[family] = combo
        self._grades.resizeColumnsToContents()
        box.addWidget(self._grades)
        defaults = QPushButton("AISC Manual defaults (Table 2-4)")
        defaults.setToolTip(
            "A992 for W and WT, A572 Gr. 50 for M, HP and MT, A36 for S, ST, channels "
            "and angles, A500 Gr. C for HSS, A53 Gr. B for pipe."
        )
        defaults.clicked.connect(self.apply_manual_defaults)
        row_layout = QHBoxLayout()
        row_layout.addWidget(defaults)
        row_layout.addStretch(1)
        box.addLayout(row_layout)
        layout.addWidget(steel)

        layout.addWidget(_ok_cancel(self))
        self._system_x.currentIndexChanged.connect(self._update_coefficients)
        self._system_y.currentIndexChanged.connect(self._update_coefficients)
        self._update_coefficients()
        self._update_stresses()

    def apply_manual_defaults(self) -> None:
        for family, combo in self._grade_boxes.items():
            combo.setCurrentIndex(combo.findData(DEFAULT_GRADES[family]))

    def _update_coefficients(self) -> None:
        parts = []
        systems = [("X", self._system_x.currentData())]
        if self._project.ndm == 3:
            systems.append(("Y", self._system_y.currentData() or self._system_x.currentData()))
        for axis, system in systems:
            if system in SYSTEM_COEFFICIENTS:
                r, omega0, cd = SYSTEM_COEFFICIENTS[system]
                parts.append(f"{axis}: R = {r:g}, Ω0 = {omega0:g}, Cd = {cd:g}")
            else:
                parts.append(f"{axis}: no seismic system")
        self._coefficients.setText("; ".join(parts))

    def _update_stresses(self) -> None:
        units = self._project.meta.units
        for row, (family, combo) in enumerate(self._grade_boxes.items()):
            key = combo.currentData()
            if key is None:
                text = "project"
            else:
                fy, fu = grade_stresses(key, family, units)
                text = f"{fy:.4g} / {fu:.4g}"
            self._grades.setItem(row, 2, QTableWidgetItem(text))

    def settings(self) -> DesignSettings:
        grades = {
            family: combo.currentData()
            for family, combo in self._grade_boxes.items()
            if combo.currentData() is not None
        }
        sds = self._sds.value()
        return self._base.model_copy(
            update={
                "method": self._method.currentText(),
                "stability_method": self._stability.currentData(),
                "seismic_system": self._system_x.currentData(),
                "seismic_system_y": self._system_y.currentData()
                if self._project.ndm == 3
                else None,
                "sds": None if abs(sds - 1.0) <= 1e-12 else sds,
                "ry": self._ry.value(),
                "steel_grades": grades,
            }
        )


class DirectAnalysisDialog(FittedDialog):
    """Generate the cases of the Direct Analysis Method and read their Δ2/Δ1."""

    def __init__(
        self, project: Any, results: Mapping[int, Any], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._results = results
        self._base = project.design or DesignSettings()
        self._generated: GeneratedCases | None = None
        self.setWindowTitle("Direct Analysis Method (AISC 360 Chapter C)")
        self.setProperty(TOPIC_PROPERTY, "design.direct_analysis")
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._cases_tab(), "Combinations")
        tabs.addTab(self._ratio_tab(), "Second-order check (Δ2/Δ1)")
        layout.addWidget(tabs)
        self._buttons = _ok_cancel(self)
        layout.addWidget(self._buttons)
        self._update_ratios()
        self._update_preview()

    # ── the cases ────────────────────────────────────────────────────
    def _cases_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "Each ASCE 7-16 LRFD combination becomes one second-order analysis: P-Delta "
            "in every frame, stiffness x0.8, and the notional loads of its own factored "
            "gravity. Give every load case its role; the cases replace any made here before."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        sources = [
            c
            for c in self._project.analyses
            if isinstance(c, StaticCase | ResponseSpectrumCase) and not is_direct_analysis_case(c)
        ]
        self._roles = QTableWidget(len(sources), 2)
        self._roles.setHorizontalHeaderLabels(["Load case", "Role"])
        self._role_boxes: dict[int, QComboBox] = {}
        for row, case in enumerate(sources):
            self._roles.setItem(row, 0, QTableWidgetItem(case.name or f"Case {case.id}"))
            combo = QComboBox()
            combo.addItem("Not used", None)
            for role in LOAD_ROLES:
                combo.addItem(LOAD_ROLE_LABELS[role], role)
            combo.setCurrentIndex(max(0, combo.findData(guess_load_role(case.name or ""))))
            combo.currentIndexChanged.connect(self._update_preview)
            self._roles.setCellWidget(row, 1, combo)
            self._role_boxes[case.id] = combo
        self._roles.resizeColumnsToContents()
        layout.addWidget(self._roles)
        self._everywhere = QCheckBox(
            f"Notional loads 0.002 α Yi in every combination (needed when Δ2/Δ1 > {DRIFT_RATIO_LIMIT:g})"
        )
        self._everywhere.toggled.connect(self._update_preview)
        layout.addWidget(self._everywhere)
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        layout.addWidget(self._preview)
        return page

    def roles(self) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for case_id, combo in self._role_boxes.items():
            role = combo.currentData()
            if role is not None:
                out.setdefault(role, []).append(case_id)
        return out

    def _first_id(self) -> int:
        kept = [c.id for c in self._project.analyses if not is_direct_analysis_case(c)]
        return max(kept, default=0) + 1

    def _update_preview(self) -> None:
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        try:
            self._generated = direct_analysis_cases(
                self._project,
                self._base,
                self.roles(),
                first_id=self._first_id(),
                notional_everywhere=self._everywhere.isChecked(),
            )
        except ValueError as exc:
            self._generated = None
            self._preview.setPlainText(str(exc))
            ok.setEnabled(False)
            return
        lines = [f"{len(self._generated.cases)} case(s):"]
        for case in self._generated.cases:
            factors = " ".join(
                f"{f:+g}×{pid}"
                for pid, f in zip(case.pattern_ids, case.pattern_factors, strict=True)
            )
            lines.append(
                f"  {case.name}  [patterns {factors}; notional {case.notional_ratio:g} Yi "
                f"{case.notional_direction}]"
            )
        lines += ["", *self._generated.notes]
        self._preview.setPlainText("\n".join(lines))
        ok.setEnabled(bool(self._generated.cases))

    def cases(self) -> list[StaticCase]:
        return list(self._generated.cases) if self._generated else []

    def settings(self) -> DesignSettings:
        """The design basis with the direct analysis method and its cases as the load sets."""
        return self._base.model_copy(update={"stability_method": "direct", "load_sets": []})

    # ── Δ2/Δ1 ───────────────────────────────────────────────────────
    def _ratio_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._ratio_status = QLabel()
        self._ratio_status.setWordWrap(True)
        layout.addWidget(self._ratio_status)
        self._ratio_table = QTableWidget(0, 5)
        self._ratio_table.setHorizontalHeaderLabels(
            ["Combination", "Storey", "Δ1 (first order)", "Δ2 (second order)", "Δ2/Δ1"]
        )
        layout.addWidget(self._ratio_table)
        return page

    def ratios(self) -> list[DriftRatio]:
        """Δ2/Δ1 of every storey of every lateral direct analysis case that has run."""
        cases = [c for c in self._project.analyses if is_direct_analysis_case(c)]
        out: list[DriftRatio] = []
        for case in cases:
            tag = case.direct_analysis
            if tag.order != "second" or not tag.lateral:
                continue
            twin = next(
                (
                    c
                    for c in cases
                    if c.direct_analysis.order == "first"
                    and c.direct_analysis.combination == tag.combination
                ),
                None,
            )
            if twin is None or case.id not in self._results or twin.id not in self._results:
                continue

            def final(result: Any) -> dict[int, np.ndarray]:
                return {nid: np.atleast_2d(v)[-1] for nid, v in result.node_disp.items()}

            out += drift_ratios(
                self._project,
                case,
                final(self._results[twin.id]),
                final(self._results[case.id]),
            )
        return out

    def _update_ratios(self) -> None:
        rows = self.ratios()
        self._ratio_table.setRowCount(len(rows))
        for k, row in enumerate(rows):
            ratio = row.ratio
            for col, text in enumerate(
                (
                    row.combination,
                    row.storey,
                    f"{row.first:.6g}",
                    f"{row.second:.6g}",
                    "-" if ratio is None else f"{ratio:.3f}",
                )
            ):
                self._ratio_table.setItem(k, col, QTableWidgetItem(text))
        self._ratio_table.resizeColumnsToContents()
        if not rows:
            self._ratio_status.setText(
                "No results yet: generate the cases, run them (Analyze → Run All Cases) "
                "and open this dialog again."
            )
            return
        worst = max(rows, key=lambda r: r.ratio or 0.0)
        text = f"Largest Δ2/Δ1 = {worst.ratio or 0.0:.3f} ({worst.combination}, {worst.storey}). "
        if notional_everywhere_required(rows):
            text += (
                f"Above {DRIFT_RATIO_LIMIT:g}: the notional loads must act in every "
                "combination; regenerate with the option on the Combinations tab."
            )
            self._everywhere.setChecked(True)
        elif (worst.ratio or 0.0) > 1.5:
            text += (
                "Above 1.5: the structure is sensitive to second-order effects; the direct "
                "analysis method is required (the effective length method is not)."
            )
        else:
            text += f"At or below {DRIFT_RATIO_LIMIT:g}: notional loads in the gravity combinations suffice."
        self._ratio_status.setText(text)
