"""Pushover curve axis labels must follow the project's unit system."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import UnitSystem  # noqa: E402
from opensees_studio.services.results import PushoverResults  # noqa: E402
from opensees_studio.views.docks.pushover_curve import (  # noqa: E402
    PushoverCurveView,
    _is_rotation_dof,
)


def _pushover(control_dof: int = 1) -> PushoverResults:
    return PushoverResults(
        case_id=1, case_name="tst", n_steps=5,
        control_node=2, control_dof=control_dof,
        control_disp=np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0]),
        base_shear=np.array([0.0, 100.0, 200.0, 300.0, 400.0, 500.0]),
    )


def test_is_rotation_dof_ndf3() -> None:
    """In a 2D/ndf=3 model, only DOF 3 is rotational."""
    assert _is_rotation_dof(1, ndf=3) is False
    assert _is_rotation_dof(2, ndf=3) is False
    assert _is_rotation_dof(3, ndf=3) is True


def test_is_rotation_dof_ndf6() -> None:
    """In a 3D/ndf=6 model, DOFs 4, 5, 6 are rotational."""
    assert _is_rotation_dof(1, ndf=6) is False
    assert _is_rotation_dof(3, ndf=6) is False      # Uz in 3D
    assert _is_rotation_dof(4, ndf=6) is True       # Rx
    assert _is_rotation_dof(5, ndf=6) is True       # Ry
    assert _is_rotation_dof(6, ndf=6) is True       # Rz


@pytest.mark.gui
def test_si_translation_labels(qtbot) -> None:  # type: ignore[no-untyped-def]
    v = PushoverCurveView(units=UnitSystem.SI_M_N, ndf=6)
    qtbot.addWidget(v)
    v.set_results(_pushover(control_dof=1))
    assert "m" in v._plot.getAxis("bottom").labelText
    assert "Displacement" in v._plot.getAxis("bottom").labelText
    assert "N" in v._plot.getAxis("left").labelText
    assert "Base shear" in v._plot.getAxis("left").labelText


@pytest.mark.gui
def test_si_rotation_labels_show_curvature_and_moment(qtbot) -> None:  # type: ignore[no-untyped-def]
    v = PushoverCurveView(units=UnitSystem.SI_M_N, ndf=3)
    qtbot.addWidget(v)
    v.set_results(_pushover(control_dof=3))
    assert "1/m" in v._plot.getAxis("bottom").labelText
    assert "Curvature" in v._plot.getAxis("bottom").labelText
    assert "N·m" in v._plot.getAxis("left").labelText
    assert "Moment" in v._plot.getAxis("left").labelText


@pytest.mark.gui
def test_us_in_kip_rotation_labels(qtbot) -> None:  # type: ignore[no-untyped-def]
    """kip-in Moment-Curvature project must NOT show cm / kN anywhere."""
    v = PushoverCurveView(units=UnitSystem.US_IN_KIP, ndf=3)
    qtbot.addWidget(v)
    v.set_results(_pushover(control_dof=3))
    x_label = v._plot.getAxis("bottom").labelText
    y_label = v._plot.getAxis("left").labelText
    assert "1/in" in x_label
    assert "kip·in" in y_label
    assert "cm" not in x_label
    assert "kN" not in y_label


@pytest.mark.gui
def test_us_in_kip_translation_labels(qtbot) -> None:  # type: ignore[no-untyped-def]
    v = PushoverCurveView(units=UnitSystem.US_IN_KIP, ndf=3)
    qtbot.addWidget(v)
    v.set_results(_pushover(control_dof=1))
    assert "in" in v._plot.getAxis("bottom").labelText
    assert "kip" in v._plot.getAxis("left").labelText


@pytest.mark.gui
def test_no_auto_scaling_applied_to_values(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Regression: earlier versions divided base_shear by 1000 to
    display kN. The values must now be drawn exactly as stored so
    kip-in users don't see nonsense scaling."""
    v = PushoverCurveView(units=UnitSystem.US_IN_KIP, ndf=3)
    qtbot.addWidget(v)
    r = _pushover(control_dof=3)
    v.set_results(r)
    # Take the single line item that was added; the item's data
    # should match the input arrays point-for-point.
    items = [it for it in v._plot.listDataItems()
             if hasattr(it, "getData")]
    assert items, "Pushover curve has no plot items"
    xs, ys = items[0].getData()
    # The first line item is the actual data (reference line is second).
    np.testing.assert_allclose(xs, r.control_disp)
    np.testing.assert_allclose(ys, r.base_shear)
