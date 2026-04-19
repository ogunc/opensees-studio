"""Material form spin-box ranges must accept any consistent unit system.

Regression: the old Concrete01 form capped ``fpc`` at -1e3 (Pa),
silently clamping kip-in / ksi users' ``-6`` input to ``-1000``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.views.dialogs.material_forms import (  # noqa: E402
    Concrete01Form,
    Concrete02Form,
    Steel01Form,
    Steel02Form,
)


@pytest.mark.gui
def test_concrete01_accepts_ksi_values(qtbot) -> None:  # type: ignore[no-untyped-def]
    """User types -6 (ksi) → spinbox stores -6, not clamped to -1000."""
    form = Concrete01Form()
    qtbot.addWidget(form)
    form._fpc.setValue(-6.0)
    form._epsc0.setValue(-0.004)
    form._fpcu.setValue(-5.0)
    form._epsU.setValue(-0.014)

    assert form._fpc.value() == pytest.approx(-6.0)
    assert form._epsc0.value() == pytest.approx(-0.004)
    assert form._fpcu.value() == pytest.approx(-5.0)
    assert form._epsU.value() == pytest.approx(-0.014)


@pytest.mark.gui
def test_concrete01_still_accepts_si_pa_values(qtbot) -> None:  # type: ignore[no-untyped-def]
    form = Concrete01Form()
    qtbot.addWidget(form)
    form._fpc.setValue(-30e6)
    form._fpcu.setValue(-5e6)
    assert form._fpc.value() == pytest.approx(-30e6)
    assert form._fpcu.value() == pytest.approx(-5e6)


@pytest.mark.gui
def test_concrete02_accepts_ksi_values(qtbot) -> None:  # type: ignore[no-untyped-def]
    form = Concrete02Form()
    qtbot.addWidget(form)
    form._fpc.setValue(-6.0)
    form._fpcu.setValue(-5.0)
    form._ft.setValue(0.6)          # ksi tensile strength
    assert form._fpc.value() == pytest.approx(-6.0)
    assert form._fpcu.value() == pytest.approx(-5.0)
    assert form._ft.value() == pytest.approx(0.6)


@pytest.mark.gui
def test_steel01_accepts_ksi_values(qtbot) -> None:  # type: ignore[no-untyped-def]
    form = Steel01Form()
    qtbot.addWidget(form)
    form._fy.setValue(60.0)         # ksi
    form._e0.setValue(30000.0)      # ksi
    form._b.setValue(0.01)
    assert form._fy.value() == pytest.approx(60.0)
    assert form._e0.value() == pytest.approx(30000.0)


@pytest.mark.gui
def test_steel02_accepts_ksi_values(qtbot) -> None:  # type: ignore[no-untyped-def]
    form = Steel02Form()
    qtbot.addWidget(form)
    form._fy.setValue(60.0)
    form._e0.setValue(30000.0)
    assert form._fy.value() == pytest.approx(60.0)
    assert form._e0.value() == pytest.approx(30000.0)


@pytest.mark.gui
def test_concrete01_round_trip_preserves_ksi_values(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Form → Concrete01 model → form round-trip keeps ksi values intact."""
    form = Concrete01Form()
    qtbot.addWidget(form)
    form._fpc.setValue(-6.0)
    form._epsc0.setValue(-0.004)
    form._fpcu.setValue(-5.0)
    form._epsU.setValue(-0.014)
    form._name_edit.setText("Core-Conc")
    form._material_id = 1
    mat = form.read()
    assert mat.fpc == pytest.approx(-6.0)
    assert mat.epsc0 == pytest.approx(-0.004)
    assert mat.fpcu == pytest.approx(-5.0)
    assert mat.epsU == pytest.approx(-0.014)
    # Round-trip through a fresh form.
    form2 = Concrete01Form()
    qtbot.addWidget(form2)
    form2.populate(mat)
    assert form2._fpc.value() == pytest.approx(-6.0)
    assert form2._fpcu.value() == pytest.approx(-5.0)
