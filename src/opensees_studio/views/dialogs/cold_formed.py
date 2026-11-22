"""Define → Section Library → Add Cold-Formed (AISI): purlins, tracks, zees, hats, angles.

Pick a profile (or two channels joined into a box or back to back) and one of
the generated sizes, or type the dimensions; the
profile is drawn, its properties (AISI linear method) are listed, and OK
inserts an elastic section made of the chosen material with the profile's
shear areas (``core.cold_formed_sections``).
"""

from __future__ import annotations

import html
from typing import Any

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.cold_formed_sections import (
    cold_formed_section,
    default_cold_formed_material,
    in_units,
)
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.section_materials import linkable_materials
from opensees_studio.core.sections import ElasticSection
from opensees_studio.core.sections.cold_formed import (
    ASSEMBLY_LABELS,
    ASSEMBLY_PROFILES,
    PROFILE_LABELS,
    ColdFormedShape,
    assemblies,
    designations,
    outlines,
    properties,
)
from opensees_studio.core.units import labels_for
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog
from opensees_studio.views.theme import drawing_colour, tone_span

#: The dimension fields each profile uses, in order.
_FIELDS: dict[str, tuple[str, ...]] = {
    "CS": ("d", "bf", "lip", "t", "r"),
    "CU": ("d", "bf", "t", "r"),
    "ZS": ("d", "bf", "lip", "lip_angle", "t", "r"),
    "HU": ("d", "bf", "b2", "t", "r"),
    "LU": ("d", "bf", "t", "r"),
}

_LABELS: dict[str, str] = {
    "d": "Depth d",
    "bf": "Flange bf",
    "lip": "Lip",
    "lip_angle": "Lip angle (°)",
    "b2": "Bottom flange b2",
    "t": "Thickness t",
    "r": "Inside radius r",
}


class _ProfileView(QWidget):
    """The profile's outline, scaled to fit."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(220, 220)
        self._sheets: list[list[tuple[float, float]]] = []
        self._points: list[tuple[float, float]] = []

    def set_shape(self, shape: ColdFormedShape | None) -> None:
        self._sheets = outlines(shape) if shape is not None else []
        self._points = [p for sheet in self._sheets for p in sheet]
        self.update()

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(drawing_colour("background")))
        if not self._points:
            return
        xs = [p[0] for p in self._points]
        ys = [p[1] for p in self._points]
        span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
        scale = 0.85 * min(self.width(), self.height()) / span
        cx, cy = (max(xs) + min(xs)) / 2.0, (max(ys) + min(ys)) / 2.0
        painter.setPen(QPen(QColor(drawing_colour("outline")), 1.0))
        painter.setBrush(QBrush(QColor(drawing_colour("fill"))))
        for sheet in self._sheets:
            polygon = QPolygonF(
                [
                    QPointF(
                        self.width() / 2 + (x - cx) * scale, self.height() / 2 - (y - cy) * scale
                    )
                    for x, y in sheet
                ]
            )
            painter.drawPolygon(polygon)


class ColdFormedDialog(FittedDialog):
    """Pick or type a cold-formed profile; :meth:`result_section` is what the caller inserts."""

    def __init__(self, project: Any, next_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cold-Formed Sections (AISI)")
        self.setProperty(TOPIC_PROPERTY, "define.cold_formed")
        self.resize(820, 560)
        self._project = project
        self._units = project.meta.units
        self._labels = labels_for(self._units)
        self._section_id = next_id
        singles = designations()
        self._sizes = singles + assemblies(singles)

        self._profile = QComboBox()
        for code, label in PROFILE_LABELS.items():
            self._profile.addItem(f"{code} — {label}", code)
        for assembly, label in ASSEMBLY_LABELS.items():
            for code in PROFILE_LABELS:
                if code in ASSEMBLY_PROFILES:
                    self._profile.addItem(f"2 {code} — {label}", f"{code}:{assembly}")
        self._profile.currentIndexChanged.connect(self._on_profile)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_size)

        self._fields: dict[str, FloatField] = {}
        self._form = QFormLayout()
        for name in ("d", "bf", "lip", "lip_angle", "b2", "t", "r"):
            field = FloatField()
            field.setRange(0.0, 1e9)
            field.valueChanged.connect(self._update)
            self._fields[name] = field
            unit = "" if name == "lip_angle" else f" ({self._labels.length})"
            self._form.addRow(f"{_LABELS[name]}{unit}:", field)

        self._material = QComboBox()
        default = default_cold_formed_material(project)
        for material in linkable_materials(project):
            self._material.addItem(f"#{material.id} {material.name}", material.id)
            if default is not None and material.id == default.id:
                self._material.setCurrentIndex(self._material.count() - 1)
        self._material.addItem("(no material: E = 29500 ksi, G = 11346 ksi)", None)
        if default is None:
            self._material.setCurrentIndex(self._material.count() - 1)
        self._form.addRow("Material:", self._material)

        self._view = _ProfileView()
        self._props = QLabel("")
        self._props.setWordWrap(True)
        self._props.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        left = QVBoxLayout()
        left.addWidget(QLabel("Profile:"))
        left.addWidget(self._profile)
        left.addWidget(QLabel("Sizes (generated by formula, inches):"))
        left.addWidget(self._list, stretch=1)
        middle = QVBoxLayout()
        middle.addLayout(self._form)
        middle.addStretch(1)
        right = QVBoxLayout()
        right.addWidget(self._view, stretch=1)
        right.addWidget(self._props)
        row = QHBoxLayout()
        row.addLayout(left, stretch=1)
        row.addLayout(middle, stretch=1)
        row.addLayout(right, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer = QVBoxLayout(self)
        outer.addLayout(row, stretch=1)
        outer.addWidget(buttons)
        self._on_profile()

    # ── public API (also used by tests) ──────────────────────────────
    def profile(self) -> str:
        """The profile code of the picked entry (``CS`` also for a box of two CS)."""
        return str(self._profile.currentData()).split(":")[0]

    def assembly(self) -> str:
        """``single``, ``box`` or ``back_to_back``."""
        key = str(self._profile.currentData())
        return key.split(":")[1] if ":" in key else "single"

    def set_profile(self, code: str, assembly: str = "single") -> None:
        key = code if assembly == "single" else f"{code}:{assembly}"
        self._profile.setCurrentIndex(self._profile.findData(key))

    def select_size(self, designation: str) -> None:
        for row in range(self._list.count()):
            if self._list.item(row).text() == designation:
                self._list.setCurrentRow(row)
                return
        raise KeyError(designation)

    def shape(self) -> ColdFormedShape:
        """The profile as typed, in the project's units (raises if it is not valid)."""
        values: dict[str, Any] = {
            name: self._fields[name].value() for name in _FIELDS[self.profile()]
        }
        values.update(profile=self.profile(), assembly=self.assembly())
        return ColdFormedShape.model_validate(values)

    def result_section(self) -> ElasticSection:
        material_id = self._material.currentData()
        material = next((m for m in self._project.materials if m.id == material_id), None)
        ksi_to_project = 1.0
        if material is None:
            from opensees_studio.core.units import UnitSystem, stress_scale

            ksi_to_project = stress_scale(UnitSystem.US_IN_KIP, self._units)
        shape = self.shape()
        name = self._list.currentItem().text() if self._list.currentItem() is not None else ""
        if name and name != in_units_name(shape, self._units):
            name = ""  # the dimensions were edited: name it by its own dimensions
        return cold_formed_section(
            shape,
            section_id=self._section_id,
            ndm=self._project.ndm,
            name=name,
            material=material,
            units=self._units,
            elastic_modulus=29_500.0 * ksi_to_project,
            shear_modulus=29_500.0 / 2.6 * ksi_to_project,
        )

    # ── slots ────────────────────────────────────────────────────────
    def _on_profile(self, _index: int = 0) -> None:
        code = self.profile()
        for name, field in self._fields.items():
            shown = name in _FIELDS[code]
            field.setVisible(shown)
            label = self._form.labelForField(field)
            if label is not None:
                label.setVisible(shown)
        self._list.blockSignals(True)
        self._list.clear()
        assembly = self.assembly()
        for size in self._sizes:
            if size.profile == code and size.assembly == assembly:
                self._list.addItem(QListWidgetItem(size.designation))
        self._list.blockSignals(False)
        if self._list.count():
            self._list.setCurrentRow(0)
            self._on_size(0)

    def _on_size(self, row: int) -> None:
        item = self._list.item(row)
        if item is None:
            return
        size = next(s for s in self._sizes if s.designation == item.text())
        shape = in_units(size, self._units)
        for name, field in self._fields.items():
            field.blockSignals(True)
            field.setValue(float(getattr(shape, name)))
            field.blockSignals(False)
        self._update()

    def _update(self, *_args: Any) -> None:
        try:
            shape = self.shape()
        except ValueError as exc:
            self._view.set_shape(None)
            self._props.setText(tone_span(html.escape(str(exc)), "error"))
            return
        self._view.set_shape(shape)
        p = properties(shape)
        length = self._labels.length
        notes = {
            "box": "<i>Two channels toe to toe: J is the closed cell's (Bredt) and Cw is "
            "taken as zero.</i><br>",
            "back_to_back": "<i>Two channels back to back: J is the two open channels', "
            "Cw that of an I with the two webs acting as one.</i><br>",
        }
        self._props.setText(
            notes.get(shape.assembly, "") + f"A = {p.A:.5g} {length}²<br>"
            f"Ix = {p.Ix:.5g}, Iy = {p.Iy:.5g}, Ixy = {p.Ixy:.4g} {length}⁴<br>"
            f"J = {p.J:.4g} {length}⁴, Cw = {p.Cw:.5g} {length}⁶<br>"
            f"x₀ = {p.x0:.4g} {length} (shear centre from the centroid)<br>"
            "<i>Gross properties by the AISI linear method. The elastic section takes Ix, "
            "Iy and J; Ixy and Cw are listed for the design.</i>"
        )


def in_units_name(shape: ColdFormedShape, units: Any) -> str:
    """The designation of the generated size ``shape`` matches, if any."""
    singles = designations()
    for size in singles + assemblies(singles):
        candidate = in_units(size, units)
        if (
            candidate.profile == shape.profile
            and candidate.assembly == shape.assembly
            and all(
                abs(getattr(candidate, n) - getattr(shape, n))
                <= 1e-9 * max(1.0, abs(getattr(shape, n)))
                for n in ("d", "bf", "t", "r", "lip", "lip_angle", "b2")
            )
        ):
            return size.designation
    return ""
