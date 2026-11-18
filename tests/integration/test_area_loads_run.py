"""Area loads and imposed displacements, solved by OpenSees against statics and closed forms."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    FloorLoad,
    ImposedDisplacement,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
    ShellMITC4Element,
    StaticCase,
    SurfaceLoad,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

FIXED = (True,) * 6


def _solve(project: Project, tmp_path: Path):  # type: ignore[no-untyped-def]
    return OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)


def _one_bay(distribution: str, lx: float = 6.0, ly: float = 6.0) -> Project:
    """Four columns 3 m tall carrying a framed bay lx by ly, the floor load on it."""
    plan = ((0.0, 0.0), (lx, 0.0), (lx, ly), (0.0, ly))
    nodes = [Node(id=k + 1, coords=(x, y, 0.0), restraint=FIXED) for k, (x, y) in enumerate(plan)]
    nodes += [Node(id=k + 11, coords=(x, y, 3.0)) for k, (x, y) in enumerate(plan)]
    elements = [ElasticBeamColumn(id=k + 1, nodes=(k + 1, k + 11), section_id=1) for k in range(4)]
    elements += [
        ElasticBeamColumn(id=k + 11, nodes=(k + 11, (k + 1) % 4 + 11), section_id=1)
        for k in range(4)
    ]
    return Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[ElasticSection(id=1, E=3e10, A=0.09, Iz=6.75e-4, Iy=6.75e-4, G=1.2e10, J=1e-3)],
        elements=elements,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                floor_loads=[
                    FloorLoad(nodes=(11, 12, 13, 14), value=5e3, distribution=distribution)  # type: ignore[arg-type]
                ],
            )
        ],
        analyses=[StaticCase(id=1, name="floor", pattern_ids=[1])],
    )


@pytest.mark.parametrize("distribution", ["two_way", "one_way_12", "one_way_23"])
def test_the_supports_carry_the_whole_floor_load(distribution: str, tmp_path: Path) -> None:
    project = _one_bay(distribution, lx=6.0, ly=4.0)
    results = _solve(project, tmp_path)
    vertical = sum(float(results.node_reaction[n][0][2]) for n in (1, 2, 3, 4))
    assert vertical == pytest.approx(5e3 * 24.0, rel=1e-9)


def test_a_square_bay_loads_its_four_beams_alike(tmp_path: Path) -> None:
    results = _solve(_one_bay("two_way"), tmp_path)
    shears = [abs(float(results.element_forces[k + 11][0][2])) for k in range(4)]
    # Each beam takes q a^2 / 4 = 45 kN, half of it at each end.
    assert shears == pytest.approx([5e3 * 36.0 / 8] * 4, rel=1e-6)


def test_a_pressure_on_a_shell_reaches_the_supports(tmp_path: Path) -> None:
    corners = ((0.0, 0.0), (2.0, 0.0), (2.0, 3.0), (0.0, 3.0))
    pin = (True, True, True, False, False, False)
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=k + 1, coords=(x, y, 0.0), restraint=pin) for k, (x, y) in enumerate(corners)
        ],
        sections=[ElasticMembranePlateSection(id=1, E=3e10, nu=0.2, h=0.2)],
        elements=[ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1, time_series_id=1, surface_loads=[SurfaceLoad(element_id=1, value=-4e3)]
            )
        ],
        analyses=[StaticCase(id=1, name="pressure", pattern_ids=[1])],
    )
    results = _solve(project, tmp_path)
    vertical = sum(float(results.node_reaction[n][0][2]) for n in (1, 2, 3, 4))
    assert vertical == pytest.approx(4e3 * 6.0, rel=1e-9)


@pytest.mark.parametrize("constraints", ["Plain", "Transformation"])
def test_a_settlement_of_the_middle_support_of_a_two_span_beam(
    constraints: str, tmp_path: Path
) -> None:
    """R_mid = 6 E I d / L^3 for spans L and a settlement d; Plain is promoted, not ignored."""
    e, i, length, settle = 2e8, 1e-4, 6.0, -0.01
    roller = (False, False, True, False, False, False)  # Uz, in the X-Z plane
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, False, False)),
        Node(id=2, coords=(length, 0.0, 0.0), restraint=roller),
        Node(id=3, coords=(2 * length, 0.0, 0.0), restraint=roller),
    ]
    project = Project(
        ndm=2,
        ndf=3,
        nodes=nodes,
        sections=[ElasticSection(id=1, E=e, A=0.01, Iz=i)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                imposed_displacements=[ImposedDisplacement(node_id=2, dof=2, value=settle)],
            )
        ],
        analyses=[StaticCase(id=1, name="settle", pattern_ids=[1], constraints=constraints)],
    )
    results = _solve(project, tmp_path)
    assert float(results.node_disp[2][0][1]) == pytest.approx(settle, rel=1e-9)
    expected = 6 * e * i * abs(settle) / length**3
    assert float(results.node_reaction[2][0][1]) == pytest.approx(-expected, rel=1e-6)
    assert float(results.node_reaction[1][0][1]) == pytest.approx(expected / 2, rel=1e-6)
