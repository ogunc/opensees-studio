"""Self weight: gamma * A per length, downward, split over each frame's local axes."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core import (
    DEFAULT_UNIT_WEIGHT,
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
    TrussElement,
    ensure_dead_load_case,
    make_default_section,
    self_weight_loads,
    total_self_weight,
)
from opensees_studio.core.geometry.local_axes import frame_local_axes, frame_vecxz

GAMMA = 10.0
AREA = 0.5
W = GAMMA * AREA  # weight per length


def _section(gamma: float = GAMMA) -> ElasticSection:
    return ElasticSection(
        id=1, name="S", E=1.0, A=AREA, Iz=1.0, Iy=1.0, G=1.0, J=1.0, unit_weight=gamma
    )


def _project(ndm: int, coords: dict[int, tuple[float, float, float]], members) -> Project:  # type: ignore[no-untyped-def]
    return Project(
        ndm=ndm,
        ndf=3 if ndm == 2 else 6,
        nodes=[Node(id=nid, coords=xyz) for nid, xyz in coords.items()],
        sections=[_section()],
        elements=[ElasticBeamColumn(id=eid, nodes=ij, section_id=1) for eid, ij in members],
    )


# ──────────────────────────── local axes ────────────────────────────
def test_the_runner_vecxz_rule() -> None:
    assert frame_vecxz((0, 0, 0), (0, 0, 3)) == (1.0, 0.0, 0.0)  # column
    assert frame_vecxz((0, 0, 0), (4, 0, 0)) == (0.0, 0.0, 1.0)  # beam
    assert frame_vecxz((0, 0, 0), (0, 0, 0)) == (0.0, 0.0, 1.0)  # degenerate


def test_local_axes_are_orthonormal_and_follow_opensees() -> None:
    x, y, z = frame_local_axes(3, (0, 0, 0), (4, 0, 0))
    assert list(x) == [1, 0, 0]
    assert list(z) == pytest.approx([0, 0, 1])  # vecxz lies in the x-z plane
    assert list(y) == pytest.approx([0, 1, 0])  # y = vecxz × x
    # 2D: the X-Z plane, local y = (-Y) x local x (OpenSees' own, see core.plane).
    x2, y2, z2 = frame_local_axes(2, (0, 0, 0), (0, 0, 3))
    assert list(x2) == [0, 0, 1] and list(y2) == pytest.approx([-1, 0, 0])
    assert list(z2) == pytest.approx([0, -1, 0])
    _, y_beam, _ = frame_local_axes(2, (0, 0, 0), (4, 0, 0))
    assert list(y_beam) == pytest.approx([0, 0, 1])  # a 2D beam's local y points up
    assert frame_local_axes(3, (1, 1, 1), (1, 1, 1)) is None


# ──────────────────────────── the loads ────────────────────────────
def test_a_3d_beam_takes_its_weight_transversely_and_a_column_axially() -> None:
    project = _project(
        3,
        {1: (0, 0, 0), 2: (4, 0, 0), 3: (0, 0, 3)},
        [(1, (1, 2)), (2, (1, 3))],
    )
    beam, column = self_weight_loads(project)

    # Beam along X: down (-Z) is -local z.
    assert (beam.wx, beam.wy, beam.wz) == pytest.approx((0.0, 0.0, -W))
    # Column from bottom to top: down is -local x (compression).
    assert (column.wx, column.wy, column.wz) == pytest.approx((-W, 0.0, 0.0))


def test_a_sloped_2d_rafter_splits_its_weight() -> None:
    project = _project(2, {1: (0, 0, 0), 2: (3, 0, 4)}, [(1, (1, 2))])
    (load,) = self_weight_loads(project, multiplier=2.0)
    # In the X-Z plane: x = (0.6, 0.8), y = (-0.8, 0.6); down = (0, -1) in (X, Z).
    assert (load.wx, load.wy) == pytest.approx((-0.8 * 2 * W, -0.6 * 2 * W))
    assert math.hypot(load.wx, load.wy) == pytest.approx(2 * W)


def test_weightless_sections_trusses_and_a_zero_multiplier_carry_nothing() -> None:
    project = _project(3, {1: (0, 0, 0), 2: (4, 0, 0)}, [(1, (1, 2))])
    assert self_weight_loads(project, multiplier=0.0) == []
    project.elements.append(TrussElement(id=2, nodes=(1, 2), area=1.0, material_id=1))
    assert [load.element_id for load in self_weight_loads(project)] == [1]
    project.sections[0] = _section(gamma=0.0)
    assert self_weight_loads(project) == []


def test_total_self_weight_is_gamma_a_l() -> None:
    project = _project(3, {1: (0, 0, 0), 2: (3, 4, 0)}, [(1, (1, 2))])
    assert total_self_weight(project) == pytest.approx(W * 5.0)


# ──────────────────────────── file format and defaults ────────────────────────────
def test_unset_unit_weight_and_self_weight_save_as_before() -> None:
    assert "unit_weight" not in _section(gamma=0.0).model_dump()
    assert "self_weight" not in PlainLoadPattern(id=1, time_series_id=1).model_dump()
    pattern = PlainLoadPattern(id=1, time_series_id=1, self_weight=1.0)
    assert PlainLoadPattern.model_validate_json(pattern.model_dump_json()).self_weight == 1.0


def test_the_default_section_is_steel() -> None:
    assert make_default_section(1).unit_weight == pytest.approx(76_982.2, rel=1e-5)
    assert make_default_section(1).unit_weight == DEFAULT_UNIT_WEIGHT


def test_the_dead_case_is_added_once() -> None:
    project = Project(ndm=3, ndf=6, time_series=[LinearTimeSeries(id=1)])
    pattern = ensure_dead_load_case(project)

    assert (pattern.id, pattern.name, pattern.self_weight) == (1, "DEAD", 1.0)
    assert project.time_series[-1].id == 2 and pattern.time_series_id == 2
    (case,) = project.analyses
    assert (case.name, case.pattern_ids) == ("DEAD", [1])

    assert ensure_dead_load_case(project) is pattern
    assert len(project.load_patterns) == 1 and len(project.analyses) == 1


# ──────────────────────────── shells ────────────────────────────
def _slab(points, gamma: float = 25.0, h: float = 0.2) -> Project:  # type: ignore[no-untyped-def]
    from opensees_studio.core import ElasticMembranePlateSection, ShellMITC4Element

    return Project(
        ndm=3,
        ndf=6,
        nodes=[Node(id=i + 1, coords=p) for i, p in enumerate(points)],
        sections=[ElasticMembranePlateSection(id=1, E=1.0, nu=0.2, h=h, unit_weight=gamma)],
        elements=[ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=1)],
    )


def test_a_rectangle_gives_a_quarter_of_its_weight_to_each_corner() -> None:
    from opensees_studio.core.self_weight import nodal_self_weight_loads

    project = _slab([(0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)])
    loads = nodal_self_weight_loads(project)
    weight = 25.0 * 0.2 * 12.0
    assert sorted(loads) == [1, 2, 3, 4]
    for force in loads.values():
        assert list(force) == pytest.approx([0.0, 0.0, -weight / 4])
    assert total_self_weight(project) == pytest.approx(weight)


def test_a_trapezoid_shares_by_consistent_integration() -> None:
    import numpy as np

    from opensees_studio.core.self_weight import quad_tributary_areas

    shares = quad_tributary_areas(np.array([(0, 0, 0), (4, 0, 0), (3, 2, 0), (1, 2, 0)], float))
    assert shares.sum() == pytest.approx(6.0)  # (4 + 2) / 2 * 2
    assert shares[0] > shares[3]  # the long side carries more


def test_a_weightless_plate_and_a_zero_multiplier_carry_nothing() -> None:
    from opensees_studio.core.self_weight import nodal_self_weight_loads

    assert (
        nodal_self_weight_loads(_slab([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], gamma=0.0))
        == {}
    )
    assert nodal_self_weight_loads(_slab([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]), 0.0) == {}
