"""Results panel: a dock that tabulates the latest analysis output.

One tab per table of :mod:`opensees_studio.services.result_tables`: static
displacements, reactions and element forces; the pushover curve; modal
frequencies; response spectrum peaks and modes; the time history of a chosen
node. Cells keep the full double. The "Significant digits" setting (default
6, up to 15) changes the display only, and "Export CSV..." writes the current
tab at full precision with a header naming the units.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Project
from opensees_studio.services.result_tables import (
    HISTORY_KINDS,
    ResultTable,
    display_text,
    modal_tables,
    node_history_table,
    pushover_tables,
    response_spectrum_tables,
    static_tables,
    write_csv,
)
from opensees_studio.services.results import (
    ModalResults,
    PushoverResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)

DEFAULT_DIGITS = 6
MAX_DIGITS = 15

_Index = QModelIndex | QPersistentModelIndex


class ResultTableModel(QAbstractTableModel):
    """Read-only model over a :class:`ResultTable`; ``digits`` rounds the display only."""

    def __init__(self, table: ResultTable, digits: int = DEFAULT_DIGITS) -> None:
        super().__init__()
        self.table = table
        self._digits = digits

    def set_digits(self, digits: int) -> None:
        self._digits = digits
        if self.table.rows:
            last = self.index(len(self.table.rows) - 1, len(self.table.columns) - 1)
            self.dataChanged.emit(self.index(0, 0), last, [Qt.ItemDataRole.DisplayRole])

    def rowCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.table.rows)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.table.columns)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        value = self.table.rows[index.row()][index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return display_text(value, self._digits)
        if role == Qt.ItemDataRole.UserRole:
            return value
        if role == Qt.ItemDataRole.TextAlignmentRole and not isinstance(value, str):
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.table.columns[section]
        return None


class ResultsPanel(QWidget):
    """Tabbed view that swaps based on the type of results received."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._models: list[ResultTableModel] = []
        self._transient: TransientResults | None = None
        self._project: Project | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._title = QLabel("<i>(no results yet)</i>")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Significant digits:"))
        self._digits = QSpinBox()
        self._digits.setRange(1, MAX_DIGITS)
        self._digits.setValue(DEFAULT_DIGITS)
        self._digits.setToolTip("Display only; Export CSV writes every digit.")
        self._digits.valueChanged.connect(self._on_digits_changed)
        bar.addWidget(self._digits)
        bar.addStretch(1)
        self._export = QPushButton("Export CSV…")
        self._export.setToolTip("Write the current table at full precision, units in the header.")
        self._export.clicked.connect(self._on_export_clicked)
        self._export.setEnabled(False)
        bar.addWidget(self._export)
        layout.addLayout(bar)

        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(lambda _i: self._export.setEnabled(bool(self.tables())))
        layout.addWidget(self._tabs)

    # ── public API ───────────────────────────────────────────────────
    def clear_results(self) -> None:
        while self._tabs.count():
            page = self._tabs.widget(0)
            self._tabs.removeTab(0)
            page.deleteLater()
        self._models = []
        self._transient = None
        self._project = None
        self._title.setText("<i>(no results yet)</i>")
        self._export.setEnabled(False)

    def show_results(self, results: Any, project: Project | None = None) -> None:
        self.clear_results()
        self._tabs.clear()
        self._models = []
        self._transient = None
        self._project = project
        if isinstance(results, StaticResults):
            self._title.setText(
                f"<b>Static — case #{results.case_id} '{results.case_name}'</b>  "
                f"({results.n_steps} step(s))"
            )
            for table, name in zip(
                static_tables(results, project),
                ("Displacements", "Reactions", "Element forces"),
                strict=True,
            ):
                self._add_table_tab(table, name)
        elif isinstance(results, PushoverResults):
            self._title.setText(
                f"<b>Pushover: case #{results.case_id} '{results.case_name}'</b>  "
                f"({results.n_steps} step(s))"
            )
            for table, name in zip(
                pushover_tables(results, project),
                ("Curve", "Displacements", "Element forces"),
                strict=True,
            ):
                self._add_table_tab(table, name)
        elif isinstance(results, ModalResults):
            solver = (
                f"  (eigen solver {results.solver}, {results.n_free_dof} free DOF)"
                if results.solver
                else ""
            )
            self._title.setText(
                f"<b>Modal — case #{results.case_id} '{results.case_name}'</b>{solver}"
            )
            self._add_table_tab(modal_tables(results)[0], "Frequencies")
        elif isinstance(results, ResponseSpectrumResults):
            damping = (
                f", damping {results.damping_ratio:g}" if results.damping_ratio is not None else ""
            )
            solver = f", eigen solver {results.solver}" if results.solver else ""
            self._title.setText(
                f"<b>Response spectrum — case #{results.case_id} '{results.case_name}'</b>  "
                f"({results.combination}{damping}{solver})"
            )
            combined, modes = response_spectrum_tables(results, project)
            self._add_table_tab(combined, "Combined displacements")
            self._add_table_tab(modes, "Modes")
        elif isinstance(results, TransientResults):
            self._title.setText(
                f"<b>Transient — case #{results.case_id} '{results.case_name}'</b>  "
                f"({results.steps_summary()} × dt={results.dt:g})"
            )
            self._transient = results
            self._tabs.addTab(self._transient_summary(results), "Summary")
            self._tabs.addTab(self._history_tab(project), "Node history")
        else:
            self._title.setText("<i>(unsupported result type)</i>")
        self._export.setEnabled(bool(self.tables()))

    def tables(self) -> list[ResultTable]:
        """The tables of the current tab (empty for a tab without one)."""
        model = self.current_model()
        return [model.table] if model is not None else []

    def current_model(self) -> ResultTableModel | None:
        view = self._tabs.currentWidget()
        view = view.findChild(QTableView) if view is not None else None
        model = view.model() if view is not None else None
        return model if isinstance(model, ResultTableModel) else None

    def digits(self) -> int:
        return self._digits.value()

    def set_digits(self, digits: int) -> None:
        self._digits.setValue(digits)

    def export_current(self, path: Path | str) -> Path | None:
        """Write the current tab's table to ``path``; ``None`` when the tab has no table."""
        tables = self.tables()
        return write_csv(tables[0], path) if tables else None

    # ── slots ────────────────────────────────────────────────────────
    def _on_digits_changed(self, digits: int) -> None:
        for model in self._models:
            model.set_digits(digits)

    def _on_export_clicked(self) -> None:
        tables = self.tables()
        if not tables:
            return
        suggested = tables[0].title.lower().replace(" ", "_").replace("(", "").replace(")", "")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export table as CSV", f"{suggested}.csv", "CSV files (*.csv)"
        )
        if path:
            self.export_current(path)

    # ── builders ─────────────────────────────────────────────────────
    def _table_view(self, table: ResultTable) -> QTableView:
        model = ResultTableModel(table, self._digits.value())
        self._models.append(model)
        view = QTableView()
        view.setModel(model)
        view.verticalHeader().setVisible(False)
        view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return view

    def _add_table_tab(self, table: ResultTable, name: str) -> None:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(f"<b>{table.title}</b>"))
        for text in table.notes:
            label = QLabel(f"Warning: {text}")
            label.setObjectName("resultWarning")
            label.setWordWrap(True)
            label.setStyleSheet("color: #c0392b;")
            layout.addWidget(label)
        if table.rows:
            layout.addWidget(self._table_view(table))
        else:
            layout.addWidget(QLabel("<i>(no data)</i>"))
        self._tabs.addTab(w, name)

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
        layout.addWidget(QLabel("<i>Node histories: see the Node history tab.</i>"))
        layout.addStretch(1)
        return w

    def _history_tab(self, project: Project | None) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        pick = QHBoxLayout()
        pick.addWidget(QLabel("Node:"))
        self._history_node = QComboBox()
        for nid in sorted(n.id for n in project.nodes) if project is not None else []:
            self._history_node.addItem(str(nid), nid)
        pick.addWidget(self._history_node)
        pick.addWidget(QLabel("Quantity:"))
        self._history_kind = QComboBox()
        for kind, label in zip(
            HISTORY_KINDS, ("Displacement", "Velocity", "Acceleration"), strict=True
        ):
            self._history_kind.addItem(label, kind)
        pick.addWidget(self._history_kind)
        pick.addStretch(1)
        layout.addLayout(pick)
        self._history_caption = QLabel("")
        layout.addWidget(self._history_caption)
        self._history_view = QTableView()
        self._history_view.verticalHeader().setVisible(False)
        self._history_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._history_view)
        self._history_node.currentIndexChanged.connect(self._refresh_history)
        self._history_kind.currentIndexChanged.connect(self._refresh_history)
        self._refresh_history()
        return w

    def _refresh_history(self) -> None:
        results, node_id = self._transient, self._history_node.currentData()
        if results is None or node_id is None:
            self._history_caption.setText("<i>(no node to show)</i>")
            return
        try:
            table = node_history_table(
                results, int(node_id), self._history_kind.currentData(), self._project
            )
        except (KeyError, OSError) as exc:
            self._history_caption.setText(f"<i>{exc}</i>")
            self._history_view.setModel(None)
            self._export.setEnabled(False)
            return
        old = self._history_view.model()
        if isinstance(old, ResultTableModel) and old in self._models:
            self._models.remove(old)
        model = ResultTableModel(table, self._digits.value())
        self._models.append(model)
        self._history_view.setModel(model)
        self._history_caption.setText(f"<b>{table.title}</b>")
        self._export.setEnabled(bool(self.tables()))
