"""Define → Section Designer: draw any cross-section, or import it from a DXF.

The section is a list of regions (polygons and circles, solid or hole) built
with the command line of :mod:`core.sections.drawing` — the shape buttons only
type a command for you — or read from the closed outlines of a DXF file
(:mod:`services.section_dxf`). The drawing, the region list and the properties
update after every command; Undo steps back one command.

OK hands back one section: an **elastic section** with the area, the
centroidal second moments and the torsional constant (solved numerically,
editable), or a **fibre section** of one material on a grid of fibres.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.materials.library import is_uniaxial
from opensees_studio.core.sections.drawing import (
    CommandError,
    describe,
    elastic_section,
    fiber_section,
    run_command,
)
from opensees_studio.core.sections.geometry import (
    CircleRegion,
    PolygonRegion,
    Region,
    SectionProperties,
    section_properties,
    torsion_constant,
)
from opensees_studio.core.units import UnitSystem, labels_for, stress_scale
from opensees_studio.services.dxf_import import DxfImportError
from opensees_studio.services.section_dxf import drawing_scale, read_section_drawing, scaled
from opensees_studio.views.dialogs.section_preview import SectionPreview
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea, scroll_area

#: Shape buttons: label and the command template they type.
_TEMPLATES = [
    ("Rectangle", "rect 0.3 0.5"),
    ("Circle", "circle 0.4"),
    ("I-shape", "ishape 0.3 0.15 0.012 0.008"),
    ("Channel", "channel 0.3 0.1 0.012 0.008"),
    ("Tee", "tee 0.3 0.2 0.015 0.01"),
    ("Angle", "angle 0.1 0.1 0.01"),
    ("Tube", "tube 0.2 0.3 0.01"),
    ("Pipe", "pipe 0.3 0.01"),
    ("Polygon", "poly 0,0 0,0.3 0.4,0.15"),
    ("Hole", "hole circle 0.1"),
]

_HELP = (
    "rect W H [Y Z] · circle D [Y Z] · poly Y1,Z1 Y2,Z2 ... · ishape D BF TF TW · "
    "channel D BF TF TW · tee D BF TF TW · angle D B T · tube W H T · pipe D T · "
    "hole <shape> ... · move N DY DZ · delete N · center · clear. "
    "Y is up the depth, Z across; lengths in {unit}."
)


def material_modulus(material: Any) -> float | None:
    """The initial modulus of a uniaxial material, when it says one."""
    for name in ("E", "E0", "Ec"):
        value = getattr(material, name, None)
        if isinstance(value, int | float) and value > 0:
            return float(value)
    fpc, epsc0 = getattr(material, "fpc", None), getattr(material, "epsc0", None)
    if fpc and epsc0:
        return float(2.0 * fpc / epsc0)
    return None


class SectionDesignerDialog(FittedDialog):
    """Command line, region list, drawing, properties and the section to add."""

    def __init__(self, project: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Section Designer")
        self.resize(1100, 720)
        self._project = project
        self._units: UnitSystem = project.meta.units
        self._regions: list[Region] = []
        self._history: list[list[Region]] = []
        self._props: SectionProperties | None = None
        self._torsion: float | None = None
        self._build_ui()
        self._refresh()

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        labels = labels_for(self._units)
        root = QHBoxLayout(self)
        left = QWidget()
        column = QVBoxLayout(left)

        draw = QGroupBox("Draw")
        draw_layout = QVBoxLayout(draw)
        grid = QGridLayout()
        for k, (label, template) in enumerate(_TEMPLATES):
            button = QPushButton(label)
            button.setToolTip(template)
            button.clicked.connect(lambda _=False, t=template: self._type(t))
            grid.addWidget(button, k // 5, k % 5)
        draw_layout.addLayout(grid)
        line = QHBoxLayout()
        self._command = QLineEdit()
        self._command.setPlaceholderText("rect 0.3 0.5")
        self._command.returnPressed.connect(self.run)
        line.addWidget(self._command, 1)
        run = QPushButton("Run")
        run.clicked.connect(self.run)
        line.addWidget(run)
        draw_layout.addLayout(line)
        hint = QLabel(_HELP.format(unit=labels.length))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #777;")
        draw_layout.addWidget(hint)
        row = QHBoxLayout()
        dxf = QPushButton("Import DXF…")
        dxf.clicked.connect(self._on_import)
        row.addWidget(dxf)
        self._undo = QPushButton("Undo")
        self._undo.clicked.connect(self.undo)
        row.addWidget(self._undo)
        center = QPushButton("Center")
        center.setToolTip("Move the section so its centroid is at the origin.")
        center.clicked.connect(lambda: self.run("center"))
        row.addWidget(center)
        row.addStretch(1)
        draw_layout.addLayout(row)
        column.addWidget(draw)

        regions = QGroupBox("Regions")
        region_layout = QVBoxLayout(regions)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(lambda _row: self._draw())
        region_layout.addWidget(self._list)
        row = QHBoxLayout()
        delete = QPushButton("Delete")
        delete.clicked.connect(self._on_delete)
        toggle = QPushButton("Solid / hole")
        toggle.clicked.connect(self._on_toggle)
        row.addWidget(delete)
        row.addWidget(toggle)
        row.addStretch(1)
        region_layout.addLayout(row)
        column.addWidget(regions)

        out = QGroupBox("Section to add")
        form = QFormLayout(out)
        self._name = QLineEdit()
        self._name.setPlaceholderText("Designed section")
        form.addRow("Name:", self._name)
        self._kind = QComboBox()
        self._kind.addItem("Elastic section", "elastic")
        self._kind.addItem("Fiber section (one material)", "fiber")
        self._kind.currentIndexChanged.connect(self._on_kind)
        form.addRow("Type:", self._kind)
        self._stack = QStackedWidget()
        elastic = QWidget()
        ef = QFormLayout(elastic)
        ef.setContentsMargins(0, 0, 0, 0)
        self._modulus = FloatField()
        self._modulus.setRange(1e-12, 1e18)
        self._modulus.setValue(200e9 * stress_scale(UnitSystem.SI_M_N, self._units))
        ef.addRow(f"E [{labels.stress}]:", self._modulus)
        self._from_material = QComboBox()
        self._from_material.addItem("(type E)", None)
        for material in project_materials(self._project):
            modulus = material_modulus(material)
            if modulus is not None:
                self._from_material.addItem(f"#{material.id} {material.name}", modulus)
        self._from_material.currentIndexChanged.connect(self._on_material_modulus)
        ef.addRow("E from material:", self._from_material)
        self._poisson = FloatField()
        self._poisson.setRange(0.0, 0.5)
        self._poisson.setValue(0.3)
        ef.addRow("Poisson's ratio ν:", self._poisson)
        self._j = FloatField()
        self._j.setRange(0.0, 1e18)
        self._j.setToolTip("Saint-Venant torsional constant, solved on a grid; edit to override.")
        ef.addRow(f"J [{labels.length}⁴]:", self._j)
        self._stack.addWidget(elastic)
        fiber = QWidget()
        ff = QFormLayout(fiber)
        ff.setContentsMargins(0, 0, 0, 0)
        self._material = QComboBox()
        for material in project_materials(self._project):
            if is_uniaxial(material):
                self._material.addItem(f"#{material.id} {material.name}", material.id)
        ff.addRow("Material:", self._material)
        self._cells = QSpinBox()
        self._cells.setRange(4, 200)
        self._cells.setValue(30)
        self._cells.setToolTip("Fibre grid cells along each side of the bounding box.")
        ff.addRow("Grid cells per side:", self._cells)
        self._gj = FloatField()
        self._gj.setRange(0.0, 1e24)
        self._gj.setToolTip("Torsional rigidity GJ for a 3D member (0 = none).")
        ff.addRow(f"GJ [{labels.force}·{labels.length}²]:", self._gj)
        self._stack.addWidget(fiber)
        form.addRow(self._stack)
        column.addWidget(out)
        column.addStretch(1)
        root.addWidget(scroll_area(left, vertical_only=True), 2)

        right = QVBoxLayout()
        self._preview = SectionPreview()
        right.addWidget(self._preview, 1)
        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right.addWidget(self._summary)
        self._message = MessageArea()
        right.addWidget(self._message)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        right.addWidget(self._buttons)
        root.addLayout(right, 3)

    # ── commands ────────────────────────────────────────────────────
    def _type(self, template: str) -> None:
        self._command.setText(template)
        self._command.setFocus()

    def run(self, text: str | None = None) -> bool:
        """Run ``text`` (the command line when omitted); ``False`` when it was refused."""
        command = text if isinstance(text, str) else self._command.text()
        try:
            result = run_command(command, self._regions)
        except CommandError as exc:
            self._message.show_message(str(exc), "error")
            return False
        self._history.append(list(self._regions))
        self._regions = result.regions
        if not isinstance(text, str):
            self._command.clear()
        self._torsion = None
        self._refresh()
        self._message.show_message(result.message, "info")
        return True

    def undo(self) -> None:
        if self._history:
            self._regions = self._history.pop()
            self._torsion = None
            self._refresh()

    def set_regions(self, regions: list[Region]) -> None:
        """Replace the section (an import), as one undoable step."""
        self._history.append(list(self._regions))
        self._regions = list(regions)
        self._torsion = None
        self._refresh()

    def import_dxf(self, path: str | Path) -> bool:
        try:
            drawing = read_section_drawing(path)
        except DxfImportError as exc:
            self._message.show_message(str(exc), "error")
            return False
        if not drawing.regions:
            self._message.show_message(
                f"{Path(path).name}: no closed outline. {drawing.summary()}", "error"
            )
            return False
        factor = drawing_scale(drawing, self._units)
        self.set_regions(scaled(drawing.regions, factor))
        self.run("center")
        note = (
            f"Imported {Path(path).name}: {drawing.summary()} Scaled by {factor:g} to "
            f"{labels_for(self._units).length} and centred."
        )
        if drawing.unit_in_metres is None:
            note += " The file has no units: its numbers were taken as project lengths."
        self._message.show_message(note, "info")
        return True

    def _on_import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import a section from DXF", "", "DXF drawings (*.dxf)"
        )
        if path:
            self.import_dxf(path)

    def _on_delete(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self.run(f"delete {row + 1}")

    def _on_toggle(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        region = self._regions[row]
        flipped: Region = (
            CircleRegion(region.y, region.z, region.radius, not region.hole)
            if isinstance(region, CircleRegion)
            else PolygonRegion(region.points, not region.hole)
        )
        self._history.append(list(self._regions))
        self._regions[row] = flipped
        self._torsion = None
        self._refresh()

    def _on_kind(self) -> None:
        self._stack.setCurrentIndex(self._kind.currentIndex())
        self._refresh()

    def _on_material_modulus(self) -> None:
        modulus = self._from_material.currentData()
        if modulus is not None:
            self._modulus.setValue(float(modulus))

    # ── state ───────────────────────────────────────────────────────
    def regions(self) -> list[Region]:
        return list(self._regions)

    def properties(self) -> SectionProperties | None:
        return self._props

    def _refresh(self) -> None:
        row = self._list.currentRow()
        self._list.blockSignals(True)
        self._list.clear()
        for k, region in enumerate(self._regions):
            self._list.addItem(f"{k + 1}. {describe(region)}")
        self._list.setCurrentRow(min(row, len(self._regions) - 1))
        self._list.blockSignals(False)
        self._undo.setEnabled(bool(self._history))
        try:
            self._props = section_properties(self._regions) if self._regions else None
        except ValueError as exc:
            self._props = None
            self._message.show_message(str(exc), "error")
        if self._props is not None and self._torsion is None:
            self._torsion = torsion_constant(self._regions)
            self._j.setValue(self._torsion)
            g = self._modulus.value() / (2.0 * (1.0 + self._poisson.value()))
            self._gj.setValue(g * self._torsion)
        self._summary.setText(self._describe())
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        fiber_ready = self._kind.currentData() != "fiber" or self._material.count() > 0
        ok.setEnabled(self._props is not None and fiber_ready)
        if self._props is not None and not fiber_ready:
            self._message.show_message(
                "A fiber section needs a uniaxial material: add one in Define → Material "
                "Library first.",
                "warning",
            )
        self._draw()

    def _draw(self) -> None:
        self._preview.clear()
        if not self._regions:
            return
        self._preview.draw_regions(self._regions, selected=self._list.currentRow())
        if self._props is not None:
            self._preview.draw_centroid(self._props.y_c, self._props.z_c)
        self._preview.fit()

    def _describe(self) -> str:
        props = self._props
        if props is None:
            return "Draw a shape or import a DXF to start."
        u = labels_for(self._units).length
        lines = [
            f"A = {props.A:.5g} {u}²; centroid y = {props.y_c:.5g}, z = {props.z_c:.5g} {u}",
            f"Iz = {props.Iz:.5g}, Iy = {props.Iy:.5g}, Iyz = {props.Iyz:.4g} {u}⁴; "
            f"I1 = {props.I1:.5g}, I2 = {props.I2:.5g} at {props.angle:.1f}°",
            f"Sz = {props.Sz:.5g}, Sy = {props.Sy:.5g}, Zz = {props.Zz:.5g}, Zy = {props.Zy:.5g} "
            f"{u}³; rz = {props.rz:.4g}, ry = {props.ry:.4g} {u}",
            f"J = {self._torsion or 0.0:.5g} {u}⁴ (Saint-Venant, solved on a grid)",
        ]
        lines += list(props.notes)
        return "<br>".join(lines)

    # ── the result ──────────────────────────────────────────────────
    def built_section(self) -> Any | None:
        """The section OK adds, or ``None`` while there is nothing to add."""
        if self._props is None:
            return None
        section_id = self._project.next_section_id()
        name = self._name.text().strip() or "Designed section"
        if self._kind.currentData() == "fiber":
            material_id = self._material.currentData()
            if material_id is None:
                return None
            return fiber_section(
                self._regions,
                section_id=section_id,
                name=name,
                material_id=int(material_id),
                torsional_rigidity=self._gj.value() or None,
                cells=self._cells.value(),
            )
        return elastic_section(
            self._regions,
            section_id=section_id,
            name=name,
            modulus=self._modulus.value(),
            poisson=self._poisson.value(),
            torsion=self._j.value() or None,
        )


def project_materials(project: Any) -> list[Any]:
    return list(getattr(project, "materials", []) or [])
