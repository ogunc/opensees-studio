"""Design → Footings: isolated and combined footings under the supports, ACI 318-19 and the soil.

**Isolated** tab: one row per vertically restrained node (:mod:`services.footings`),
with a box that says whether the support gets its own footing. The selected rows'
footing is edited in the form; **Size** finds the smallest plan, thickness and
bars that pass. **Combine the selected supports** puts two or more of them on
one combined footing.

**Combined** tab: one row per combined footing, its plan, slab and bars in the
form and its columns (footprint and pedestal) in the table below it.

The checks of the selected footing are listed on the right with their values,
clause and load set. The two lists at the bottom pick the service (soil) and
strength (concrete) load sets, and **Pressure Plan…** draws the soil pressure
under every footing. Nothing is stored until OK, which keeps the footings in
``Project.design`` with one undoable command.
"""

from __future__ import annotations

import html
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.design.combined_footing import CombinedColumn, CombinedFootingDesign
from opensees_studio.core.design.footing import FootingDesign
from opensees_studio.core.design.settings import DesignLoadSet, DesignSettings
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import labels_for
from opensees_studio.services.footings import (
    STATUS_REQUIRES_VERIFICATION,
    FootingReport,
    FootingSupport,
    check_combined_footings,
    check_footings,
    default_combined,
    default_footing,
    footing_load_sets,
    footing_supports,
    size_combined_design,
    size_design,
)
from opensees_studio.services.steel_design import load_set_label
from opensees_studio.views.dialogs.design_basis import _ok_cancel
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog
from opensees_studio.views.theme import tone

_COLUMNS = [
    "Footing",
    "Node",
    "Column",
    "L × B × h",
    "Bars X / Y",
    "Ratio",
    "Governing",
    "Load set",
]
_COMBINED_COLUMNS = ["Name", "Nodes", "L × B × h", "Ratio", "Governing", "Load set"]
_COLUMN_COLUMNS = ["Node", "X size", "Y size", "Pedestal height"]

_LENGTHS = (
    ("length_x", "Length L (along X)"),
    ("width_y", "Width B (along Y)"),
    ("thickness", "Thickness h"),
    ("offset_x", "Support offset from the centre, X"),
    ("offset_y", "Support offset from the centre, Y"),
    ("column_x", "Pedestal / column / plate, X"),
    ("column_y", "Pedestal / column / plate, Y"),
    ("pedestal_height", "Pedestal height (0 = none)"),
    ("soil_cover", "Fill above the footing"),
    ("cover", "Clear cover"),
    ("bar_x_diameter", "X bars: diameter"),
    ("bar_x_spacing", "X bars: spacing"),
    ("bar_y_diameter", "Y bars: diameter"),
    ("bar_y_spacing", "Y bars: spacing"),
)
_COMBINED_LENGTHS = (
    ("center_x", "Centre X"),
    ("center_y", "Centre Y"),
    ("length_x", "Length L (along X)"),
    ("width_y", "Width B (along Y)"),
    ("thickness", "Thickness h"),
    ("soil_cover", "Fill above the footing"),
    ("cover", "Clear cover"),
    ("bar_x_diameter", "X bars: diameter"),
    ("bar_x_spacing", "X bars: spacing"),
    ("bar_y_diameter", "Y bars: diameter"),
    ("bar_y_spacing", "Y bars: spacing"),
    ("top_bar_diameter", "Top bars (long axis): diameter, 0 = none"),
    ("top_bar_spacing", "Top bars: spacing"),
)
_STRESSES = (
    ("fc", "Concrete f'c"),
    ("fy", "Reinforcement fy"),
    ("bearing_allowable", "Allowable soil pressure qa (gross)"),
)
_WEIGHTS = (("concrete_weight", "Concrete unit weight"), ("soil_weight", "Fill unit weight"))
_FACTORS = (
    ("friction", "Friction coefficient μ"),
    ("fs_overturning", "FS against overturning"),
    ("fs_sliding", "FS against sliding"),
)
_SIGNED = {"offset_x", "offset_y", "center_x", "center_y"}
_ZERO_OK = {"pedestal_height", "soil_cover", "top_bar_diameter"}


def _float_field(key: str) -> FloatField:
    widget = FloatField()
    low = -1e18 if key in _SIGNED else (0.0 if key in _ZERO_OK else 1e-12)
    widget.setRange(low, 1e18)
    return widget


def _form(
    lengths: tuple[tuple[str, str], ...], lab: Any, fields: dict[str, FloatField]
) -> QFormLayout:
    form = QFormLayout()
    for key, label in lengths:
        fields[key] = _float_field(key)
        form.addRow(f"{label} [{lab.length}]:", fields[key])
    for key, label in _STRESSES:
        fields[key] = _float_field(key)
        form.addRow(f"{label} [{lab.stress}]:", fields[key])
    for key, label in _WEIGHTS:
        fields[key] = _float_field(key)
        form.addRow(f"{label} [{lab.force}/{lab.length}³]:", fields[key])
    for key, label in _FACTORS:
        fields[key] = _float_field(key)
        form.addRow(f"{label}:", fields[key])
    return form


def _scrolled(layout: QFormLayout, title: str) -> QScrollArea:
    box = QGroupBox(title)
    box.setLayout(layout)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(box)
    return area


class FootingsDialog(FittedDialog):
    """The supports, their isolated and combined footings, and the governing ratio of each."""

    def __init__(
        self, project: Any, results: dict[int, Any], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._results = results
        self._base_settings = project.design or DesignSettings()
        self.setWindowTitle("Footings (ACI 318-19, soil)")
        self.setProperty(TOPIC_PROPERTY, "design.footings")
        units = project.meta.units
        self._supports: list[FootingSupport] = footing_supports(project, self._base_settings)
        saved = {d.node_id: d for d in self._base_settings.footings}
        self._designs: dict[int, FootingDesign] = {
            s.node_id: saved.get(s.node_id) or default_footing(s, units, self._base_settings)
            for s in self._supports
        }
        self._combined: list[CombinedFootingDesign] = list(self._base_settings.combined_footings)
        first_time = not saved and not self._combined
        self._enabled: set[int] = (
            {s.node_id for s in self._supports} if first_time else set(saved)
        ) - self._combined_nodes()
        self._reports: dict[int, FootingReport] = {}
        self._combined_reports: list[FootingReport] = []

        layout = QVBoxLayout(self)
        intro = QLabel(
            "An isolated footing under each support restrained in Uz, or a combined footing "
            "under two or more. The soil is checked with the service (ASD) load sets, the "
            "concrete with the strength (LRFD) ones, after ACI 318-19. A steel column's base "
            "plate stays in Design → Base Plates; with a footing its A2 comes from here."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        lab = labels_for(units)

        # ── isolated tab ──
        isolated = QWidget()
        iso_layout = QVBoxLayout(isolated)
        self._table = QTableWidget(len(self._supports), len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._show_selected)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.setMinimumHeight(140)
        iso_layout.addWidget(self._table, 1)
        self._fields: dict[str, FloatField] = {}
        iso_layout.addWidget(
            _scrolled(_form(_LENGTHS, lab, self._fields), "Footing of the selected supports"), 2
        )
        iso_buttons = QHBoxLayout()
        self._apply = QPushButton("Apply to the selected supports")
        self._apply.clicked.connect(self.apply_to_selected)
        self._size = QPushButton("Size the selected footings")
        self._size.clicked.connect(self.size_selected)
        self._combine = QPushButton("Combine the selected supports")
        self._combine.clicked.connect(self.combine_selected)
        for button in (self._apply, self._size, self._combine):
            iso_buttons.addWidget(button)
        iso_buttons.addStretch(1)
        iso_layout.addLayout(iso_buttons)

        # ── combined tab ──
        combined = QWidget()
        comb_layout = QVBoxLayout(combined)
        self._combined_table = QTableWidget(0, len(_COMBINED_COLUMNS))
        self._combined_table.setHorizontalHeaderLabels(_COMBINED_COLUMNS)
        self._combined_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._combined_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._combined_table.itemSelectionChanged.connect(self._show_combined)
        self._combined_table.setMinimumHeight(110)
        comb_layout.addWidget(self._combined_table, 1)
        self._combined_fields: dict[str, FloatField] = {}
        comb_layout.addWidget(
            _scrolled(
                _form(_COMBINED_LENGTHS, lab, self._combined_fields),
                "The selected combined footing",
            ),
            2,
        )
        self._columns_table = QTableWidget(0, len(_COLUMN_COLUMNS))
        self._columns_table.setHorizontalHeaderLabels(
            [_COLUMN_COLUMNS[0]] + [f"{c} [{lab.length}]" for c in _COLUMN_COLUMNS[1:]]
        )
        self._columns_table.setMinimumHeight(90)
        comb_layout.addWidget(self._columns_table, 1)
        comb_buttons = QHBoxLayout()
        self._apply_combined = QPushButton("Apply to the combined footing")
        self._apply_combined.clicked.connect(self.apply_combined)
        self._size_combined = QPushButton("Size the combined footing")
        self._size_combined.clicked.connect(self.size_combined)
        self._remove_combined = QPushButton("Remove the combined footing")
        self._remove_combined.clicked.connect(self.remove_combined)
        for button in (self._apply_combined, self._size_combined, self._remove_combined):
            comb_buttons.addWidget(button)
        comb_buttons.addStretch(1)
        comb_layout.addLayout(comb_buttons)

        middle = QHBoxLayout()
        self._tabs = QTabWidget()
        self._tabs.addTab(isolated, "Isolated")
        self._tabs.addTab(combined, "Combined")
        self._tabs.currentChanged.connect(lambda _i: self._show_details())
        middle.addWidget(self._tabs, 3)
        self._details = QTextBrowser()
        middle.addWidget(self._details, 2)
        layout.addLayout(middle, 1)

        sets = QHBoxLayout()
        service, strength, _notes = footing_load_sets(project, self._base_settings)
        self._service = self._set_list(service)
        self._strength = self._set_list(strength)
        for title, widget in (
            ("Service load sets (soil)", self._service),
            ("Strength load sets (concrete)", self._strength),
        ):
            group = QGroupBox(title)
            QVBoxLayout(group).addWidget(widget)
            widget.setMaximumHeight(110)
            sets.addWidget(group)
        layout.addLayout(sets)
        self._service.itemChanged.connect(lambda _i: self.run_check())
        self._strength.itemChanged.connect(lambda _i: self.run_check())

        bottom = QHBoxLayout()
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        bottom.addWidget(self._summary, 1)
        self._plan = QPushButton("Pressure Plan…")
        self._plan.clicked.connect(self.show_pressure_plan)
        bottom.addWidget(self._plan)
        layout.addLayout(bottom)
        layout.addWidget(_ok_cancel(self))
        self.run_check()
        if self._supports:
            self._table.selectRow(0)
        if self._combined:
            self._combined_table.selectRow(0)

    # ── load sets ────────────────────────────────────────────────────
    def _set_list(self, chosen: list[DesignLoadSet]) -> QListWidget:
        widget = QListWidget()
        keys = {(s.source, s.ref_id) for s in chosen}
        options = [
            DesignLoadSet(source="combination", ref_id=c.id) for c in self._project.combinations
        ]
        options += [
            DesignLoadSet(source="case", ref_id=c.id)
            for c in self._project.analyses
            if type(c).__name__ in ("StaticCase", "ResponseSpectrumCase")
        ]
        for option in options:
            item = QListWidgetItem(load_set_label(self._project, option))
            item.setData(Qt.ItemDataRole.UserRole, option)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = (option.source, option.ref_id) in keys
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            widget.addItem(item)
        return widget

    @staticmethod
    def _checked(widget: QListWidget) -> list[DesignLoadSet]:
        return [
            widget.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(widget.count())
            if widget.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _combined_nodes(self) -> set[int]:
        return {n for c in self._combined for n in c.node_ids}

    def _settings_for_check(self) -> DesignSettings:
        return self._base_settings.model_copy(
            update={
                "footing_service_sets": self._checked(self._service),
                "footing_strength_sets": self._checked(self._strength),
                "combined_footings": list(self._combined),
            }
        )

    # ── checks ───────────────────────────────────────────────────────
    @staticmethod
    def _paint(item: QTableWidgetItem, report: FootingReport | None) -> None:
        if report is None:
            return
        if report.status == "NG":
            item.setForeground(QBrush(QColor(tone("error"))))
        elif report.status == STATUS_REQUIRES_VERIFICATION:
            item.setForeground(QBrush(QColor(tone("warning"))))
        if report.notes:
            item.setToolTip("\n".join(report.notes))

    def run_check(self) -> list[FootingReport]:
        settings = self._settings_for_check()
        enabled = self._enabled - self._combined_nodes()
        reports = check_footings(
            self._project, self._results, settings,
            designs={n: self._designs[n] for n in enabled}, nodes=enabled,
        )  # fmt: skip
        self._reports = {r.node_id: r for r in reports}
        self._combined_reports = check_combined_footings(self._project, self._results, settings)
        owner = {n: c.name for c in self._combined for n in c.node_ids}
        self._table.blockSignals(True)
        for row, support in enumerate(self._supports):
            design = self._designs[support.node_id]
            report = self._reports.get(support.node_id)
            combined = owner.get(support.node_id)
            if report is not None:
                governing = report.governing or report.status
            else:
                governing = f"on {combined}" if combined else "no footing"
            values = [
                "",
                str(support.node_id),
                support.column or "-",
                f"{design.length_x:.4g} × {design.width_y:.4g} × {design.thickness:.4g}",
                f"{design.bar_x_diameter:.3g}@{design.bar_x_spacing:.3g} / "
                f"{design.bar_y_diameter:.3g}@{design.bar_y_spacing:.3g}",
                f"{report.ratio:.3f}" if report and report.governing else "-",
                governing,
                report.load_set if report else "",
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 0:
                    if combined:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    else:
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        item.setCheckState(
                            Qt.CheckState.Checked
                            if support.node_id in self._enabled
                            else Qt.CheckState.Unchecked
                        )
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._paint(item, report)
                self._table.setItem(row, col, item)
        self._table.blockSignals(False)
        self._table.resizeColumnsToContents()

        selected = self._combined_index()
        self._combined_table.blockSignals(True)
        self._combined_table.setRowCount(len(self._combined))
        for row, (combo, report) in enumerate(
            zip(self._combined, self._combined_reports, strict=True)
        ):
            values = [
                combo.name,
                ", ".join(map(str, combo.node_ids)),
                f"{combo.length_x:.4g} × {combo.width_y:.4g} × {combo.thickness:.4g}",
                f"{report.ratio:.3f}" if report.governing else "-",
                report.governing or report.status,
                report.load_set,
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._paint(item, report)
                self._combined_table.setItem(row, col, item)
        if selected is not None and selected < len(self._combined):
            self._combined_table.selectRow(selected)
        self._combined_table.blockSignals(False)
        self._combined_table.resizeColumnsToContents()

        every = reports + self._combined_reports
        failing = sum(1 for r in every if r.status == "NG")
        pending = sum(1 for r in every if r.status == STATUS_REQUIRES_VERIFICATION)
        if not self._supports:
            text = "No support restrained in Uz."
        else:
            text = (
                f"{len(reports)} isolated and {len(self._combined_reports)} combined "
                f"footing(s), {failing} over the limit"
            )
            text += f", {pending} requiring verification." if pending else "."
        self._summary.setText(text)
        self._show_details()
        return every

    # ── isolated ─────────────────────────────────────────────────────
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        node = self._supports[item.row()].node_id
        if item.checkState() == Qt.CheckState.Checked:
            self._enabled.add(node)
        else:
            self._enabled.discard(node)
        self.run_check()

    def _selected_nodes(self) -> list[int]:
        rows = sorted({index.row() for index in self._table.selectedIndexes()})
        return [self._supports[r].node_id for r in rows]

    def _show_selected(self) -> None:
        nodes = self._selected_nodes()
        if not nodes:
            return
        design = self._designs[nodes[0]]
        for key, widget in self._fields.items():
            widget.setValue(float(getattr(design, key)))
        self._show_details()

    def apply_to_selected(self) -> None:
        values = {key: w.value() for key, w in self._fields.items()}
        busy = self._combined_nodes()
        for node in self._selected_nodes():
            if node in busy:
                continue
            current = self._designs[node]
            self._designs[node] = FootingDesign.model_validate({**current.model_dump(), **values})
            self._enabled.add(node)
        self.run_check()

    def size_selected(self) -> None:
        settings = self._settings_for_check()
        missing: list[int] = []
        busy = self._combined_nodes()
        for node in self._selected_nodes():
            if node in busy:
                continue
            sized = size_design(self._project, self._results, settings, self._designs[node])
            if sized is None:
                missing.append(node)
            else:
                self._designs[node] = sized
                self._enabled.add(node)
        self.run_check()
        self._show_selected()
        if missing:
            self._summary.setText(
                self._summary.text()
                + f" No footing up to 8 m passes at node(s) {', '.join(map(str, missing))}"
                " (or there are no static results): check the loads and the soil."
            )

    def combine_selected(self) -> CombinedFootingDesign | None:
        """A combined footing under the selected supports (two or more, none combined yet)."""
        busy = self._combined_nodes()
        nodes = [n for n in self._selected_nodes() if n not in busy]
        if len(nodes) < 2:
            self._summary.setText(
                "Select two or more supports that are not on a combined footing yet."
            )
            return None
        names = {c.name for c in self._combined}
        k = len(self._combined) + 1
        while f"CF-{k}" in names:
            k += 1
        design = default_combined(self._project, nodes, self._settings_for_check(), name=f"CF-{k}")
        self._combined.append(design)
        self._enabled -= set(nodes)
        self.run_check()
        self._tabs.setCurrentIndex(1)
        self._combined_table.selectRow(len(self._combined) - 1)
        self._show_combined()
        return design

    # ── combined ─────────────────────────────────────────────────────
    def _combined_index(self) -> int | None:
        rows = sorted({index.row() for index in self._combined_table.selectedIndexes()})
        return rows[0] if rows else None

    def _show_combined(self) -> None:
        index = self._combined_index()
        if index is None or index >= len(self._combined):
            self._columns_table.setRowCount(0)
            self._show_details()
            return
        design = self._combined[index]
        for key, widget in self._combined_fields.items():
            widget.setValue(float(getattr(design, key)))
        self._columns_table.setRowCount(len(design.columns))
        for row, column in enumerate(design.columns):
            values = [
                str(column.node_id),
                f"{column.column_x:.6g}",
                f"{column.column_y:.6g}",
                f"{column.pedestal_height:.6g}",
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._columns_table.setItem(row, col, item)
        self._show_details()

    def _column_values(self, design: CombinedFootingDesign) -> list[CombinedColumn]:
        out = []
        for row, column in enumerate(design.columns):
            try:
                cx, cy, hp = (float(self._cell(row, col)) for col in (1, 2, 3))
            except ValueError:
                out.append(column)
                continue
            out.append(
                column.model_copy(
                    update={"column_x": cx, "column_y": cy, "pedestal_height": max(hp, 0.0)}
                )
            )
        return out

    def _cell(self, row: int, col: int) -> str:
        item = self._columns_table.item(row, col)
        return item.text() if item is not None else ""

    def apply_combined(self) -> None:
        index = self._combined_index()
        if index is None:
            return
        current = self._combined[index]
        values = {key: w.value() for key, w in self._combined_fields.items()}
        data = {**current.model_dump(), **values}
        data["columns"] = [c.model_dump() for c in self._column_values(current)]
        self._combined[index] = CombinedFootingDesign.model_validate(data)
        self.run_check()
        self._show_combined()

    def size_combined(self) -> None:
        index = self._combined_index()
        if index is None:
            return
        sized = size_combined_design(
            self._project, self._results, self._settings_for_check(), self._combined[index]
        )
        if sized is not None:
            self._combined[index] = sized
        self.run_check()
        self._show_combined()
        if sized is None:
            self._summary.setText(
                self._summary.text() + " No width up to 8 m passes for the combined footing "
                "(or there are no static results): make it longer or check the loads."
            )

    def remove_combined(self) -> None:
        index = self._combined_index()
        if index is None:
            return
        removed = self._combined.pop(index)
        self._enabled |= set(removed.node_ids)
        self.run_check()
        self._show_combined()

    # ── details ──────────────────────────────────────────────────────
    def _current_report(self) -> FootingReport | None:
        if self._tabs.currentIndex() == 1:
            index = self._combined_index()
            if index is None or index >= len(self._combined_reports):
                return None
            return self._combined_reports[index]
        nodes = self._selected_nodes()
        return self._reports.get(nodes[0]) if nodes else None

    def _show_details(self) -> None:
        report = self._current_report()
        if report is None:
            self._details.setHtml("<p>No footing checked here.</p>")
            return
        rows = "".join(
            f"<tr><td>{html.escape(c.name)}</td><td align='right'>{c.ratio:.3f}</td>"
            f"<td>{html.escape(c.value)}</td><td>{html.escape(c.reference)}</td>"
            f"<td>{html.escape(c.load)}</td></tr>"
            for c in sorted(report.checks, key=lambda c: -c.ratio)
        )
        notes = "".join(f"<li>{html.escape(n)}</li>" for n in report.notes)
        self._details.setHtml(
            f"<p><b>{html.escape(report.label)}</b>: {html.escape(report.status)}</p>"
            "<table cellspacing='4'><tr><th align='left'>Check</th><th>Ratio</th>"
            "<th align='left'>Values</th><th align='left'>Reference</th>"
            f"<th align='left'>Load set</th></tr>{rows}</table>"
            + (f"<ul>{notes}</ul>" if notes else "")
        )

    def show_pressure_plan(self) -> None:
        from opensees_studio.views.dialogs.footing_pressures import FootingPressuresDialog

        dialog = FootingPressuresDialog(self._project, self.reports(), self)
        dialog.exec()

    # ── results ──────────────────────────────────────────────────────
    def designs(self) -> dict[int, FootingDesign]:
        busy = self._combined_nodes()
        return {n: self._designs[n] for n in self._enabled if n not in busy}

    def combined(self) -> list[CombinedFootingDesign]:
        return list(self._combined)

    def reports(self) -> list[FootingReport]:
        return list(self._reports.values()) + list(self._combined_reports)

    def settings(self) -> DesignSettings:
        """The design settings with every enabled isolated footing and every combined one.

        Load sets equal to the automatic choice are left unsaved, so they keep
        following the project's combinations.
        """
        busy = self._combined_nodes()
        footings = [
            self._designs[s.node_id]
            for s in self._supports
            if s.node_id in self._enabled and s.node_id not in busy
        ]
        plain = self._base_settings.model_copy(
            update={"footing_service_sets": [], "footing_strength_sets": []}
        )
        auto_service, auto_strength, _notes = footing_load_sets(self._project, plain)
        service = self._checked(self._service)
        strength = self._checked(self._strength)
        return self._base_settings.model_copy(
            update={
                "footings": footings,
                "combined_footings": list(self._combined),
                "footing_service_sets": [] if service == auto_service else service,
                "footing_strength_sets": [] if strength == auto_strength else strength,
            }
        )
