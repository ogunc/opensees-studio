"""Design → Steel Frame Check (AISC 360-16) and Design → Storey Drift Check.

Both dialogs read the results of the cases run in this session (the window's
case results cache) and never run an analysis themselves: a load set whose
cases have no current result is listed and skipped, with the case to run.

The settings (method, Fy, load sets, member overrides, drift limit) are kept
in ``Project.design``; the dialog hands them back and the window stores them
with one undoable command, so OK is the only thing that changes the project.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.analysis import ResponseSpectrumCase, StaticCase
from opensees_studio.core.design.settings import (
    DRIFT_PRESETS,
    DesignLoadSet,
    DesignSettings,
    SteelMemberDesign,
)
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import labels_for
from opensees_studio.services.steel_design import (
    DesignReport,
    default_fy,
    default_load_sets,
    load_set_label,
    steel_frame_check,
    storey_drift_check,
)
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

_RESULT_COLUMNS = [
    "Element",
    "Shape",
    "Ratio",
    "Status",
    "Governs",
    "Equation",
    "Load set",
    "Notes",
]
_FAIL = QColor("#f8d7da")
_SKIP = QColor("#eeeeee")


class SteelDesignDialog(FittedDialog):
    """Settings, member overrides and the result table of the AISC 360-16 check."""

    def __init__(
        self,
        project: Any,
        results: dict[int, Any],
        *,
        selected_elements: frozenset[int] = frozenset(),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._results = results
        self._selected = sorted(selected_elements)
        settings = project.design or DesignSettings()
        self._members = {m.element_id: m for m in settings.members}
        self._settings = settings
        self._report: DesignReport | None = None
        self.setWindowTitle("Steel Frame Check — AISC 360-16")
        self.setProperty(TOPIC_PROPERTY, "design.steel_check")
        self._build_ui()
        self._load_settings(settings)

    # ── ui ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Frame members whose section is an AISC <b>W, M, S, HP, channel, tee, "
                "equal-leg angle, HSS or pipe</b> shape (by name, "
                "or named below) are checked for tension, compression, flexure, shear and "
                "the H1 interaction, over the results of the load sets ticked here."
            )
        )
        top = QHBoxLayout()
        form = QFormLayout()
        self._method = QComboBox()
        self._method.addItems(["LRFD", "ASD"])
        form.addRow("Method:", self._method)
        stress = labels_for(self._project.meta.units).stress
        self._fy = FloatField()
        self._fy.setRange(1e-9, 1e15)
        form.addRow(f"Fy [{stress}]:", self._fy)
        self._limit = FloatField()
        self._limit.setRange(0.01, 100.0)
        form.addRow("Ratio limit:", self._limit)
        top.addLayout(form)

        self._load_sets = QListWidget()
        self._load_sets.setMinimumHeight(110)
        top.addWidget(self._load_sets, 1)
        layout.addLayout(top)

        self._overrides = QGroupBox(f"Overrides for the {len(self._selected)} selected member(s)")
        over = QFormLayout(self._overrides)
        self._shape = QLineEdit()
        self._shape.setPlaceholderText("from the section's name")
        over.addRow("AISC shape:", self._shape)
        self._k_major = FloatField()
        self._k_major.setRange(0.1, 10.0)
        self._k_major.setValue(1.0)
        over.addRow("K, major axis:", self._k_major)
        self._k_minor = FloatField()
        self._k_minor.setRange(0.1, 10.0)
        self._k_minor.setValue(1.0)
        over.addRow("K, minor axis:", self._k_minor)
        length = labels_for(self._project.meta.units).length
        self._lb = FloatField()
        self._lb.setRange(0.0, 1e9)
        self._lb.setToolTip("Unbraced length of the compression flange; 0 = the member length.")
        over.addRow(f"Lb (LTB) [{length}], 0 = member:", self._lb)
        self._cb = FloatField()
        self._cb.setRange(0.0, 3.0)
        self._cb.setToolTip("0 = from the moment diagram (F1-1). Use 1.0 for a cantilever.")
        over.addRow("Cb, 0 = from the diagram:", self._cb)
        apply = QPushButton("Apply to the selected members")
        apply.clicked.connect(self._apply_overrides)
        over.addRow(apply)
        self._overrides.setEnabled(bool(self._selected))
        layout.addWidget(self._overrides)

        run_row = QHBoxLayout()
        self._run = QPushButton("Check")
        self._run.clicked.connect(self.run_check)
        run_row.addWidget(self._run)
        self._select_failing = QPushButton("Select failing members")
        self._select_failing.setEnabled(False)
        self._select_failing.clicked.connect(self.accept_and_select)
        run_row.addWidget(self._select_failing)
        self._show_ratios = QPushButton("Show ratios on the model")
        self._show_ratios.setToolTip("Close with OK and paint every member by its governing ratio.")
        self._show_ratios.setEnabled(False)
        self._show_ratios.clicked.connect(self.accept_and_show)
        run_row.addWidget(self._show_ratios)
        run_row.addStretch(1)
        layout.addLayout(run_row)

        self._table = QTableWidget(0, len(_RESULT_COLUMNS))
        self._table.setHorizontalHeaderLabels(_RESULT_COLUMNS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setMinimumHeight(200)
        layout.addWidget(self._table, 1)

        self._summary = MessageArea()
        layout.addWidget(self._summary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.select_failing_requested = False
        self.show_ratios_requested = False

    def _load_settings(self, settings: DesignSettings) -> None:
        self._method.setCurrentText(settings.method)
        units = self._project.meta.units
        self._fy.setValue(settings.fy if settings.fy is not None else default_fy(units))
        self._limit.setValue(settings.ratio_limit)
        chosen = {
            (s.source, s.ref_id) for s in (settings.load_sets or default_load_sets(self._project))
        }
        candidates = [
            DesignLoadSet(source="combination", ref_id=c.id) for c in self._project.combinations
        ] + [
            DesignLoadSet(source="case", ref_id=c.id)
            for c in self._project.analyses
            if isinstance(c, StaticCase | ResponseSpectrumCase)
        ]
        for load_set in candidates:
            label = load_set_label(self._project, load_set)
            if load_set.source == "case" and load_set.ref_id not in self._results:
                label += "  (no result: run it first)"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            on = (load_set.source, load_set.ref_id) in chosen
            item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, (load_set.source, load_set.ref_id))
            self._load_sets.addItem(item)
        if len(self._selected) == 1 and self._selected[0] in self._members:
            member = self._members[self._selected[0]]
            self._shape.setText(member.shape or "")
            self._k_major.setValue(member.k_major)
            self._k_minor.setValue(member.k_minor)
            self._lb.setValue(member.length_ltb or 0.0)
            self._cb.setValue(member.cb or 0.0)

    def _apply_overrides(self) -> None:
        shape = self._shape.text().strip() or None
        for element_id in self._selected:
            self._members[element_id] = SteelMemberDesign(
                element_id=element_id,
                shape=shape,
                k_major=self._k_major.value(),
                k_minor=self._k_minor.value(),
                length_ltb=self._lb.value() or None,
                cb=self._cb.value() or None,
            )
        self._summary.show_message(f"Overrides set on {len(self._selected)} member(s).")

    # ── what the caller needs ───────────────────────────────────────
    def settings(self) -> DesignSettings:
        """The settings as the dialog shows them (stored by the caller on OK)."""
        chosen: list[DesignLoadSet] = []
        for row in range(self._load_sets.count()):
            item = self._load_sets.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                source, ref_id = item.data(Qt.ItemDataRole.UserRole)
                chosen.append(DesignLoadSet(source=source, ref_id=ref_id))
        default = [(s.source, s.ref_id) for s in default_load_sets(self._project)]
        same_as_default = [(s.source, s.ref_id) for s in chosen] == default
        fy = self._fy.value()
        units = self._project.meta.units
        base = self._project.design or DesignSettings()
        members = [
            m
            for _, m in sorted(self._members.items())
            if m != SteelMemberDesign(element_id=m.element_id)
        ]
        return base.model_copy(
            update={
                "method": self._method.currentText(),
                "fy": None if abs(fy - default_fy(units)) <= 1e-9 * fy else fy,
                "ratio_limit": self._limit.value(),
                "load_sets": [] if same_as_default else chosen,
                "members": members,
            }
        )

    def report(self) -> DesignReport | None:
        return self._report

    def failing_elements(self) -> set[int]:
        return {m.element_id for m in self._report.failing} if self._report else set()

    def accept_and_select(self) -> None:
        self.select_failing_requested = True
        self.accept()

    def accept_and_show(self) -> None:
        self.show_ratios_requested = True
        self.accept()

    # ── running ─────────────────────────────────────────────────────
    def run_check(self) -> DesignReport:
        report = steel_frame_check(self._project, self._results, self.settings())
        self._report = report
        self._table.setRowCount(len(report.members))
        for row, member in enumerate(sorted(report.members, key=lambda m: -m.ratio)):
            cells = [
                str(member.element_id),
                member.shape or "—",
                f"{member.ratio:.3f}" if member.status != "not designed" else "",
                member.status,
                member.check,
                member.equation,
                member.load_set,
                " ".join(member.notes),
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if member.status == "NG":
                    item.setBackground(QBrush(_FAIL))
                elif member.status == "not designed":
                    item.setBackground(QBrush(_SKIP))
                self._table.setItem(row, column, item)
        self._table.resizeColumnsToContents()
        text = report.summary()
        if report.notes:
            text += " " + " ".join(report.notes)
        self._summary.show_message(
            text, level="warning" if report.failing or report.notes else "info"
        )
        self._select_failing.setEnabled(bool(report.failing))
        self._show_ratios.setEnabled(bool(report.members))
        return report


class DriftCheckDialog(FittedDialog):
    """Amplified storey drift ratios of the current results against a limit."""

    def __init__(
        self, project: Any, results: dict[int, Any], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._results = results
        self.setWindowTitle("Storey Drift Check")
        self.setProperty(TOPIC_PROPERTY, "design.drift_check")
        settings = project.design or DesignSettings()
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Inter-storey drift ratio of each storey, times the amplification, against the "
                "allowable ratio, for every static and response spectrum case with a result."
            )
        )
        form = QFormLayout()
        self._preset = QComboBox()
        self._preset.addItem("Custom", None)
        for label, values in DRIFT_PRESETS.items():
            self._preset.addItem(label, values)
        self._preset.currentIndexChanged.connect(self._on_preset)
        form.addRow("Code:", self._preset)
        self._limit = FloatField()
        self._limit.setRange(1e-6, 1.0)
        self._limit.setValue(settings.drift_limit)
        form.addRow("Allowable drift ratio:", self._limit)
        self._amplification = FloatField()
        self._amplification.setRange(1e-3, 100.0)
        self._amplification.setValue(settings.drift_amplification)
        self._amplification.setToolTip("Cd / Ie for ASCE 7; 1 when the drifts are design values.")
        form.addRow("Amplification:", self._amplification)
        layout.addLayout(form)
        run = QPushButton("Check")
        run.clicked.connect(self.run_check)
        layout.addWidget(run)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Case", "Storey", "Drift X", "Drift Y", "Ratio"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table, 1)
        self._summary = MessageArea()
        layout.addWidget(self._summary)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_preset(self) -> None:
        values = self._preset.currentData()
        if values:
            self._limit.setValue(values[0])
            self._amplification.setValue(values[1])

    def settings(self) -> DesignSettings:
        base = self._project.design or DesignSettings()
        return base.model_copy(
            update={
                "drift_limit": self._limit.value(),
                "drift_amplification": self._amplification.value(),
            }
        )

    def run_check(self) -> list[Any]:
        settings = self.settings()
        reports = []
        for case_id in sorted(self._results):
            found = storey_drift_check(self._project, self._results[case_id], settings)
            if found is not None:
                reports.append(found)
        rows = [(report, row) for report in reports for row in report.rows]
        self._table.setRowCount(len(rows))
        for k, (report, row) in enumerate(rows):
            drift = [*row.drift, 0.0][:2]
            cells = [
                report.load_set,
                row.storey,
                f"{drift[0]:.5f}",
                f"{drift[1]:.5f}" if len(row.drift) > 1 else "—",
                f"{row.ratio:.3f}",
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if row.ratio > 1.0:
                    item.setBackground(QBrush(_FAIL))
                self._table.setItem(k, column, item)
        self._table.resizeColumnsToContents()
        if not self._project.storeys:
            self._summary.show_message(
                "The project has no storeys: define them (Define → Storeys) to check drifts.",
                level="warning",
            )
        elif not reports:
            self._summary.show_message(
                "No static or response spectrum result to check: run a case first.",
                level="warning",
            )
        else:
            worst = max(report.worst for report in reports)
            failing = sum(1 for _, row in rows if row.ratio > 1.0)
            self._summary.show_message(
                f"Largest ratio {worst:.3f}; {failing} storey row(s) over the limit.",
                level="warning" if failing else "info",
            )
        return reports
