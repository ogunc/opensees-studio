"""GroundMotionCatalogViewModel: generated inputs (Qt-free)."""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import (
    PathTimeSeries,
    Project,
    ProjectMeta,
    TrigTimeSeries,
    UnitSystem,
    gravity,
)
from opensees_studio.viewmodels.ground_motion_catalog_vm import GroundMotionCatalogViewModel


def _vm(units: UnitSystem = UnitSystem.SI_M_N) -> tuple[Project, GroundMotionCatalogViewModel]:
    project = Project(meta=ProjectMeta(units=units))
    return project, GroundMotionCatalogViewModel(project)


def test_plain_sine_in_g_becomes_trig_with_g_in_factor() -> None:
    project, vm = _vm(UnitSystem.US_IN_KIP)
    ts = vm.build_generated_series(
        {
            "kind": "sine",
            "amplitude": 0.5,
            "frequency": 2.0,
            "duration": 6.0,
            "dt": 0.01,
            "units": "g",
        }
    )
    assert isinstance(ts, TrigTimeSeries)
    assert ts.id == 1
    assert ts.factor == pytest.approx(0.5 * gravity(UnitSystem.US_IN_KIP))
    assert ts.period == pytest.approx(0.5)
    assert ts.t_end == 6.0
    assert ts.generator["units"] == "g"
    assert ts.name == "sine 2 Hz 0.5 g"
    project.time_series.append(ts)
    assert vm.generated_series() == [ts]
    assert vm.generator_descriptor_of(ts)["amplitude"] == 0.5


def test_ramped_sine_and_beat_become_generated_path_series() -> None:
    project, vm = _vm()
    ramped = vm.build_generated_series(
        {
            "kind": "sine",
            "amplitude": 1.0,
            "frequency": 1.0,
            "duration": 10.0,
            "dt": 0.01,
            "ramp_in_cycles": 1.0,
            "ramp_out_cycles": 0.0,
            "units": "project",
        },
        name="Ramped",
    )
    assert isinstance(ramped, PathTimeSeries)
    assert ramped.factor == 1.0 and ramped.file_path == "generated:sine"
    assert ramped.name == "Ramped"
    beat = vm.build_generated_series(
        {
            "kind": "sine-beat",
            "amplitude": 0.2,
            "frequency": 4.0,
            "cycles_per_beat": 10,
            "n_beats": 5,
            "pause": 2.0,
            "dt": 0.005,
            "units": "g",
        },
        series_id=9,
    )
    assert isinstance(beat, PathTimeSeries) and beat.id == 9
    assert beat.factor == pytest.approx(gravity(UnitSystem.SI_M_N))
    assert len(beat.values) == 5 * 500 + 4 * 400 + 1
    project.time_series.extend([ramped, beat])
    assert [ts.id for ts in vm.generated_series()] == [1, 9]
    # a hand-made Path series is not a generated input
    project.time_series.append(PathTimeSeries(id=3, dt=0.01, values=[0.0, 1.0]))
    assert [ts.id for ts in vm.generated_series()] == [1, 9]
    assert vm.generator_descriptor_of(project.time_series[-1]) is None


def test_generated_spectrum_is_in_g_whatever_the_amplitude_unit() -> None:
    _, vm = _vm(UnitSystem.SI_M_N)
    base = {"kind": "sine", "frequency": 1.0, "duration": 20.0, "dt": 0.005}
    in_g = vm.generated_spectrum({**base, "amplitude": 0.1, "units": "g"})
    in_si = vm.generated_spectrum({**base, "amplitude": 0.1 * 9.80665, "units": "project"})
    assert np.allclose(in_g.sa, in_si.sa, rtol=1e-9)
    assert float(in_g.sa[0]) == pytest.approx(0.1, rel=2e-2)  # short period: Sa = PGA


def test_bad_units_and_unknown_kind_are_refused() -> None:
    _, vm = _vm()
    with pytest.raises(ValueError, match="units"):
        vm.build_generated_series(
            {"kind": "sine", "amplitude": 1.0, "frequency": 1.0, "duration": 1.0, "dt": 0.01}
        )
    with pytest.raises(ValueError, match="Unknown generator kind"):
        vm.build_generated_series({"kind": "noise", "amplitude": 1.0, "units": "g"})
