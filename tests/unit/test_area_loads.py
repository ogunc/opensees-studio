"""Area loads: shell pressure, floor panels to frames, imposed displacements (pure core)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

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
    SurfaceLoad,
)
from opensees_studio.core.area_loads import (
    AreaLoadError,
    edge_profile,
    floor_area,
    floor_member_loads,
    floor_panels,
    pattern_distributed_loads,
    surface_nodal_loads,
)


def _member_total(project: Project, loads) -> float:  # type: ignore[no-untyped-def]
    """The resultant (force) of trapezoidal member loads."""
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    elements = {e.id: e for e in project.elements}
    total = 0.0
    for load in loads:
        i, j = elements[load.element_id].nodes
        length = float(np.linalg.norm(coords[j] - coords[i]))
        a = math.dist((0, 0, 0), load.start())
        b = math.dist((0, 0, 0), load.end())
        total += 0.5 * (a + b) * (load.x_end - load.x_start) * length
    return total


def _floor(lx: float = 6.0, ly: float = 4.0, split_first_beam: bool = False) -> Project:
    corners = [(0.0, 0.0), (lx, 0.0), (lx, ly), (0.0, ly)]
    nodes = [Node(id=k + 1, coords=(x, y, 3.0)) for k, (x, y) in enumerate(corners)]
    edges = [(1, 2), (2, 3), (3, 4), (4, 1)]
    if split_first_beam:
        nodes.append(Node(id=9, coords=(lx / 3, 0.0, 3.0)))
        edges = [(1, 9), (9, 2), *edges[1:]]
    elements = [ElasticBeamColumn(id=k + 1, nodes=e, section_id=1) for k, e in enumerate(edges)]
    return Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        elements=elements,
        sections=[ElasticSection(id=1, E=1.0, A=1.0, Iz=1.0, Iy=1.0, G=1.0, J=1.0)],
    )


# ─────────────────────────── floor panels ───────────────────────────
@pytest.mark.parametrize("distribution", ["two_way", "one_way_12", "one_way_23"])
@pytest.mark.parametrize("split", [False, True])
def test_a_floor_panel_hands_exactly_q_a_to_its_frames(distribution: str, split: bool) -> None:
    project = _floor(split_first_beam=split)
    load = FloorLoad(nodes=(1, 2, 3, 4), value=5.0, distribution=distribution)  # type: ignore[arg-type]
    loads = floor_member_loads(project, load)
    assert _member_total(project, loads) == pytest.approx(5.0 * floor_area(project, load))


def test_two_way_gives_trapezoids_on_long_edges_and_triangles_on_short_ones() -> None:
    assert edge_profile(6.0, 4.0, 5.0) == [
        (0.0, 2.0, 0.0, 10.0),
        (2.0, 4.0, 10.0, 10.0),
        (4.0, 6.0, 10.0, 0.0),
    ]
    assert edge_profile(4.0, 4.0, 5.0) == [(0.0, 2.0, 0.0, 10.0), (2.0, 4.0, 10.0, 0.0)]


def test_one_way_loads_only_the_edges_across_the_span() -> None:
    project = _floor()
    loads = floor_member_loads(
        project, FloorLoad(nodes=(1, 2, 3, 4), value=5.0, distribution="one_way_12")
    )
    assert {load.element_id for load in loads} == {2, 4}  # edges 2-3 and 4-1
    assert all(math.dist((0, 0, 0), load.start()) == pytest.approx(15.0) for load in loads)


def test_the_load_points_down_in_each_members_axes() -> None:
    project = _floor()
    for load in floor_member_loads(project, FloorLoad(nodes=(1, 2, 3, 4), value=5.0)):
        # Horizontal beams: gravity is -local z, nothing axial or along local y.
        assert load.wx_start == pytest.approx(0.0) and load.wy_start == pytest.approx(0.0)
        assert load.wz_start <= 0.0 and load.wz_end <= 0.0


def test_a_panel_must_be_a_horizontal_framed_rectangle() -> None:
    project = _floor()
    with pytest.raises(AreaLoadError, match="not a rectangle"):
        floor_member_loads(project, FloorLoad(nodes=(1, 3, 2, 4), value=1.0))
    project.nodes[2] = project.nodes[2].model_copy(update={"coords": (6.0, 4.0, 3.5)})
    with pytest.raises(AreaLoadError, match="not horizontal"):
        floor_member_loads(project, FloorLoad(nodes=(1, 2, 3, 4), value=1.0))
    framed = _floor()
    framed.elements = framed.elements[:3]  # edge 4-1 has no beam
    with pytest.raises(AreaLoadError, match="No frame members"):
        floor_member_loads(framed, FloorLoad(nodes=(1, 2, 3, 4), value=1.0))


def test_floor_panels_finds_each_framed_bay_once() -> None:
    project = _floor(split_first_beam=True)
    assert floor_panels(project, {1, 2, 3, 4, 9}) == [(1, 2, 3, 4)]
    assert floor_panels(project, {1, 2, 3}) == []


def test_the_pattern_reads_its_floor_loads_with_its_member_loads() -> None:
    project = _floor()
    pattern = PlainLoadPattern(
        id=1, time_series_id=1, floor_loads=[FloorLoad(nodes=(1, 2, 3, 4), value=2.0)]
    )
    assert _member_total(project, pattern_distributed_loads(project, pattern)) == pytest.approx(
        48.0
    )


# ─────────────────────────── shells ───────────────────────────
def _plate() -> Project:
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0)),
        Node(id=2, coords=(2.0, 0.0, 0.0)),
        Node(id=3, coords=(2.0, 3.0, 0.0)),
        Node(id=4, coords=(0.0, 3.0, 0.0)),
    ]
    return Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[ElasticMembranePlateSection(id=1, E=3e10, nu=0.2, h=0.2)],
        elements=[ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=1)],
    )


@pytest.mark.parametrize(
    ("direction", "axis", "sign"), [("Z", 2, 1.0), ("normal", 2, 1.0), ("X", 0, 1.0)]
)
def test_a_shell_pressure_adds_up_to_value_times_area(
    direction: str, axis: int, sign: float
) -> None:
    forces = surface_nodal_loads(
        _plate(), [SurfaceLoad(element_id=1, value=-4.0, direction=direction)]
    )  # type: ignore[arg-type]
    total = sum(forces.values())
    assert total[axis] == pytest.approx(sign * -4.0 * 6.0)
    assert all(f[axis] == pytest.approx(-4.0 * 6.0 / 4) for f in forces.values())


# ─────────────────────────── the file ───────────────────────────
def test_a_pattern_without_the_new_loads_saves_as_before() -> None:
    dumped = PlainLoadPattern(id=1, time_series_id=1).model_dump(mode="json")
    for key in ("surface_loads", "floor_loads", "imposed_displacements"):
        assert key not in dumped


def test_references_of_the_new_loads_are_checked() -> None:
    project = _floor()
    project.time_series.append(LinearTimeSeries(id=1))
    project.load_patterns.append(
        PlainLoadPattern(
            id=1,
            time_series_id=1,
            surface_loads=[SurfaceLoad(element_id=1, value=1.0)],
            floor_loads=[FloorLoad(nodes=(1, 2, 3, 77), value=1.0)],
            imposed_displacements=[ImposedDisplacement(node_id=88, dof=3, value=-0.01)],
        )
    )
    with pytest.raises(ValueError) as excinfo:
        project.validate_references()
    message = str(excinfo.value)
    assert "not a shell" in message and "missing node(s) [77]" in message and "88" in message
    assert json.loads(project.model_dump_json())["load_patterns"][0]["floor_loads"]
