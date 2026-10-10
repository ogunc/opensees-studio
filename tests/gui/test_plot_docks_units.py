"""The plot docks convert their values, not just their axis labels.

Time history, hysteresis and response spectrum all read a display unit system:
the plotted series move by the conversion factor and the axes say which unit
they are in. Reference values are exact definitions (1 in = 25.4 mm,
1 kip = 4448.2216152605 N).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from opensees_studio.core import ResponseSpectrum, UnitConverter, UnitSystem
from opensees_studio.services.results import ResponseSpectrumResults, TransientResults
from opensees_studio.services.spectrum import ModeContribution
from opensees_studio.views.docks.hysteresis import HysteresisView
from opensees_studio.views.docks.response_spectrum import ResponseSpectrumView
from opensees_studio.views.docks.time_history import TimeHistoryView

IN_M = 0.0254
KIP_N = 4448.2216152605

TO_MM = UnitConverter(UnitSystem.SI_M_N, UnitSystem.SI_MM_N)
TO_US = UnitConverter(UnitSystem.SI_M_N, UnitSystem.US_IN_KIP)


@pytest.fixture
def transient(tmp_path: Path) -> TransientResults:
    """5-step, ndf=6 histories: node 1 displacement 10, node 100 force 5."""
    import h5py

    h5_path = tmp_path / "case.h5"
    n_steps, ndf = 5, 6
    with h5py.File(h5_path, "w") as f:
        f.create_dataset("time", data=np.linspace(0.0, 0.04, n_steps))
        f.create_dataset("nodes/1/disp", data=np.full((n_steps, ndf), 10.0))
        f.create_dataset("nodes/1/vel", data=np.full((n_steps, ndf), 10.1))
        f.create_dataset("nodes/1/accel", data=np.full((n_steps, ndf), 10.2))
        f.create_dataset("elements/100/forces", data=np.full((n_steps, 12), 5.0))
    return TransientResults(
        case_id=1,
        case_name="t",
        h5_path=h5_path,
        n_steps=n_steps,
        dt=0.01,
        n_steps_requested=n_steps,
    )


def _traces(view):  # type: ignore[no-untyped-def]
    return [it for it in view._plot.listDataItems() if hasattr(it, "getData")]


# ───────────────────────────── time history ─────────────────────────────
@pytest.mark.gui
def test_time_history_plots_the_trace_in_display_units(qtbot, transient) -> None:  # type: ignore[no-untyped-def]
    view = TimeHistoryView()
    qtbot.addWidget(view)
    view.set_results(transient)
    view.set_available_nodes([1, 2])
    view._quantity.setCurrentIndex(view._quantity.findData("disp"))
    view._on_add_trace()

    items = _traces(view)
    assert len(items) == 1
    _t, values = items[0].getData()
    np.testing.assert_allclose(values, 10.0)
    assert "Displacement" in view._plot.getAxis("left").labelText
    assert "[m]" in view._plot.getAxis("left").labelText

    view.set_units(TO_MM)

    items = _traces(view)
    assert len(items) == 1  # the selection survived the redraw
    _t, values = items[0].getData()
    np.testing.assert_allclose(values, 10000.0)
    assert "[mm]" in view._plot.getAxis("left").labelText

    # A velocity is a length per second: same length factor, different exponent.
    view._quantity.setCurrentIndex(view._quantity.findData("vel"))
    view._on_add_trace()
    _t, velocities = _traces(view)[1].getData()
    np.testing.assert_allclose(velocities, 10.1 * 1000.0)
    assert "[mm/s]" in view._plot.getAxis("left").labelText


@pytest.mark.gui
def test_time_history_converts_to_us_customary(qtbot, transient) -> None:  # type: ignore[no-untyped-def]
    view = TimeHistoryView()
    qtbot.addWidget(view)
    view.set_results(transient)
    view.set_available_nodes([1])
    view._on_add_trace()
    view.set_units(TO_US)
    _t, values = _traces(view)[0].getData()
    np.testing.assert_allclose(values, 10.0 / IN_M)
    assert "[in]" in view._plot.getAxis("left").labelText


# ───────────────────────────── hysteresis ─────────────────────────────
@pytest.mark.gui
def test_hysteresis_converts_both_the_displacement_and_the_element_force(  # type: ignore[no-untyped-def]
    qtbot, transient
) -> None:
    view = HysteresisView()
    qtbot.addWidget(view)
    view.set_results(transient)
    view.set_available_nodes([1])
    view.set_available_elements([100])
    view._y_kind.setCurrentIndex(view._y_kind.findData("element_force"))
    view._y_element.setCurrentIndex(0)
    view._y_component.setCurrentIndex(view._y_component.findText("Mz1"))
    view._on_plot()

    xs, ys = _traces(view)[0].getData()
    np.testing.assert_allclose(xs, 10.0)
    np.testing.assert_allclose(ys, 5.0)
    assert "Mz1 [N·m]" in view._plot.getAxis("left").labelText  # the identity system

    view.set_units(TO_US)

    xs, ys = _traces(view)[0].getData()
    np.testing.assert_allclose(xs, 10.0 / IN_M)  # X is always a displacement
    np.testing.assert_allclose(ys, 5.0 / KIP_N / IN_M)  # Mz1 is a moment
    assert "[in]" in view._plot.getAxis("bottom").labelText
    assert "[kip·in]" in view._plot.getAxis("left").labelText


@pytest.mark.gui
def test_hysteresis_converts_a_nodal_acceleration_as_a_length(qtbot, transient) -> None:  # type: ignore[no-untyped-def]
    view = HysteresisView()
    qtbot.addWidget(view)
    view.set_results(transient)
    view.set_available_nodes([1])
    view._y_kind.setCurrentIndex(view._y_kind.findData("node_accel"))
    view._on_plot()
    view.set_units(TO_MM)
    _x, ys = _traces(view)[0].getData()
    np.testing.assert_allclose(ys, 10.2 * 1000.0)
    assert "[mm/s^2]" in view._plot.getAxis("left").labelText


# ───────────────────────────── response spectrum ─────────────────────────────
def _spectrum_results() -> ResponseSpectrumResults:
    return ResponseSpectrumResults(
        case_id=1,
        case_name="rs",
        direction=1,
        combination="CQC",
        combined_disp={1: np.array([0.02, 0.0, 0.0])},
        modes=[
            ModeContribution(
                mode_number=1,
                period=1.0,
                frequency=1.0,
                angular_frequency=2.0 * np.pi,
                participation_factor=1.0,
                effective_mass=1.0,
                mass_ratio=1.0,
                sa_at_period=0.5,
            )
        ],
    )


def _spectrum() -> ResponseSpectrum:
    return ResponseSpectrum(
        id=1,
        name="code",
        periods=[0.01, 1.0, 2.0],
        accelerations=[0.4, 0.5, 0.2],
    )


@pytest.mark.gui
def test_response_spectrum_converts_sa_and_labels_the_axis(qtbot) -> None:  # type: ignore[no-untyped-def]
    view = ResponseSpectrumView()
    qtbot.addWidget(view)
    view.set_results(_spectrum_results(), _spectrum())
    assert "[m/s²]" in view._plot.getAxis("left").labelText

    view.set_units(TO_US)

    assert "[in/s²]" in view._plot.getAxis("left").labelText
    # The dense curve and the control points both convert.
    items = _traces(view)
    _p, a = items[0].getData()
    assert max(a) == pytest.approx(0.5 / IN_M, rel=0.01)  # dense curve, interpolated
    _p, control = items[1].getData()
    np.testing.assert_allclose(control, np.array([0.4, 0.5, 0.2]) / IN_M)
    # The marker sits on the converted Sa, and the table cell follows it.
    values = [view._table.item(0, col).text() for col in range(view._table.columnCount())]
    assert values[-1] == f"{0.5 / IN_M:.4g}"
    assert view._table.horizontalHeaderItem(6).text() == "Sa(T) [in/s²]"
