"""Design → Built-Up Shapes: welded I-shapes defined from their plates.

One row per shape: its name, the depth d, the flange bf x tf, the web tw and,
for a plate girder, the spacing a of its transverse stiffeners (0 = none). The
area, the strong-axis inertia and plastic modulus, and the flange and web
classes of AISC 360 Table B4.1 (with kc for a built-up flange) follow as you
type. A section or a member override that names a shape is checked with it.

OK stores the shapes in ``Project.design`` and, when asked, adds an elastic
analysis section for every shape no section is named after yet — one undo step.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.design.aisc360 import Steel, slenderness
from opensees_studio.core.design.built_up import analysis_section, built_up_ishape
from opensees_studio.core.design.built_up_model import BuiltUpShape
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.core.design.steel_grades import DEFAULT_GRADES, grade_stresses
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.sections import ElasticSection
from opensees_studio.core.units import UnitSystem, labels_for, length_scale, stress_scale
from opensees_studio.views.dialogs.design_basis import _ok_cancel
from opensees_studio.views.screen_fit import FittedDialog

_INPUTS = ("name", "d", "bf", "tf", "tw", "stiffener_spacing")
_OUTPUTS = ("A", "Ix", "Zx", "Flange", "Web")


class BuiltUpShapesDialog(FittedDialog):
    """Define, edit and remove the project's welded I-shapes."""

    def __init__(self, project: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._settings = project.design or DesignSettings()
        self.setWindowTitle("Built-Up Shapes")
        self.setProperty(TOPIC_PROPERTY, "design.built_up")
        units = project.meta.units
        lab = labels_for(units)
        key = self._settings.steel_grades.get("BU", DEFAULT_GRADES["BU"])
        fy, _fu = grade_stresses(key, "BU", units)
        self._steel = Steel(Fy=fy, E=29000.0 * stress_scale(UnitSystem.US_IN_KIP, units), G=1.0)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Doubly symmetric I-shapes welded from three plates. Name a section after one "
            "(or give it as a member's shape override) and the steel check uses it: Table "
            "B4.1 with kc for the flanges, F2 to F5, and web shear with the stiffeners "
            f"(a = 0: none). Classes for Fy = {fy:.4g} {lab.stress} (the BU grade)."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        headers = [
            "Name",
            f"d [{lab.length}]",
            f"bf [{lab.length}]",
            f"tf [{lab.length}]",
            f"tw [{lab.length}]",
            f"a [{lab.length}]",
            f"A [{lab.length}²]",
            f"Ix [{lab.length}⁴]",
            f"Zx [{lab.length}³]",
            "Flange",
            "Web",
        ]
        self._table = QTableWidget(0, len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.itemChanged.connect(self._refresh_row)
        layout.addWidget(self._table)
        row = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(lambda: self.add_shape())
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_selected)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)
        self._create = QCheckBox("Add an analysis section for each shape no section is named after")
        self._create.setChecked(True)
        layout.addWidget(self._create)
        self._message = QLabel()
        self._message.setWordWrap(True)
        layout.addWidget(self._message)
        self._buttons = _ok_cancel(self)
        layout.addWidget(self._buttons)
        for shape in self._settings.built_up:
            self.add_shape(shape)

    # ── rows ─────────────────────────────────────────────────────────
    def add_shape(self, shape: BuiltUpShape | None = None) -> None:
        if shape is None:
            inch = length_scale(UnitSystem.US_IN_KIP, self._project.meta.units)
            shape = BuiltUpShape(
                name=f"BU{self._table.rowCount() + 1}",
                d=36.0 * inch,
                bf=12.0 * inch,
                tf=1.0 * inch,
                tw=0.5 * inch,
            )
        r = self._table.rowCount()
        self._table.blockSignals(True)
        self._table.insertRow(r)
        for col, key in enumerate(_INPUTS):
            value = getattr(shape, key)
            text = value if key == "name" else f"{value or 0:g}"
            self._table.setItem(r, col, QTableWidgetItem(str(text)))
        self._table.blockSignals(False)
        self._refresh_row(self._table.item(r, 0))

    def remove_selected(self) -> None:
        for r in sorted({i.row() for i in self._table.selectedIndexes()}, reverse=True):
            self._table.removeRow(r)
        self._validate()

    def _shape_at(self, r: int) -> BuiltUpShape:
        cells = [self._table.item(r, c) for c in range(len(_INPUTS))]
        name = (cells[0].text() if cells[0] else "").strip()
        values = [float(c.text()) if c and c.text().strip() else 0.0 for c in cells[1:]]
        d, bf, tf, tw, a = values
        return BuiltUpShape(
            name=name, d=d, bf=bf, tf=tf, tw=tw, stiffener_spacing=a if a > 0.0 else None
        )

    def _refresh_row(self, item: QTableWidgetItem | None) -> None:
        if item is None or item.column() >= len(_INPUTS):
            return
        r = item.row()
        self._table.blockSignals(True)
        try:
            props = built_up_ishape(self._shape_at(r))
            classes = slenderness(props, self._steel)
            values = [
                f"{props.A:.5g}",
                f"{props.Ix:.5g}",
                f"{props.Zx:.5g}",
                f"{classes.flange_class} ({classes.flange:.3g})",
                f"{classes.web_class} ({classes.web:.3g})",
            ]
        except (ValueError, ZeroDivisionError):
            values = ["-"] * len(_OUTPUTS)
        for k, text in enumerate(values):
            cell = QTableWidgetItem(text)
            cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(r, len(_INPUTS) + k, cell)
        self._table.blockSignals(False)
        self._validate()

    def _validate(self) -> None:
        try:
            shapes = self.shapes()
        except ValueError as exc:
            self._message.setText(f"<b>{exc}</b>")
            self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return
        names = [s.name.upper() for s in shapes]
        duplicate = next((n for n in names if names.count(n) > 1), None)
        ok = duplicate is None
        self._message.setText("" if ok else f"<b>The name {duplicate} is used twice.</b>")
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    # ── results ──────────────────────────────────────────────────────
    def shapes(self) -> list[BuiltUpShape]:
        """The shapes in the table. Raises ValueError for an incomplete or impossible row."""
        out: list[BuiltUpShape] = []
        for r in range(self._table.rowCount()):
            try:
                out.append(self._shape_at(r))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Row {r + 1}: {exc}") from None
        return out

    def settings(self) -> DesignSettings:
        return self._settings.model_copy(update={"built_up": self.shapes()})

    def new_sections(self) -> list[ElasticSection]:
        """An elastic section for every shape no section is named after (when asked)."""
        if not self._create.isChecked():
            return []
        units = self._project.meta.units
        ksi = stress_scale(UnitSystem.US_IN_KIP, units)
        taken = {(s.name or "").strip().upper() for s in self._project.sections}
        next_id = self._project.next_section_id()
        out: list[ElasticSection] = []
        for shape in self.shapes():
            if shape.name.strip().upper() in taken:
                continue
            out.append(
                analysis_section(
                    shape,
                    section_id=next_id,
                    elastic_modulus=29000.0 * ksi,
                    shear_modulus=11200.0 * ksi,
                    ndm=self._project.ndm,
                )
            )
            next_id += 1
        return out
