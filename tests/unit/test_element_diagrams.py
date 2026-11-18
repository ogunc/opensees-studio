"""Per-element diagram data used by the right-click element window."""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import (
    ConstantTimeSeries,
    ElasticBeamColumn,
    ElasticSection,
    ElasticUniaxial,
    LinearTimeSeries,
    LoadCombination,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    StaticCase,
    TrussElement,
    UniformElementLoad,
)
from opensees_studio.services.element_diagrams import (
    combine_element_bundles,
    element_applied_loads,
    element_deformation_curves,
    element_diagram_bundle,
    element_force_curves,
)
from opensees_studio.services.element_forces import ForceComponent
from opensees_studio.services.results import StaticResults


def _section() -> ElasticSection:
    return ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6)


def _frame_2d() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(4.0, 0.0, 0.0)),
        ],
        sections=[_section()],
        elements=[ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1)],
        time_series=[ConstantTimeSeries(id=1, factor=2.0)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=10, wy=-5.0)],
                point_loads=[PointElementLoad(element_id=10, x=0.25, py=-3.0)],
            )
        ],
        analyses=[StaticCase(id=1, name="case", n_steps=1, pattern_ids=[1])],
    )


def _frame_3d() -> Project:
    return Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(4.0, 0.0, 0.0)),
        ],
        sections=[_section()],
        elements=[ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1)],
    )


def _forces_2d() -> StaticResults:
    return StaticResults(
        case_id=1,
        case_name="case",
        n_steps=1,
        element_forces={10: np.array([[100.0, 5.0, 9.0, -100.0, -5.0, -9.0]])},
    )


def test_a_2d_member_reports_axial_shear_and_in_plane_moment() -> None:
    series = element_force_curves(_frame_2d(), _forces_2d(), 10, stations=False)

    assert [item.component for item in series] == [
        ForceComponent.N,
        ForceComponent.V2,
        ForceComponent.M3,
    ]
    np.testing.assert_allclose(series[0].x, [0.0, 4.0])
    np.testing.assert_allclose(series[0].values, [100.0, 100.0])
    np.testing.assert_allclose(series[1].values, [5.0, 5.0])
    np.testing.assert_allclose(series[2].values, [9.0, 9.0])


def test_a_3d_member_reports_all_six_components() -> None:
    forces = np.array([[100.0, 5.0, 7.0, 1.0, 8.0, 9.0, -100.0, -5.0, -7.0, -1.0, -8.0, -9.0]])
    results = StaticResults(
        case_id=1,
        case_name="3d",
        n_steps=1,
        element_forces={10: forces},
    )

    series = element_force_curves(_frame_3d(), results, 10, stations=False)

    assert [item.component for item in series] == [
        ForceComponent.N,
        ForceComponent.V2,
        ForceComponent.V3,
        ForceComponent.T,
        ForceComponent.M2,
        ForceComponent.M3,
    ]
    np.testing.assert_allclose(series[3].values, [1.0, 1.0])  # torsion


def test_a_truss_reports_only_its_axial_force() -> None:
    project = Project(
        ndm=2,
        ndf=2,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(3.0, 0.0, 0.0)),
        ],
        materials=[ElasticUniaxial(id=1, E=200e9)],
        elements=[TrussElement(id=1, nodes=(1, 2), area=1e-3, material_id=1)],
    )
    results = StaticResults(
        case_id=1,
        case_name="truss",
        n_steps=1,
        element_forces={1: np.array([[-1500.0, 0.0, 1500.0, 0.0]])},
    )

    series = element_force_curves(project, results, 1, stations=False)

    assert [item.component for item in series] == [ForceComponent.N]
    np.testing.assert_allclose(series[0].values, [-1500.0, -1500.0])


def test_a_rigid_chord_has_no_relative_deformation() -> None:
    project = _frame_2d()
    delta = 0.02
    results = StaticResults(
        case_id=1,
        case_name="chord",
        n_steps=1,
        node_disp={
            1: np.array([[0.0, 0.0, -delta / 4.0]]),
            2: np.array([[0.0, delta, -delta / 4.0]]),
        },
    )

    absolute, relative, note = element_deformation_curves(project, results, 10)

    assert "interpolates" in note
    assert absolute is not None and relative is not None
    mid = len(absolute[0]) // 2
    assert absolute[0][mid] == pytest.approx(2.0)
    assert absolute[1][mid] == pytest.approx(delta / 2.0, rel=1e-9)
    assert relative[1][mid] == pytest.approx(0.0, abs=1e-12)


def test_symmetric_end_rotations_give_the_hermite_midspan_deflection() -> None:
    project = _frame_2d()
    theta = 0.001
    # Global Ry is the negative of the local-z rotation (core.plane).
    results = StaticResults(
        case_id=1,
        case_name="bending",
        n_steps=1,
        node_disp={
            1: np.array([[0.0, 0.0, -theta]]),
            2: np.array([[0.0, 0.0, theta]]),
        },
    )

    absolute, relative, _note = element_deformation_curves(project, results, 10)

    assert absolute is not None and relative is not None
    mid = len(absolute[0]) // 2
    expected = theta * 4.0 / 4.0
    assert relative[1][mid] == pytest.approx(expected, rel=1e-9)
    assert absolute[1][mid] == pytest.approx(expected, rel=1e-9)


def test_a_3d_member_interpolates_about_its_own_local_axes() -> None:
    project = _frame_3d()
    theta = 0.001
    results = StaticResults(
        case_id=1,
        case_name="bending-3d",
        n_steps=1,
        node_disp={
            1: np.array([[0.0, 0.0, 0.0, 0.0, 0.0, theta]]),
            2: np.array([[0.0, 0.0, 0.0, 0.0, 0.0, -theta]]),
        },
    )

    _absolute, relative, _note = element_deformation_curves(project, results, 10)

    assert relative is not None
    mid = len(relative[0]) // 2
    assert relative[1][mid] == pytest.approx(theta * 4.0 / 4.0, rel=1e-9)


def test_the_applied_loads_are_scaled_by_the_case_time_series() -> None:
    segments, points, note = element_applied_loads(_frame_2d(), _forces_2d(), 10)

    assert note == ""
    assert len(segments) == 1
    segment = segments[0]
    assert (segment.x0, segment.x1) == pytest.approx((0.0, 4.0))
    assert segment.w0 == pytest.approx((0.0, -10.0, 0.0))
    assert segment.w1 == pytest.approx((0.0, -10.0, 0.0))

    assert len(points) == 1
    point = points[0]
    assert point.x == pytest.approx(1.0)
    assert point.p == pytest.approx((0.0, -6.0, 0.0))


def test_a_combination_bound_says_it_has_no_single_load_pattern() -> None:
    project = _frame_2d()
    project.combinations.append(LoadCombination(id=99, name="ULS"))
    results = StaticResults(
        case_id=99,
        case_name="ULS max",
        n_steps=1,
        element_forces={10: np.zeros((1, 6))},
    )

    segments, points, note = element_applied_loads(project, results, 10)

    assert segments == () and points == ()
    assert "combination bound" in note


def test_the_bundle_keeps_the_2d_limitation_and_both_envelope_bounds() -> None:
    project = _frame_2d()
    upper = element_diagram_bundle(project, _forces_2d(), 10, stations=False, label="Max")
    lower = element_diagram_bundle(project, _forces_2d(), 10, stations=False, label="Min")

    assert upper.element_id == 10
    assert upper.length == pytest.approx(4.0)
    assert [item.component for item in upper.forces] == [
        ForceComponent.N,
        ForceComponent.V2,
        ForceComponent.M3,
    ]
    assert any("2D frame" in note for note in upper.notes)

    combined = combine_element_bundles(upper, lower)

    assert len(combined.forces) == 6
    assert {item.label for item in combined.forces} == {"Max", "Min"}
    assert (
        combined.notes.count("2D frame: V3, M2 and T are not part of its element force output.")
        == 1
    )


def test_an_unknown_element_is_an_error() -> None:
    with pytest.raises(ValueError, match="not in the project"):
        element_diagram_bundle(_frame_2d(), _forces_2d(), 999)


def test_a_linear_series_with_a_plain_pattern_is_still_scalable() -> None:
    project = _frame_2d()
    project.time_series[:] = [LinearTimeSeries(id=1, factor=1.0)]

    segments, points, note = element_applied_loads(project, _forces_2d(), 10)

    assert note == ""
    assert segments and points
