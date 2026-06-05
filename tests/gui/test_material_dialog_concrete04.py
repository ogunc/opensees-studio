"""GUI tests for the Concrete04 material form."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import Concrete04  # noqa: E402
from opensees_studio.views.dialogs.material_forms import (  # noqa: E402
    Concrete04Form,
    FORM_REGISTRY,
)


@pytest.mark.gui
def test_concrete04_in_registry(qtbot) -> None:  # type: ignore[no-untyped-def]
    assert "Concrete04" in FORM_REGISTRY
    assert FORM_REGISTRY["Concrete04"] is Concrete04Form


@pytest.mark.gui
def test_concrete04_form_constructs(qtbot) -> None:  # type: ignore[no-untyped-def]
    form = Concrete04Form()
    qtbot.addWidget(form)
    assert form.type_label == "Concrete04 — Popovics concrete (optional tension)"


@pytest.mark.gui
def test_concrete04_read_no_tension(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Fill the form and read back a Concrete04 model (no tension branch)."""
    form = Concrete04Form()
    qtbot.addWidget(form)

    form._name_edit.setText("C30")
    form._fpc.setValue(-30e6)
    form._epsc0.setValue(-0.002)
    form._epscu.setValue(-0.005)
    form._Ec.setValue(30e9)
    form._fct.setValue(0.0)   # 0 → no tension
    form._et.setValue(0.0)
    form._material_id = 1

    mat = form.read()
    assert isinstance(mat, Concrete04)
    assert mat.id == 1
    assert mat.name == "C30"
    assert mat.fpc == pytest.approx(-30e6)
    assert mat.epsc0 == pytest.approx(-0.002)
    assert mat.epscu == pytest.approx(-0.005)
    assert mat.Ec == pytest.approx(30e9)
    assert mat.fct is None
    assert mat.et is None


@pytest.mark.gui
def test_concrete04_read_with_tension(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Form with positive fct + et produces the tensile-branch model."""
    form = Concrete04Form()
    qtbot.addWidget(form)

    form._fpc.setValue(-30e6)
    form._epsc0.setValue(-0.002)
    form._epscu.setValue(-0.005)
    form._Ec.setValue(30e9)
    form._fct.setValue(3.0e6)
    form._et.setValue(1e-4)
    form._material_id = 2

    mat = form.read()
    assert isinstance(mat, Concrete04)
    assert mat.fct == pytest.approx(3.0e6)
    assert mat.et == pytest.approx(1e-4)


@pytest.mark.gui
def test_concrete04_populate_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    """populate(mat) + read() reproduces the original model object."""
    original = Concrete04(
        id=3, name="C40-Tension",
        fpc=-40e6, epsc0=-0.0022, epscu=-0.006, Ec=32e9,
        fct=2.5e6, et=8e-5,
    )

    form = Concrete04Form()
    qtbot.addWidget(form)
    form.populate(original)

    recovered = form.read()
    assert recovered.id == original.id
    assert recovered.name == original.name
    assert recovered.fpc == pytest.approx(original.fpc)
    assert recovered.epsc0 == pytest.approx(original.epsc0)
    assert recovered.epscu == pytest.approx(original.epscu)
    assert recovered.Ec == pytest.approx(original.Ec)
    assert recovered.fct == pytest.approx(original.fct)
    assert recovered.et == pytest.approx(original.et)


@pytest.mark.gui
def test_concrete04_accepts_ksi_values(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Form must not clamp US-customary (ksi) values for fpc."""
    form = Concrete04Form()
    qtbot.addWidget(form)
    form._fpc.setValue(-6.0)        # ksi
    form._Ec.setValue(3600.0)       # ksi
    assert form._fpc.value() == pytest.approx(-6.0)
    assert form._Ec.value() == pytest.approx(3600.0)


@pytest.mark.gui
def test_concrete04_spinboxes_use_c_locale(qtbot) -> None:  # type: ignore[no-untyped-def]
    form = Concrete04Form()
    qtbot.addWidget(form)
    assert form._epsc0.locale().decimalPoint() == "."
    assert form._fpc.locale().decimalPoint() == "."
