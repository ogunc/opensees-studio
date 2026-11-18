"""View → Grid Line View: which objects lie on a grid line, and the filtered copy."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core import Project
from opensees_studio.core.constraints import EqualDOFConstraint
from opensees_studio.core.geometry import (
    CoordinateGridSystem,
    CoordinateSystem,
    ElasticBeamColumn,
    GridSystem,
    Node,
    make_grid_lines,
)
from opensees_studio.core.grid_view import (
    default_window,
    filtered_project,
    find_grid_line,
    grid_lines,
    objects_on_line,
)
from opensees_studio.core.loads import NodalLoad, PlainLoadPattern, UniformElementLoad
from opensees_studio.core.units import UnitSystem


def _frame(**grid: object) -> Project:
    """Two bays along X (0, 6, 12) at y = 0 and one joint at y = 0.03 (inside 50 mm)."""
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0)),
        Node(id=2, coords=(0.0, 0.0, 3.0)),
        Node(id=3, coords=(6.0, 0.0, 3.0)),
        Node(id=4, coords=(6.0, 0.03, 0.0)),
        Node(id=5, coords=(6.0, 5.0, 3.0)),
    ]
    elements = [
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
        ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
        ElasticBeamColumn(id=3, nodes=(3, 4), section_id=1),
        ElasticBeamColumn(id=4, nodes=(3, 5), section_id=1),
    ]
    system = CoordinateGridSystem(
        name="Global",
        grid=GridSystem.model_validate(
            {
                "x_grid_lines": make_grid_lines("X", [0.0, 6.0]),
                "y_grid_lines": make_grid_lines("Y", [0.0, 5.0]),
                "z_grid_lines": make_grid_lines("Z", [0.0, 3.0]),
                **grid,
            }
        ),
    )
    return Project.model_construct(
        **{
            **Project(ndm=3, ndf=6).__dict__,
            "nodes": nodes,
            "elements": elements,
            "coord_systems": [system],
        }
    )


def test_default_window_is_50_mm_in_the_model_unit() -> None:
    assert default_window(UnitSystem.SI_M_N) == pytest.approx(0.05)
    assert default_window(UnitSystem.SI_MM_N) == pytest.approx(50.0)
    assert default_window(UnitSystem.US_IN_KIP) == pytest.approx(0.05 / 0.0254)


def test_lines_are_listed_by_label() -> None:
    project = _frame()
    labels = [ref.label for ref in grid_lines(project)]
    assert labels[0] == "Global: X X1 (0)"
    assert find_grid_line(project, "Global: Y Y1 (0)") is not None
    assert find_grid_line(project, "Global: Y Q (0)") is None


def test_plane_line_keeps_joints_inside_the_window() -> None:
    project = _frame()
    y1 = find_grid_line(project, "Global: Y Y1 (0)")
    assert y1 is not None
    nodes, elements = objects_on_line(project, y1, 0.05)
    assert nodes == {1, 2, 3, 4}  # joint 4 is 30 mm off, inside the window
    assert elements == {1, 2, 3}  # element 4 goes to y = 5
    nodes, _ = objects_on_line(project, y1, 0.01)
    assert 4 not in nodes


def test_level_line() -> None:
    project = _frame()
    z2 = find_grid_line(project, "Global: Z Z2 (3)")
    assert z2 is not None
    assert objects_on_line(project, z2, 0.05) == ({2, 3, 5}, {2, 4})


def test_line_of_a_shifted_system_is_measured_in_its_own_frame() -> None:
    project = _frame()
    shifted = CoordinateGridSystem(
        name="B",
        coord=CoordinateSystem(origin=(6.0, 0.0, 0.0)),
        grid=GridSystem(x_grid_lines=make_grid_lines("X", [0.0])),
    )
    project.coord_systems = [*project.coord_systems, shifted]
    ref = find_grid_line(project, "B: X X1 (0)")
    assert ref is not None
    assert objects_on_line(project, ref, 0.05)[0] == {3, 4, 5}


def test_ring_and_radial_lines() -> None:
    nodes = [
        Node(id=k + 1, coords=(10 * math.cos(math.radians(a)), 10 * math.sin(math.radians(a)), 0.0))
        for k, a in enumerate((0, 90, 180))
    ] + [Node(id=9, coords=(5.0, 0.0, 0.0))]
    grid = GridSystem.model_validate(
        {
            "system_type": "Cylindrical",
            "x_grid_lines": make_grid_lines("R", [5.0, 10.0]),
            "y_grid_lines": make_grid_lines("T", [0.0, 90.0, 180.0, 270.0]),
        }
    )
    project = Project(
        ndm=3, ndf=6, nodes=nodes, coord_systems=[CoordinateGridSystem(name="Global", grid=grid)]
    )
    ring = find_grid_line(project, "Global: R R2 (10)")
    radial = find_grid_line(project, "Global: T T1 (0°)")
    assert ring is not None and radial is not None
    assert objects_on_line(project, ring, 0.05)[0] == {1, 2, 3}
    # The 0° radial line runs from the axis outwards: the 180° joint is not on it.
    assert objects_on_line(project, radial, 0.05)[0] == {1, 9}


def test_filtered_project_drops_what_points_at_hidden_objects() -> None:
    project = _frame()
    pattern = PlainLoadPattern(
        id=1,
        time_series_id=1,
        nodal_loads=[
            NodalLoad(node_id=2, forces=(1.0, 0, 0, 0, 0, 0)),
            NodalLoad(node_id=5, forces=(1.0, 0, 0, 0, 0, 0)),
        ],
        element_loads=[
            UniformElementLoad(element_id=2, wy=-1.0),
            UniformElementLoad(element_id=4, wy=-1.0),
        ],
    )
    project.load_patterns = [pattern]
    project.mp_constraints = [EqualDOFConstraint(retained_node=3, constrained_node=5, dofs=[1])]
    view = filtered_project(project, frozenset({1, 2, 3, 4}), frozenset({1, 2, 3}))
    assert [n.id for n in view.nodes] == [1, 2, 3, 4]
    assert [e.id for e in view.elements] == [1, 2, 3]
    shown = view.load_patterns[0]
    assert [ld.node_id for ld in shown.nodal_loads] == [2]
    assert [ld.element_id for ld in shown.element_loads] == [2]
    assert view.mp_constraints == []
    # The model itself is untouched.
    assert len(project.nodes) == 5 and len(project.load_patterns[0].nodal_loads) == 2
