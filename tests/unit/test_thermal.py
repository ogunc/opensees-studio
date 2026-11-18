"""Temperature loads: fixed-end forces, equivalent loads, and the members they refuse."""

from __future__ import annotations

import json

import numpy as np
import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
    TemperatureLoad,
)
from opensees_studio.core.geometry.frame_options import EndRelease, FrameModifiers, FrameReleases
from opensees_studio.core.selection import loaded_by_pattern
from opensees_studio.core.thermal import (
    ThermalLoadError,
    equivalent_nodal_loads,
    fixed_end_forces,
)

E, A, IZ, IY, ALPHA = 200e9, 0.01, 1e-4, 3e-4, 1.2e-5


def _member(ndm: int = 2, **element: object) -> Project:
    section = ElasticSection(
        id=1, E=E, A=A, Iz=IZ, **({"Iy": IY, "G": 77e9, "J": 1e-4} if ndm == 3 else {})
    )
    return Project(
        ndm=ndm,
        ndf=3 if ndm == 2 else 6,
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(4.0, 0.0, 0.0))],
        sections=[section],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1, **element)],  # type: ignore[arg-type]
    )


def test_uniform_change_is_an_axial_compression_when_held() -> None:
    fe = fixed_end_forces(_member(), TemperatureLoad(element_id=1, alpha=ALPHA, uniform=30.0))
    c = E * A * ALPHA * 30.0
    np.testing.assert_allclose(fe, [c, 0.0, 0.0, -c, 0.0, 0.0])


def test_gradients_give_constant_moments_in_2d_and_3d() -> None:
    g = 100.0
    fe2 = fixed_end_forces(_member(), TemperatureLoad(element_id=1, alpha=ALPHA, gradient_y=g))
    m = E * IZ * ALPHA * g
    np.testing.assert_allclose(fe2, [0.0, 0.0, -m, 0.0, 0.0, m])
    project = _member(3)
    fe3 = fixed_end_forces(
        project, TemperatureLoad(element_id=1, alpha=ALPHA, gradient_y=g, gradient_z=g)
    )
    my = E * IY * ALPHA * g
    assert fe3[5] == pytest.approx(-m) and fe3[11] == pytest.approx(m)
    assert fe3[4] == pytest.approx(my) and fe3[10] == pytest.approx(-my)


def test_modifiers_scale_the_section() -> None:
    project = _member(modifiers=FrameModifiers(area=0.5, i33=0.25))
    fe = fixed_end_forces(
        project, TemperatureLoad(element_id=1, alpha=ALPHA, uniform=10.0, gradient_y=10.0)
    )
    assert fe[0] == pytest.approx(0.5 * E * A * ALPHA * 10.0)
    assert fe[5] == pytest.approx(0.25 * E * IZ * ALPHA * 10.0)


def test_equivalent_loads_are_minus_the_fixed_end_forces_in_global_axes() -> None:
    project = _member()
    load = TemperatureLoad(element_id=1, alpha=ALPHA, uniform=30.0)
    node_i, at_i, node_j, at_j = equivalent_nodal_loads(project, load)
    c = E * A * ALPHA * 30.0
    assert (node_i, node_j) == (1, 2)
    np.testing.assert_allclose(at_i, [-c, 0, 0, 0, 0, 0], atol=1e-6)
    np.testing.assert_allclose(at_j, [c, 0, 0, 0, 0, 0], atol=1e-6)


def test_members_the_method_cannot_take_are_refused() -> None:
    released = FrameReleases(j=EndRelease(released=("M3",)))
    with pytest.raises(ThermalLoadError, match="without end releases"):
        fixed_end_forces(
            _member(releases=released), TemperatureLoad(element_id=1, alpha=ALPHA, uniform=1.0)
        )
    with pytest.raises(ThermalLoadError, match="elastic beam-columns only"):
        fixed_end_forces(_member(), TemperatureLoad(element_id=9, alpha=ALPHA, uniform=1.0))


def test_the_pattern_saves_without_the_field_when_unused_and_selects_its_members() -> None:
    project = _member()
    project.time_series.append(LinearTimeSeries(id=1))
    plain = PlainLoadPattern(id=1, time_series_id=1)
    assert "temperature_loads" not in json.loads(plain.model_dump_json())
    plain.temperature_loads.append(TemperatureLoad(element_id=1, alpha=ALPHA, uniform=5.0))
    project.load_patterns.append(plain)
    assert loaded_by_pattern(project, 1)[1] == {1}
    project.validate_references()
    plain.temperature_loads.append(TemperatureLoad(element_id=7, alpha=ALPHA, uniform=5.0))
    with pytest.raises(ValueError, match="temperature load on missing element 7"):
        project.validate_references()
