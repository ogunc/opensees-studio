"""Results panel — a dock that summarizes the latest analysis output.

Phase 6 keeps it minimal: tables for static (displacements, reactions)
and modal (frequencies). Time-history visualization (plots, animation)
is Phase 7.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.services.results import (
    ModalResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)


class ResultsPanel(QWidget):
    """Tabbed view that swaps based on the type of results received."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._title = QLabel("<i>(no results yet)</i>")
        layout.addWidget(self._title)
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

    # ── public API ───────────────────────────────────────────────────
    def show_results(self, results: Any) -> None:
        self._tabs.clear()
        if isinstance(results, StaticResults):
            self._title.setText(
                f"<b>Static — case #{results.case_id} '{results.case_name}'</b>  "
                f"({results.n_steps} step(s))"
            )
            self._tabs.addTab(self._build_static_disp_table(results), "Displacements")
            self._tabs.addTab(self._build_static_reaction_table(results), "Reactions")
        elif isinstance(results, ModalResults):
            solver = (
                f"  (eigen solver {results.solver}, {results.n_free_dof} free DOF)"
                if results.solver
                else ""
            )
            self._title.setText(
                f"<b>Modal — case #{results.case_id} '{results.case_name}'</b>{solver}"
            )
            self._tabs.addTab(self._build_modal_table(results), "Frequencies")
        elif isinstance(results, ResponseSpectrumResults):
            damping = (
                f", damping {results.damping_ratio:g}" if results.damping_ratio is not None else ""
            )
            solver = f", eigen solver {results.solver}" if results.solver else ""
            self._title.setText(
                f"<b>Response spectrum — case #{results.case_id} '{results.case_name}'</b>  "
                f"({results.combination}{damping}{solver})"
            )
            self._tabs.addTab(self._build_rs_combined_table(results), "Combined displacements")
            self._tabs.addTab(self._build_rs_mode_table(results), "Modes")
        elif isinstance(results, TransientResults):
            self._title.setText(
                f"<b>Transient — case #{results.case_id} '{results.case_name}'</b>  "
                f"({results.steps_summary()} × dt={results.dt:g})"
            )
            self._tabs.addTab(self._transient_summary(results), "Summary")
        else:
            self._title.setText("<i>(unsupported result type)</i>")

    # ── builders ─────────────────────────────────────────────────────
    def _build_static_disp_table(self, r: StaticResults) -> QWidget:
        rows = sorted(r.node_disp.keys())
        if not rows:
            return self._empty_table_widget()
        ndf = r.node_disp[rows[0]].shape[1]
        headers = ["Node"] + [f"DOF {i + 1}" for i in range(ndf)]
        table = self._make_table(headers, len(rows))
        for i, nid in enumerate(rows):
            self._set_cell(table, i, 0, str(nid))
            last_step = r.node_disp[nid][-1]
            for j, val in enumerate(last_step):
                self._set_cell(table, i, j + 1, f"{val:.6g}")
        return self._wrap(table, "Final-step displacements")

    def _build_static_reaction_table(self, r: StaticResults) -> QWidget:
        rows = sorted(r.node_reaction.keys())
        if not rows:
            return self._empty_table_widget()
        ndf = r.node_reaction[rows[0]].shape[1]
        headers = ["Node"] + [f"DOF {i + 1}" for i in range(ndf)]
        table = self._make_table(headers, len(rows))
        for i, nid in enumerate(rows):
            self._set_cell(table, i, 0, str(nid))
            last_step = r.node_reaction[nid][-1]
            for j, val in enumerate(last_step):
                self._set_cell(table, i, j + 1, f"{val:.6g}")
        return self._wrap(table, "Final-step reactions")

    def _build_modal_table(self, r: ModalResults) -> QWidget:
        n = len(r.eigenvalues)
        headers = ["Mode", "Eigenvalue (rad²/s²)", "ω (rad/s)", "f (Hz)", "T (s)"]
        table = self._make_table(headers, n)
        for i in range(n):
            self._set_cell(table, i, 0, str(i + 1))
            self._set_cell(table, i, 1, f"{r.eigenvalues[i]:.6g}")
            self._set_cell(table, i, 2, f"{r.angular_frequencies[i]:.6g}")
            self._set_cell(table, i, 3, f"{r.frequencies[i]:.6g}")
            self._set_cell(table, i, 4, f"{r.periods[i]:.6g}")
        return self._wrap(table, "Modal results")

    def _build_rs_combined_table(self, r: ResponseSpectrumResults) -> QWidget:
        rows = sorted(r.combined_disp.keys())
        if not rows:
            return self._empty_table_widget()
        table = self._make_table(["Node", "U1", "U2", "U3"], len(rows))
        for i, nid in enumerate(rows):
            self._set_cell(table, i, 0, str(nid))
            for j, val in enumerate(r.combined_disp[nid][:3]):
                self._set_cell(table, i, j + 1, f"{val:.6g}")
        return self._wrap(table, f"{r.combination} combined peak displacements", r.warnings)

    def _build_rs_mode_table(self, r: ResponseSpectrumResults) -> QWidget:
        headers = ["Mode", "T (s)", "f (Hz)", "Γ", "Mass ratio", "Sa(T)"]
        table = self._make_table(headers, len(r.modes))
        for i, m in enumerate(r.modes):
            self._set_cell(table, i, 0, str(m.mode_number))
            self._set_cell(table, i, 1, f"{m.period:.6g}")
            self._set_cell(table, i, 2, f"{m.frequency:.6g}")
            self._set_cell(table, i, 3, f"{m.participation_factor:+.6g}")
            self._set_cell(table, i, 4, f"{m.mass_ratio:.4f}")
            self._set_cell(table, i, 5, f"{m.sa_at_period:.6g}")
        return self._wrap(table, "Modal contributions", r.warnings)

    def _transient_summary(self, r: TransientResults) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(
            QLabel(
                f"<b>Steps:</b> {r.steps_summary()}<br>"
                f"<b>dt:</b> {r.dt:g}<br>"
                f"<b>Total time:</b> {r.n_steps * r.dt:g}<br>"
                f"<b>HDF5 file:</b> <code>{r.h5_path}</code>"
            )
        )
        layout.addWidget(
            QLabel("<i>Time-history plots and animation will appear here in Phase 7.</i>")
        )
        layout.addStretch(1)
        return w

    # ── helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _make_table(headers: list[str], n_rows: int) -> QTableWidget:
        table = QTableWidget(n_rows, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    @staticmethod
    def _set_cell(table: QTableWidget, r: int, c: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(r, c, item)

    @staticmethod
    def _wrap(table: QTableWidget, caption: str, warnings: list[str] | None = None) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(f"<b>{caption}</b>"))
        for text in warnings or []:
            label = QLabel(f"Warning: {text}")
            label.setObjectName("resultWarning")
            label.setWordWrap(True)
            label.setStyleSheet("color: #c0392b;")
            layout.addWidget(label)
        layout.addWidget(table)
        return w

    def _empty_table_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel("<i>(no data)</i>"))
        return w
