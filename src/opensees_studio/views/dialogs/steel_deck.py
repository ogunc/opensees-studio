"""Define → Steel Deck Slab Wizard: a composite deck slab as an orthotropic layered shell.

The numbers are in :mod:`core.steel_deck`; this dialog collects the deck's
geometry and materials in the project's units, draws two ribs of the slab and
lists the stiffness in each direction and what will be added. OK hands back the
materials and the section; the window adds them in one undo step.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.default_materials import DEFAULT_MATERIALS, build_material
from opensees_studio.core.materials import ElasticIsotropic
from opensees_studio.core.sections.geometry import PolygonRegion
from opensees_studio.core.steel_deck import (
    DECK_GAUGES,
    DECK_PROFILES,
    DeckInput,
    DeckModel,
    build_deck_model,
    deck_outline,
    mm_in_units,
    profile_in_units,
)
from opensees_studio.core.units import UnitSystem, labels_for
from opensees_studio.views.dialogs.section_preview import SectionPreview
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea, scroll_area

#: The concrete and the sheet steel the wizard starts with.
DEFAULT_CONCRETE = "4000Psi"
DEFAULT_SHEET_STEEL = "A653SSGr33"
#: Concrete above the ribs a new deck starts with, mm.
DEFAULT_TOPPING_MM = 65.0
CUSTOM = "Custom"


def _elastic_materials(project: Any) -> list[tuple[str, ElasticIsotropic]]:
    """``(label, material)`` for every isotropic material, then the defaults it lacks.

    A default material the project does not have is offered for its numbers
    only (E, ν, ρ); nothing is added to the project for it.
    """
    units: UnitSystem = project.meta.units
    out = [
        (f"{m.name or m.type} (#{m.id})", m)
        for m in project.materials
        if isinstance(m, ElasticIsotropic)
    ]
    have = {m.name for _, m in out}
    for entry in DEFAULT_MATERIALS:
        if entry.name not in have:
            out.append((f"{entry.name} (default values)", build_material(entry, 999999, units)))
    return out


class SteelDeckDialog(FittedDialog):
    """Geometry, materials, a drawing and the orthotropic properties of a deck slab."""

    def __init__(self, project: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Steel Deck Slab Wizard")
        self.resize(1000, 680)
        self._project = project
        self._units: UnitSystem = project.meta.units
        self._result: DeckModel | None = None
        self._materials = _elastic_materials(project)
        self._build_ui()
        self._on_profile()
        self._on_gauge()
        self._topping.setValue(mm_in_units(DEFAULT_TOPPING_MM, self._units))
        self._refresh()

    # ── UI ──────────────────────────────────────────────────────────
    def _float(self) -> FloatField:
        field = FloatField()
        field.setRange(0.0, 1e15)
        field.valueChanged.connect(self._refresh)
        return field

    def _material_combo(self, preferred: str) -> QComboBox:
        combo = QComboBox()
        for label, material in self._materials:
            combo.addItem(label, material)
        index = next(
            (k for k, (_, m) in enumerate(self._materials) if m.name == preferred),
            0,
        )
        combo.setCurrentIndex(index)
        combo.currentIndexChanged.connect(self._refresh)
        return combo

    def _build_ui(self) -> None:
        length = labels_for(self._units).length
        root = QHBoxLayout(self)
        left = QWidget()
        form_root = QVBoxLayout(left)

        deck = QGroupBox("Deck profile")
        f = QFormLayout(deck)
        self._profile = QComboBox()
        for profile in DECK_PROFILES:
            self._profile.addItem(profile.name, profile)
        self._profile.addItem(CUSTOM, None)
        self._profile.currentIndexChanged.connect(self._on_profile)
        f.addRow("Profile:", self._profile)
        self._hr = self._float()
        self._pitch = self._float()
        self._wb = self._float()
        self._wt = self._float()
        f.addRow(f"Rib height hr [{length}]:", self._hr)
        f.addRow(f"Rib spacing (pitch) [{length}]:", self._pitch)
        f.addRow(f"Concrete rib width, bottom [{length}]:", self._wb)
        f.addRow(f"Concrete rib width, top [{length}]:", self._wt)
        self._gauge = QComboBox()
        for name, thickness in DECK_GAUGES.items():
            self._gauge.addItem(f"{name} ({thickness:g} mm)", thickness)
        self._gauge.addItem(CUSTOM, None)
        self._gauge.setCurrentIndex(1)  # 20 ga
        self._gauge.currentIndexChanged.connect(self._on_gauge)
        f.addRow("Sheet gauge:", self._gauge)
        self._t = self._float()
        f.addRow(f"Sheet thickness t [{length}]:", self._t)
        for field in (self._hr, self._pitch, self._wb, self._wt):
            field.valueChanged.connect(self._mark_custom_profile)
        self._t.valueChanged.connect(self._mark_custom_gauge)
        form_root.addWidget(deck)

        slab = QGroupBox("Slab")
        f = QFormLayout(slab)
        self._topping = self._float()
        f.addRow(f"Concrete above the ribs tc [{length}]:", self._topping)
        self._concrete = self._material_combo(DEFAULT_CONCRETE)
        f.addRow("Concrete:", self._concrete)
        self._steel = self._material_combo(DEFAULT_SHEET_STEEL)
        f.addRow("Deck steel:", self._steel)
        self._ribs_along = QComboBox()
        self._ribs_along.addItem("Local 1 (first edge of each shell)", "x")
        self._ribs_along.addItem("Local 2", "y")
        self._ribs_along.currentIndexChanged.connect(self._refresh)
        f.addRow("Ribs run along:", self._ribs_along)
        form_root.addWidget(slab)

        out = QGroupBox("Add to the project")
        f = QFormLayout(out)
        self._name = QLineEdit()
        self._name.setPlaceholderText("from the deck and the concrete")
        self._name.textChanged.connect(self._refresh)
        f.addRow("Section name:", self._name)
        form_root.addWidget(out)
        form_root.addStretch(1)
        root.addWidget(scroll_area(left, vertical_only=True), 2)

        right = QVBoxLayout()
        self._preview = SectionPreview()
        self._preview.setLabel("bottom", "across the ribs")
        self._preview.setLabel("left", "")
        right.addWidget(self._preview, 1)
        self._summary = QLabel("")
        self._summary.setWordWrap(True)
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

    # ── reactions ───────────────────────────────────────────────────
    def _on_profile(self) -> None:
        profile = self._profile.currentData()
        if profile is None:
            return
        values = profile_in_units(profile, self._units)
        fields = {"rib_height": self._hr, "pitch": self._pitch}
        fields.update(rib_bottom=self._wb, rib_top=self._wt)
        for key, field in fields.items():
            field.blockSignals(True)
            field.setValue(values[key])
            field.blockSignals(False)
        self._refresh()

    def _on_gauge(self) -> None:
        thickness = self._gauge.currentData()
        if thickness is None:
            return
        self._t.blockSignals(True)
        self._t.setValue(mm_in_units(thickness, self._units))
        self._t.blockSignals(False)
        self._refresh()

    def _mark_custom_profile(self) -> None:
        self._profile.blockSignals(True)
        self._profile.setCurrentIndex(self._profile.count() - 1)
        self._profile.blockSignals(False)

    def _mark_custom_gauge(self) -> None:
        self._gauge.blockSignals(True)
        self._gauge.setCurrentIndex(self._gauge.count() - 1)
        self._gauge.blockSignals(False)

    # ── model ───────────────────────────────────────────────────────
    def deck_input(self) -> DeckInput:
        concrete: ElasticIsotropic = self._concrete.currentData()
        steel: ElasticIsotropic = self._steel.currentData()
        return DeckInput(
            rib_height=self._hr.value(),
            pitch=self._pitch.value(),
            rib_bottom=self._wb.value(),
            rib_top=self._wt.value(),
            sheet_thickness=self._t.value(),
            topping=self._topping.value(),
            Ec=concrete.E,
            nu=concrete.nu,
            rho_c=concrete.rho,
            Es=steel.E,
            rho_s=steel.rho,
            ribs_along=self._ribs_along.currentData(),
        )

    def section_name(self) -> str:
        typed = self._name.text().strip()
        if typed:
            return typed
        length = labels_for(self._units).length
        concrete: ElasticIsotropic = self._concrete.currentData()
        total = self._hr.value() + self._topping.value()
        return f"Deck {total:.4g}{length} {concrete.name}"

    def built_deck(self) -> DeckModel | None:
        """What OK adds: the materials and the section (``None`` while the inputs are invalid)."""
        return self._result

    def _refresh(self) -> None:
        if not hasattr(self, "_buttons"):
            return
        ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._preview.clear()
        try:
            deck = self.deck_input()
            result = build_deck_model(
                deck,
                name=self.section_name(),
                first_material_id=self._project.next_material_id(),
                section_id=self._project.next_section_id(),
                units=self._units,
            )
        except ValueError as exc:
            self._result = None
            self._summary.setText("")
            self._message.show_message(str(exc).splitlines()[-1], "error")
            ok_button.setEnabled(False)
            return
        self._result = result
        self._preview.draw_regions([PolygonRegion(tuple(deck_outline(deck)), False)])
        self._preview.draw_centroid(result.properties.centroid, deck.pitch)
        self._preview.fit()
        self._summary.setText(self._describe(result))
        self._message.show_message(
            "The ribs follow each shell's local 1 axis (from its first node to its second) "
            "unless you choose local 2: draw the shells so that edge runs along the ribs. "
            "Stiffness is elastic and uncracked.",
            "info",
        )
        ok_button.setEnabled(True)

    def _describe(self, result: DeckModel) -> str:
        labels = labels_for(self._units)
        length, force = labels.length, labels.force
        p = result.properties
        section = result.section
        weight = section.unit_weight * section.h
        rows = [
            ("", "Along the ribs", "Across the ribs"),
            (
                f"EA [{force}/{length}]",
                f"{p.EA_strong:.4g}",
                f"{p.EA_weak:.4g}",
            ),
            (
                f"EI [{force}·{length}²/{length}]",
                f"{p.EI_strong:.4g}",
                f"{p.EI_weak:.4g}",
            ),
            (
                f"Equivalent membrane thickness [{length}]",
                f"{p.membrane_thickness_strong:.4g}",
                f"{p.membrane_thickness_weak:.4g}",
            ),
            (
                f"Equivalent bending thickness [{length}]",
                f"{p.bending_thickness_strong:.4g}",
                f"{p.bending_thickness_weak:.4g}",
            ),
        ]
        table = (
            "<table cellspacing='6'>"
            + "".join(
                "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
            )
            + "</table>"
        )
        added = ", ".join(f"material #{m.id} {m.name}" for m in result.materials)
        return "<br>".join(
            [
                table,
                f"Bending stiffness ratio EI₁ / EI₂ = <b>{p.stiffness_ratio:.3g}</b>; "
                f"concrete {p.concrete_area:.4g} {length}³/{length}², "
                f"sheet {p.steel_area:.4g} {length}³/{length}²; "
                f"self weight {weight:.4g} {force}/{length}².",
                f"Layered shell h = {section.h:.4g} {length} (face, core, face).",
                f"Adds {added}, section #{section.id} {section.name}.",
            ]
        )
