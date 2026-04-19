"""Material parameter forms.

For each Material subclass, a small ``QWidget`` exposing its parameters.
Forms expose ``read()`` which returns a fully-validated material instance
(or raises ``ValidationError``) and ``populate(material)`` to fill in
fields when editing an existing one.

Adding a new material type to the project = (a) define it in core, (b)
add a form here, (c) register it in :data:`FORM_REGISTRY` below.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QWidget,
)

from opensees_studio.core import (
    Concrete01,
    Concrete02,
    ElasticIsotropic,
    ElasticPP,
    ElasticUniaxial,
    Steel01,
    Steel02,
)


# ─────────────────────────── helpers ───────────────────────────
def _spin(default: float = 0.0, *, decimals: int = 6,
          minimum: float = -1e15, maximum: float = 1e15,
          step: float = 1.0) -> QDoubleSpinBox:
    from PySide6.QtCore import QLocale
    sb = QDoubleSpinBox()
    # Force C locale so "." is always the decimal separator.
    sb.setLocale(QLocale(QLocale.Language.C))
    # Disable keyboardTracking so partial-typing values don't clamp
    # while the user is still mid-keystroke. Without this, typing
    # "-0.004" into a box with range [-1.0, -1e-6] clamps the
    # intermediate "-0" (= 0.0) to the max -1e-6 and the subsequent
    # zero digits get appended to the clamped text instead of
    # forming the number the user meant. Value commits on Enter /
    # focus-out / arrow step.
    sb.setKeyboardTracking(False)
    sb.setRange(minimum, maximum)
    sb.setDecimals(decimals)
    sb.setSingleStep(step)
    sb.setValue(default)
    return sb


# ─────────────────────────── base ───────────────────────────
class MaterialFormBase(QWidget):
    """Common name field + concrete-class subclasses fill the rest."""

    type_label: str = "Material"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._material_id: int | None = None
        self._layout = QFormLayout(self)
        self._name_edit = QLineEdit()
        self._layout.addRow("Name:", self._name_edit)

    def populate(self, material: Any) -> None:
        """Fill the form fields from an existing material (used in edit mode)."""
        self._material_id = material.id
        self._name_edit.setText(material.name)
        self._populate_specific(material)

    def _populate_specific(self, material: Any) -> None: ...

    def read(self, material_id: int | None = None) -> Any:
        """Return a validated Material instance built from current field values."""
        mid = self._material_id if self._material_id is not None else material_id
        if mid is None:
            raise ValueError("Material id required.")
        return self._read_specific(mid)

    def _read_specific(self, material_id: int) -> Any:
        raise NotImplementedError


# ─────────────────────────── Steel01 ───────────────────────────
class Steel01Form(MaterialFormBase):
    type_label = "Steel01 — bilinear with kinematic hardening"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Unit-agnostic: type any positive value directly. Arrow keys
        # step by 1.0 so kip-in users (Fy ≈ 60) get useful increments;
        # SI-Pa users (Fy ≈ 4e8) still type directly.
        self._fy = _spin(420e6, step=1.0, minimum=1e-9)
        self._e0 = _spin(200e9, step=1.0, minimum=1e-9)
        self._b = _spin(0.01, decimals=4, minimum=0.0, maximum=1.0, step=0.01)
        self._layout.addRow("Fy:", self._fy)
        self._layout.addRow("E0:", self._e0)
        self._layout.addRow("b (hardening ratio):", self._b)

    def _populate_specific(self, m: Steel01) -> None:
        self._fy.setValue(m.Fy)
        self._e0.setValue(m.E0)
        self._b.setValue(m.b)

    def _read_specific(self, mid: int) -> Steel01:
        return Steel01(
            id=mid, name=self._name_edit.text(),
            Fy=self._fy.value(), E0=self._e0.value(), b=self._b.value(),
        )


# ─────────────────────────── Steel02 ───────────────────────────
class Steel02Form(MaterialFormBase):
    type_label = "Steel02 — Giuffré-Menegotto-Pinto"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fy = _spin(355e6, step=1.0, minimum=1e-9)
        self._e0 = _spin(200e9, step=1.0, minimum=1e-9)
        self._b = _spin(0.005, decimals=4, minimum=0.0, maximum=1.0, step=0.001)
        self._r0 = _spin(18.0, decimals=2, minimum=10.0, maximum=20.0, step=0.5)
        self._cR1 = _spin(0.925, decimals=4, step=0.01)
        self._cR2 = _spin(0.15, decimals=4, step=0.01)
        for label, w in (("Fy:", self._fy), ("E0:", self._e0), ("b:", self._b),
                         ("R0:", self._r0), ("cR1:", self._cR1), ("cR2:", self._cR2)):
            self._layout.addRow(label, w)

    def _populate_specific(self, m: Steel02) -> None:
        self._fy.setValue(m.Fy); self._e0.setValue(m.E0); self._b.setValue(m.b)
        self._r0.setValue(m.R0); self._cR1.setValue(m.cR1); self._cR2.setValue(m.cR2)

    def _read_specific(self, mid: int) -> Steel02:
        return Steel02(
            id=mid, name=self._name_edit.text(),
            Fy=self._fy.value(), E0=self._e0.value(), b=self._b.value(),
            R0=self._r0.value(), cR1=self._cR1.value(), cR2=self._cR2.value(),
        )


# ─────────────────────────── Concrete01 ───────────────────────────
class Concrete01Form(MaterialFormBase):
    type_label = "Concrete01 — Kent-Scott-Park, no tension"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # f'c, f'cu: any non-zero negative value. The old -1e3 max
        # assumed SI-Pa and locked out kip-in users who wanted
        # values like -6 ksi; -1e-6 leaves the full unit range open.
        self._fpc = _spin(-30e6, step=1.0, maximum=0.0)
        self._epsc0 = _spin(-0.002, decimals=6, minimum=-1.0, maximum=0.0, step=1e-4)
        self._fpcu = _spin(-15e6, step=1.0, maximum=0.0)
        self._epsU = _spin(-0.005, decimals=6, minimum=-1.0, maximum=0.0, step=1e-4)
        for label, w in (("f'c (-):", self._fpc), ("ε_c0 (-):", self._epsc0),
                         ("f'cu (-):", self._fpcu), ("ε_U (-):", self._epsU)):
            self._layout.addRow(label, w)

    def _populate_specific(self, m: Concrete01) -> None:
        self._fpc.setValue(m.fpc); self._epsc0.setValue(m.epsc0)
        self._fpcu.setValue(m.fpcu); self._epsU.setValue(m.epsU)

    def _read_specific(self, mid: int) -> Concrete01:
        return Concrete01(
            id=mid, name=self._name_edit.text(),
            fpc=self._fpc.value(), epsc0=self._epsc0.value(),
            fpcu=self._fpcu.value(), epsU=self._epsU.value(),
        )


# ─────────────────────────── Concrete02 ───────────────────────────
class Concrete02Form(MaterialFormBase):
    type_label = "Concrete02 — Kent-Scott-Park with linear tension"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Same range fix as Concrete01 — permissive so kip-in values
        # like -6 aren't clamped by a hard-coded SI-Pa maximum.
        self._fpc = _spin(-30e6, step=1.0, maximum=0.0)
        self._epsc0 = _spin(-0.002, decimals=6, minimum=-1.0, maximum=0.0, step=1e-4)
        self._fpcu = _spin(-15e6, step=1.0, maximum=0.0)
        self._epsU = _spin(-0.005, decimals=6, minimum=-1.0, maximum=0.0, step=1e-4)
        self._lambda = _spin(0.1, decimals=4, minimum=0.0, maximum=1.0, step=0.01)
        self._ft = _spin(3e6, step=1.0, minimum=1e-9)
        self._ets = _spin(2e9, step=1.0, minimum=1e-9)
        for label, w in (("f'c (-):", self._fpc), ("ε_c0 (-):", self._epsc0),
                         ("f'cu (-):", self._fpcu), ("ε_U (-):", self._epsU),
                         ("λ (unload ratio):", self._lambda),
                         ("ft (tensile):", self._ft), ("Ets (soften):", self._ets)):
            self._layout.addRow(label, w)

    def _populate_specific(self, m: Concrete02) -> None:
        self._fpc.setValue(m.fpc); self._epsc0.setValue(m.epsc0)
        self._fpcu.setValue(m.fpcu); self._epsU.setValue(m.epsU)
        self._lambda.setValue(m.lambda_); self._ft.setValue(m.ft); self._ets.setValue(m.Ets)

    def _read_specific(self, mid: int) -> Concrete02:
        return Concrete02(
            id=mid, name=self._name_edit.text(),
            fpc=self._fpc.value(), epsc0=self._epsc0.value(),
            fpcu=self._fpcu.value(), epsU=self._epsU.value(),
            ft=self._ft.value(), Ets=self._ets.value(),
            **{"lambda": self._lambda.value()},
        )


# ─────────────────────────── ElasticUniaxial ───────────────────────────
class ElasticUniaxialForm(MaterialFormBase):
    type_label = "Elastic (uniaxial)"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._e = _spin(200e9, step=1.0, minimum=1e-9)
        self._eta = _spin(0.0, decimals=4)
        self._layout.addRow("E:", self._e)
        self._layout.addRow("η (damping):", self._eta)

    def _populate_specific(self, m: ElasticUniaxial) -> None:
        self._e.setValue(m.E); self._eta.setValue(m.eta)

    def _read_specific(self, mid: int) -> ElasticUniaxial:
        return ElasticUniaxial(
            id=mid, name=self._name_edit.text(),
            E=self._e.value(), eta=self._eta.value(),
        )


# ─────────────────────────── ElasticIsotropic ───────────────────────────
class ElasticIsotropicForm(MaterialFormBase):
    type_label = "Elastic Isotropic (3D)"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._e = _spin(200e9, step=1.0, minimum=1e-9)
        self._nu = _spin(0.3, decimals=4, minimum=-1.0, maximum=0.5, step=0.01)
        self._rho = _spin(7850.0, decimals=2, minimum=0.0, step=100.0)
        self._layout.addRow("E:", self._e)
        self._layout.addRow("ν (Poisson):", self._nu)
        self._layout.addRow("ρ (density):", self._rho)

    def _populate_specific(self, m: ElasticIsotropic) -> None:
        self._e.setValue(m.E); self._nu.setValue(m.nu); self._rho.setValue(m.rho)

    def _read_specific(self, mid: int) -> ElasticIsotropic:
        return ElasticIsotropic(
            id=mid, name=self._name_edit.text(),
            E=self._e.value(), nu=self._nu.value(), rho=self._rho.value(),
        )


# ─────────────────────────── ElasticPP ───────────────────────────
class ElasticPPForm(MaterialFormBase):
    type_label = "Elastic-Perfectly-Plastic"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._e = _spin(200e9, step=1.0, minimum=1e-9)
        self._epsy = _spin(0.002, decimals=6, minimum=1e-6, step=1e-4)
        self._layout.addRow("E:", self._e)
        self._layout.addRow("ε_y (yield strain):", self._epsy)

    def _populate_specific(self, m: ElasticPP) -> None:
        self._e.setValue(m.E); self._epsy.setValue(m.epsy_pos)

    def _read_specific(self, mid: int) -> ElasticPP:
        return ElasticPP(
            id=mid, name=self._name_edit.text(),
            E=self._e.value(), epsy_pos=self._epsy.value(),
        )


# ─────────────────────────── registry ───────────────────────────
#: Maps a "type" key (matches the Pydantic discriminator) to a form class.
FORM_REGISTRY: dict[str, type[MaterialFormBase]] = {
    "Steel01": Steel01Form,
    "Steel02": Steel02Form,
    "Concrete01": Concrete01Form,
    "Concrete02": Concrete02Form,
    "Elastic": ElasticUniaxialForm,
    "ElasticIsotropic": ElasticIsotropicForm,
    "ElasticPP": ElasticPPForm,
}


def form_for(material: Any) -> MaterialFormBase:
    """Return a form instance pre-populated for ``material``."""
    cls = FORM_REGISTRY[material.type]
    form = cls()
    form.populate(material)
    return form
