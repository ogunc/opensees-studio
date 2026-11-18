"""Define → Concrete Creep & Shrinkage (fib MC2010): a TDConcreteMC10 material from the mix.

Enter the mean strength, the exposure and the cement; the window shows the
Model Code's creep coefficient and shrinkage at a few ages, and OK adds the
``TDConcreteMC10`` material (stresses in the project's unit) for fibre
sections and bars of a time-dependent staged construction case.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.materials.library import TDConcreteMC10
from opensees_studio.core.mc2010 import Mc2010Concrete, tdconcrete_material
from opensees_studio.core.units import UnitSystem, stress_scale
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

AGES = (90.0, 365.0, 3650.0, 18250.0)


class Mc2010ConcreteDialog(FittedDialog):
    """The mix and exposure, a preview of phi and eps_cs, and the material OK adds."""

    def __init__(self, project: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Concrete Creep & Shrinkage (fib MC2010)")
        self.setProperty(TOPIC_PROPERTY, "define.mc2010")
        self._project = project
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._name = QLineEdit("Concrete (MC2010)")
        form.addRow("Name:", self._name)
        self._fcm = self._field(38.0, 5.0, 150.0)
        form.addRow("Mean strength fcm [MPa]:", self._fcm)
        self._rh = self._field(70.0, 40.0, 99.0)
        form.addRow("Relative humidity [%]:", self._rh)
        self._h0 = self._field(200.0, 10.0, 5000.0)
        form.addRow("Notional size h0 = 2Ac/u [mm]:", self._h0)
        self._cement = QComboBox()
        self._cement.addItems(["32.5N", "32.5R/42.5N", "42.5R/52.5N/R"])
        self._cement.setCurrentIndex(1)
        self._cement.currentIndexChanged.connect(self._refresh)
        form.addRow("Cement class:", self._cement)
        self._drying = self._field(7.0, 0.5, 365.0)
        form.addRow("Drying starts at age [days]:", self._drying)
        self._cast = self._field(0.0, 0.0, 1e5)
        form.addRow("Cast at analysis time [days]:", self._cast)
        self._t0 = self._field(28.0, 2.0, 1e5)
        form.addRow("Preview: loaded at age [days]:", self._t0)
        layout.addLayout(form)
        self._preview = QLabel()
        self._preview.setWordWrap(True)
        layout.addWidget(self._preview)
        self._message = MessageArea()
        layout.addWidget(self._message)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._refresh()

    def _field(self, value: float, low: float, high: float) -> FloatField:
        field = FloatField()
        field.setRange(low, high)
        field.setValue(value)
        field.valueChanged.connect(self._refresh)
        return field

    def mix(self) -> Mc2010Concrete:
        return Mc2010Concrete(
            fcm=self._fcm.value(),
            relative_humidity=self._rh.value(),
            h0=self._h0.value(),
            cement=self._cement.currentText(),  # type: ignore[arg-type]
            drying_start=self._drying.value(),
        )

    def material(self) -> TDConcreteMC10:
        units = self._project.meta.units
        return tdconcrete_material(
            self.mix(),
            self._project.next_material_id(),
            name=self._name.text().strip(),
            stress_scale=stress_scale(UnitSystem.SI_MM_N, units),
            cast_time=self._cast.value(),
        )

    def _refresh(self) -> None:
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        try:
            mix = self.mix()
        except ValueError as exc:
            self._message.show_message(str(exc), "error")
            ok.setEnabled(False)
            return
        t0 = self._t0.value()
        rows = [
            f"age {t:g} d: φ = {mix.creep_coefficient(t, t0):.3f}, "
            f"εcs = {mix.shrinkage(t) * 1e6:.0f} µε"
            for t in AGES
            if t > t0
        ]
        self._preview.setText(
            f"Eci = {mix.elastic_modulus:.0f} MPa, fctm = {mix.tensile_strength:.2f} MPa.<br>"
            + "<br>".join(rows)
        )
        self._message.show_message(
            "Creep and shrinkage advance only in a staged construction case marked "
            "time-dependent, whose time is the concrete age in days.",
            "info",
        )
        ok.setEnabled(True)
