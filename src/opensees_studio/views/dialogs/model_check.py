"""Review the model before it runs: what is loose, unconnected or unstable.

The dialog only *reports*. Every finding names the nodes and elements involved,
so "Select in canvas" shows where to look, and says what to do about it; fixing
is the modeller's job, because the right fix (a support, a brace, a node to
merge) is a decision, not a repair.

It has two uses. Opened from Analyze → Check Model it just lists the findings
and closes. Opened by Run, when the model has errors, it asks whether to run
anyway: a model the check calls broken is nearly always one OpenSees cannot
solve, but the check is a linear, small-displacement test and the person at the
keyboard may know better (a gap, a cable, a deliberate rigid-body modal run).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Project
from opensees_studio.core.model_check import Finding, ModelCheckReport, Severity, check_model
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

SelectEntities = Callable[[Sequence[int], Sequence[int]], None]

_SEVERITY_COLOUR = {
    Severity.ERROR: QColor("#c0392b"),
    Severity.WARNING: QColor("#b9770e"),
    Severity.INFO: QColor("#5d6d7e"),
}
_SEVERITY_LABEL = {
    Severity.ERROR: "Error",
    Severity.WARNING: "Warning",
    Severity.INFO: "Info",
}

COLUMNS = ("", "What was found", "Where", "What to do")


def _where(finding: Finding) -> str:
    parts = []
    if finding.node_ids:
        shown = ", ".join(str(i) for i in finding.node_ids[:6])
        extra = f" … +{len(finding.node_ids) - 6}" if len(finding.node_ids) > 6 else ""
        parts.append(f"nodes {shown}{extra}")
    if finding.element_ids:
        shown = ", ".join(str(i) for i in finding.element_ids[:6])
        extra = f" … +{len(finding.element_ids) - 6}" if len(finding.element_ids) > 6 else ""
        parts.append(f"elements {shown}{extra}")
    return "; ".join(parts) or "—"


class ModelCheckDialog(FittedDialog):
    """List what the model check found, with the way to see each finding in the canvas."""

    def __init__(
        self,
        project: Project,
        *,
        pre_run: bool = False,
        on_select: SelectEntities | None = None,
        report: ModelCheckReport | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._pre_run = pre_run
        self._on_select = on_select
        self._report = report if report is not None else check_model(project)
        self.setWindowTitle("Run Analysis — Model Problems" if pre_run else "Check Model")
        self._build_ui()

    # ── ui ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        intro = (
            "The model has problems that will most likely stop the analysis, or make its "
            "results meaningless. Fix them, or run anyway if you know better."
            if self._pre_run
            else "Loose nodes, unconnected elements and static instability, found without "
            "running the analysis. <i>Stability is a linear, small-displacement test: it "
            "does not see gaps, cables or sliders.</i>"
        )
        layout.addWidget(QLabel(intro, wordWrap=True))

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(list(COLUMNS))
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setWordWrap(True)
        self._table.setMinimumHeight(220)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self._table)

        self._summary = MessageArea()
        layout.addWidget(self._summary)

        buttons = QDialogButtonBox()
        self._select_button = QPushButton("Select in canvas")
        self._select_button.clicked.connect(self._select_current)
        buttons.addButton(self._select_button, QDialogButtonBox.ButtonRole.ActionRole)
        if self._pre_run:
            buttons.addButton("Run anyway", QDialogButtonBox.ButtonRole.AcceptRole)
            cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
            cancel.setDefault(True)  # the safe answer is the default one
        else:
            buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._fill()

    # ── data ────────────────────────────────────────────────────────
    def report(self) -> ModelCheckReport:
        return self._report

    def _fill(self) -> None:
        findings = self._report.findings
        self._table.setRowCount(len(findings))
        for row, finding in enumerate(findings):
            colour = _SEVERITY_COLOUR[finding.severity]
            cells = [
                _SEVERITY_LABEL[finding.severity],
                finding.message,
                _where(finding),
                finding.hint,
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setForeground(QBrush(colour))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self._table.setItem(row, column, item)
        self._table.resizeRowsToContents()

        if self._report.has_errors:
            level = "error"
        elif not self._report.is_clean:
            level = "warning"
        else:
            level = "info"
        self._summary.show_message(self._report.summary(), level)
        self._select_button.setEnabled(False)

    def _current_finding(self) -> Finding | None:
        row = self._table.currentRow()
        findings = self._report.findings
        return findings[row] if 0 <= row < len(findings) else None

    # ── selection in the canvas ─────────────────────────────────────
    def _selection_changed(self) -> None:
        finding = self._current_finding()
        has_target = finding is not None and bool(finding.node_ids or finding.element_ids)
        self._select_button.setEnabled(has_target and self._on_select is not None)

    def _select_current(self) -> None:
        finding = self._current_finding()
        if finding is None or self._on_select is None:
            return
        self._on_select(finding.node_ids, finding.element_ids)
