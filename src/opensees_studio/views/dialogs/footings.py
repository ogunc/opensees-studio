"""Design → Footings: an isolated footing under every support, ACI 318-19 and the soil.

One row per vertically restrained node (:mod:`services.footings`), with a box
that says whether the support gets a footing. The selected rows' footing is
edited in the form; **Size** finds the smallest plan, thickness and bars that
pass. The checks of the selected footing are listed with their values, clause
and load set. The two lists at the bottom pick the service (soil) and strength
(concrete) load sets. Nothing is stored until OK, which keeps the footings in
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
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.design.footing import FootingDesign
from opensees_studio.core.design.settings import DesignLoadSet, DesignSettings
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import labels_for
from opensees_studio.services.footings import (
    STATUS_REQUIRES_VERIFICATION,
    FootingReport,
    FootingSupport,
    check_footings,
    default_footing,
    footing_load_sets,
    footing_supports,
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
_SIGNED = {"offset_x", "offset_y"}
_ZERO_OK = {"pedestal_height", "soil_cover"}


class FootingsDialog(FittedDialog):
    """The supports, their footings and the governing ratio of each."""

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
        self._enabled: set[int] = set(saved) or {s.node_id for s in self._supports}
        self._reports: dict[int, FootingReport] = {}

        layout = QVBoxLayout(self)
        intro = QLabel(
            "An isolated footing under each support restrained in Uz. The soil is checked with "
            "the service (ASD) load sets, the concrete with the strength (LRFD) ones, after "
            "ACI 318-19. A steel column's base plate stays in Design → Base Plates; with a "
            "footing its A2 comes from here."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self._table = QTableWidget(len(self._supports), len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._show_selected)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.setMinimumHeight(140)
        splitter.addWidget(self._table)

        middle = QWidget()
        row = QHBoxLayout(middle)
        row.setContentsMargins(0, 0, 0, 0)
        lab = labels_for(units)
        self._fields: dict[str, FloatField] = {}
        form = QFormLayout()
        for key, label in _LENGTHS:
            form.addRow(f"{label} [{lab.length}]:", self._field(key))
        for key, label in _STRESSES:
            form.addRow(f"{label} [{lab.stress}]:", self._field(key))
        for key, label in _WEIGHTS:
            form.addRow(f"{label} [{lab.force}/{lab.length}³]:", self._field(key))
        for key, label in _FACTORS:
            form.addRow(f"{label}:", self._field(key))
        box = QGroupBox("Footing of the selected supports")
        box.setLayout(form)
        row.addWidget(box)
        self._details = QTextBrowser()
        row.addWidget(self._details, 1)
        splitter.addWidget(middle)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        self._apply = QPushButton("Apply to the selected supports")
        self._apply.clicked.connect(self.apply_to_selected)
        self._size = QPushButton("Size the selected footings")
        self._size.clicked.connect(self.size_selected)
        buttons.addWidget(self._apply)
        buttons.addWidget(self._size)
        buttons.addStretch(1)
        layout.addLayout(buttons)

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
            sets.addWidget(group)
        layout.addLayout(sets)
        self._service.itemChanged.connect(lambda _i: self.run_check())
        self._strength.itemChanged.connect(lambda _i: self.run_check())

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        layout.addWidget(_ok_cancel(self))
        self.run_check()
        if self._supports:
            self._table.selectRow(0)

    def _field(self, key: str) -> FloatField:
        widget = FloatField()
        low = -1e18 if key in _SIGNED else (0.0 if key in _ZERO_OK else 1e-12)
        widget.setRange(low, 1e18)
        self._fields[key] = widget
        return widget

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

    def _settings_for_check(self) -> DesignSettings:
        return self._base_settings.model_copy(
            update={
                "footing_service_sets": self._checked(self._service),
                "footing_strength_sets": self._checked(self._strength),
            }
        )

    # ── table ────────────────────────────────────────────────────────
    def run_check(self) -> list[FootingReport]:
        settings = self._settings_for_check()
        reports = check_footings(
            self._project, self._results, settings,
            designs={n: self._designs[n] for n in self._enabled}, nodes=self._enabled,
        )  # fmt: skip
        self._reports = {r.node_id: r for r in reports}
        self._table.blockSignals(True)
        for row, support in enumerate(self._supports):
            design = self._designs[support.node_id]
            report = self._reports.get(support.node_id)
            enabled = support.node_id in self._enabled
            values = [
                "",
                str(support.node_id),
                support.column or "-",
                f"{design.length_x:.4g} × {design.width_y:.4g} × {design.thickness:.4g}",
                f"{design.bar_x_diameter:.3g}@{design.bar_x_spacing:.3g} / "
                f"{design.bar_y_diameter:.3g}@{design.bar_y_spacing:.3g}",
                f"{report.ratio:.3f}" if report and report.governing else "-",
                (report.governing or report.status) if report else "no footing",
                report.load_set if report else "",
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(
                        Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked
                    )
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if report is not None:
                    if report.status == "NG":
                        item.setForeground(QBrush(QColor(tone("error"))))
                    elif report.status == STATUS_REQUIRES_VERIFICATION:
                        item.setForeground(QBrush(QColor(tone("warning"))))
                    if report.notes:
                        item.setToolTip("\n".join(report.notes))
                self._table.setItem(row, col, item)
        self._table.blockSignals(False)
        self._table.resizeColumnsToContents()
        failing = sum(1 for r in reports if r.status == "NG")
        pending = sum(1 for r in reports if r.status == STATUS_REQUIRES_VERIFICATION)
        if not self._supports:
            text = "No support restrained in Uz."
        else:
            text = f"{len(reports)} footing(s), {failing} over the limit"
            text += f", {pending} requiring verification." if pending else "."
        self._summary.setText(text)
        self._show_details()
        return reports

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

    def _show_details(self) -> None:
        nodes = self._selected_nodes()
        report = self._reports.get(nodes[0]) if nodes else None
        if report is None:
            self._details.setHtml("<p>No footing checked at this support.</p>")
            return
        rows = "".join(
            f"<tr><td>{html.escape(c.name)}</td><td align='right'>{c.ratio:.3f}</td>"
            f"<td>{html.escape(c.value)}</td><td>{html.escape(c.reference)}</td>"
            f"<td>{html.escape(c.load)}</td></tr>"
            for c in sorted(report.checks, key=lambda c: -c.ratio)
        )
        notes = "".join(f"<li>{html.escape(n)}</li>" for n in report.notes)
        self._details.setHtml(
            f"<p><b>Node {report.node_id}</b>: {html.escape(report.status)}</p>"
            "<table cellspacing='4'><tr><th align='left'>Check</th><th>Ratio</th>"
            "<th align='left'>Values</th><th align='left'>Reference</th>"
            f"<th align='left'>Load set</th></tr>{rows}</table>"
            + (f"<ul>{notes}</ul>" if notes else "")
        )

    def _form_values(self) -> dict[str, Any]:
        return {key: w.value() for key, w in self._fields.items()}

    def apply_to_selected(self) -> None:
        values = self._form_values()
        for node in self._selected_nodes():
            current = self._designs[node]
            self._designs[node] = FootingDesign.model_validate({**current.model_dump(), **values})
            self._enabled.add(node)
        self.run_check()

    def size_selected(self) -> None:
        settings = self._settings_for_check()
        missing: list[int] = []
        for node in self._selected_nodes():
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

    def designs(self) -> dict[int, FootingDesign]:
        return {n: self._designs[n] for n in self._enabled}

    def reports(self) -> list[FootingReport]:
        return list(self._reports.values())

    def settings(self) -> DesignSettings:
        """The design settings with the footings of every enabled support.

        Load sets equal to the automatic choice are left unsaved, so they keep
        following the project's combinations.
        """
        footings = [self._designs[s.node_id] for s in self._supports if s.node_id in self._enabled]
        plain = self._base_settings.model_copy(
            update={"footing_service_sets": [], "footing_strength_sets": []}
        )
        auto_service, auto_strength, _notes = footing_load_sets(self._project, plain)
        service = self._checked(self._service)
        strength = self._checked(self._strength)
        return self._base_settings.model_copy(
            update={
                "footings": footings,
                "footing_service_sets": [] if service == auto_service else service,
                "footing_strength_sets": [] if strength == auto_strength else strength,
            }
        )
