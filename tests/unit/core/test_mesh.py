"""The meshing geometry: pieces, subdivisions, and the joins between them.

Everything here is pure geometry on core models, so it is checked against hand
calculations: how many pieces a 10 m bar at 3 m becomes, where the nodes land,
that a meshed shell keeps its corners and shares its edges, and that a node or a
crossing inside a bar splits it.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    Node,
    Project,
    ShellMITC4Element,
)
from opensees_studio.core.mesh import (
    MeshError,
    auto_mesh,
    mesh_bars,
    mesh_shells,
    split_bars_at_crossings,
    split_bars_at_nodes,
)


def _frame_section() -> ElasticSection:
    return ElasticSection(id=1, name="S", E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6)


def _plate_section() -> ElasticMembranePlateSection:
    return ElasticMembranePlateSection(id=2, name="P", E=30e9, nu=0.2, h=0.2, rho=2500.0)


def _bar_project(length: float = 10.0, *, element_id: int = 1) -> Project:
    return Project(
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(length, 0.0, 0.0))],
        sections=[_frame_section()],
        elements=[ElasticBeamColumn(id=element_id, nodes=(1, 2), section_id=1)],
    )


def _quad_project(corners: list[tuple[float, float, float]], *, ids: int = 1) -> Project:
    nodes = [Node(id=index + 1, coords=point) for index, point in enumerate(corners)]
    elements = [
        ShellMITC4Element(
            id=index + 1,
            nodes=(index * 4 + 1, index * 4 + 2, index * 4 + 3, index * 4 + 4),
            section_id=2,
        )
        for index in range(ids)
    ]
    return Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[_plate_section()],
        elements=elements,
    )


def _coords_of(plan, node_id: int) -> tuple[float, ...]:  # type: ignore[no-untyped-def]
    for node in plan.new_nodes:
        if node.id == node_id:
            return tuple(node.coords)
    raise AssertionError(f"node {node_id} is not in the plan")


# ──────────────────────────── bars ────────────────────────────
def test_a_bar_is_split_into_equal_pieces() -> None:
    plan = mesh_bars(_bar_project(10.0), {1}, target_size=2.0)

    assert [element.nodes for element in plan.new_elements] == [
        (1, 3),
        (3, 4),
        (4, 5),
        (5, 6),
        (6, 2),
    ]
    positions = sorted(node.coords[0] for node in plan.new_nodes)
    assert positions == [2.0, 4.0, 6.0, 8.0]
    assert plan.removed_element_ids == [1]
    assert plan.replacements == {1: [2, 3, 4, 5, 6]}


def test_the_pieces_are_no_longer_than_the_target() -> None:
    """A 10 m bar at 3 m gives four pieces of 2.5 m, not three of 3.33 m."""
    plan = mesh_bars(_bar_project(10.0), {1}, target_size=3.0)

    assert len(plan.new_elements) == 4
    positions = [0.0, *sorted(node.coords[0] for node in plan.new_nodes), 10.0]
    lengths = np.diff(positions)
    assert np.allclose(lengths, 2.5)
    assert max(lengths) <= 3.0


def test_a_bar_shorter_than_the_target_is_left_alone() -> None:
    plan = mesh_bars(_bar_project(2.0), {1}, target_size=5.0)

    assert plan.is_empty
    assert "No bar longer than the target" in plan.summary()


def test_the_pieces_keep_the_element_properties() -> None:
    project = _bar_project()
    project.elements[0].geom_transf = "PDelta"
    project.elements[0].rho = 7850.0

    plan = mesh_bars(project, {1}, target_size=4.0)

    for element in plan.new_elements:
        assert element.section_id == 1
        assert element.geom_transf == "PDelta"
        assert element.rho == 7850.0


def test_a_node_that_already_exists_is_reused() -> None:
    """Meshing must not land a node on top of one the model already has."""
    project = _bar_project(10.0)
    project.nodes.append(Node(id=3, coords=(5.0, 0.0, 0.0)))

    plan = mesh_bars(project, {1}, target_size=5.0)

    assert plan.new_nodes == []
    assert [element.nodes for element in plan.new_elements] == [(1, 3), (3, 2)]


def test_only_the_selected_bars_are_meshed() -> None:
    project = _bar_project(10.0)
    project.nodes.append(Node(id=3, coords=(10.0, 0.0, 0.0)))
    project.nodes.append(Node(id=4, coords=(20.0, 0.0, 0.0)))
    project.elements.append(ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1))

    plan = mesh_bars(project, {1}, target_size=5.0)

    assert plan.removed_element_ids == [1]  # element 2 untouched
    assert all(element.id != 2 for element in plan.new_elements)


def test_a_target_of_zero_is_refused() -> None:
    with pytest.raises(MeshError, match="must be positive"):
        mesh_bars(_bar_project(), {1}, target_size=0.0)


# ──────────────────────────── shells ────────────────────────────
def test_a_shell_is_subdivided_in_both_directions() -> None:
    project = _quad_project([(0.0, 0.0, 0.0), (6.0, 0.0, 0.0), (6.0, 4.0, 0.0), (0.0, 4.0, 0.0)])

    plan = mesh_shells(project, {1}, target_size=2.0)

    assert len(plan.new_elements) == 6  # 3 across by 2 down
    assert len(plan.new_nodes) == 8  # the interior of a 4x3 grid
    assert plan.removed_element_ids == [1]
    assert all(len(element.nodes) == 4 for element in plan.new_elements)
    # Every cell reuses the original corners where it can.
    used = {node_id for element in plan.new_elements for node_id in element.nodes}
    assert {1, 2, 3, 4} <= used
    assert len(used) == 12  # 4x3 grid: 12 nodes


def test_the_cells_cover_the_shell_without_holes() -> None:
    project = _quad_project([(0.0, 0.0, 0.0), (6.0, 0.0, 0.0), (6.0, 4.0, 0.0), (0.0, 4.0, 0.0)])
    plan = mesh_shells(project, {1}, target_size=2.0)

    coords = {node.id: np.asarray(node.coords) for node in project.nodes}
    coords.update({node.id: np.asarray(node.coords) for node in plan.new_nodes})
    total = 0.0
    for element in plan.new_elements:
        points = [coords[node_id] for node_id in element.nodes]
        total += 0.5 * abs(
            sum(
                points[i][0] * points[(i + 1) % 4][1] - points[(i + 1) % 4][0] * points[i][1]
                for i in range(4)
            )
        )
    assert total == pytest.approx(24.0)  # 6 x 4


def test_two_meshed_shells_share_their_common_edge() -> None:
    """The point of the shared node table: a conforming interface, no duplicates."""
    project = _quad_project(
        [
            (0.0, 0.0, 0.0),
            (3.0, 0.0, 0.0),
            (3.0, 3.0, 0.0),
            (0.0, 3.0, 0.0),
            (6.0, 0.0, 0.0),
            (6.0, 3.0, 0.0),
        ]
    )
    project.elements[0].nodes = (1, 2, 3, 4)
    project.elements.append(ShellMITC4Element(id=2, nodes=(2, 5, 6, 3), section_id=2))

    plan = mesh_shells(project, None, target_size=1.5)

    assert len(plan.new_elements) == 8  # 2x2 cells each
    # The shared edge (nodes 2-3) contributes its middle node once, and both
    # sides use that same id.
    edge_nodes = [
        node
        for node in plan.new_nodes
        if abs(node.coords[0] - 3.0) < 1e-9 and node.coords[1] == 1.5
    ]
    assert len(edge_nodes) == 1
    middle = edge_nodes[0].id
    users = [element for element in plan.new_elements if middle in element.nodes]
    # The edge is split in two, so two cells on each side meet at that node: one
    # node, four cells, and no duplicate anywhere on the interface.
    assert len(users) == 4
    coords = {node.id: np.asarray(node.coords) for node in plan.new_nodes}
    coords.update({node.id: np.asarray(node.coords) for node in project.nodes})
    sides = {
        sign
        for element in users
        for sign in [np.sign(sum(coords[n][0] for n in element.nodes) / 4.0 - 3.0)]
    }
    assert sides == {-1.0, 1.0}  # cells from both shells use it


def test_a_general_quadrilateral_is_meshed_inside_its_own_edges() -> None:
    """Bilinear interpolation keeps the mesh inside a skewed shell."""
    corners = [(0.0, 0.0, 0.0), (4.0, 1.0, 0.0), (3.0, 4.0, 0.0), (-1.0, 3.0, 0.0)]
    project = _quad_project(corners)
    quad = [np.array(corner) for corner in corners]

    plan = mesh_shells(project, {1}, target_size=1.5)

    assert plan.new_elements
    # Every node of the mesh is inside the (convex) quadrilateral: it lies to the
    # left of each edge, the quad being counter-clockwise.
    for node in plan.new_nodes:
        point = np.asarray(node.coords)
        for index in range(4):
            start_point = quad[index]
            edge = quad[(index + 1) % 4] - start_point
            assert float(np.cross(edge, point - start_point)[2]) >= -1e-9
    # And the corners of the mesh carry the shell's own edge directions.
    used = {node_id for element in plan.new_elements for node_id in element.nodes}
    assert {1, 2, 3, 4} <= used


def test_a_supported_edge_stays_supported_after_meshing() -> None:
    """Otherwise meshing a slab would quietly drop the middle of its supports."""
    n = 2
    nodes: list[Node] = []
    ids: dict[tuple[int, int], int] = {}
    for j in range(n + 1):
        for i in range(n + 1):
            restraint = [False] * 6
            if i in (0, n) or j in (0, n):
                restraint[2] = True  # Uz fixed along the whole edge
            ids[(i, j)] = len(nodes) + 1
            nodes.append(
                Node(id=len(nodes) + 1, coords=(i / n, j / n, 0.0), restraint=tuple(restraint))
            )
    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[_plate_section()],
        elements=[
            ShellMITC4Element(
                id=j * n + i + 1,
                nodes=(ids[(i, j)], ids[(i + 1, j)], ids[(i + 1, j + 1)], ids[(i, j + 1)]),
                section_id=2,
            )
            for j in range(n)
            for i in range(n)
        ],
    )

    plan = mesh_shells(project, None, target_size=0.25)

    on_edge = [
        node
        for node in plan.new_nodes
        if node.coords[0] in (0.0, 1.0) or node.coords[1] in (0.0, 1.0)
    ]
    inside = [
        node for node in plan.new_nodes if 0.0 < node.coords[0] < 1.0 and 0.0 < node.coords[1] < 1.0
    ]
    assert on_edge and inside
    assert all(node.restraint[2] for node in on_edge)  # the support, inherited
    assert all(not any(node.restraint) for node in inside)  # an interior node is free


def test_a_shell_smaller_than_the_target_is_left_alone() -> None:
    project = _quad_project([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)])

    plan = mesh_shells(project, {1}, target_size=5.0)

    assert plan.is_empty
    assert "No shell larger than the target" in plan.summary()


# ──────────────────────────── the joins ────────────────────────────
def test_a_bar_is_split_at_a_node_lying_on_it() -> None:
    project = _bar_project(10.0)
    project.nodes.append(Node(id=3, coords=(5.0, 0.0, 0.0)))

    plan = split_bars_at_nodes(project, {1})

    assert [element.nodes for element in plan.new_elements] == [(1, 3), (3, 2)]
    assert plan.new_nodes == []  # the node was already there
    assert "1 bar(s) split at nodes" in plan.summary()


def test_several_nodes_on_one_bar_split_it_into_pieces() -> None:
    project = _bar_project(10.0)
    project.nodes.extend(
        [
            Node(id=4, coords=(7.0, 0.0, 0.0)),
            Node(id=3, coords=(3.0, 0.0, 0.0)),
        ]
    )

    plan = split_bars_at_nodes(project, {1})

    # Sorted along the bar, whatever order the nodes were in.
    assert [element.nodes for element in plan.new_elements] == [(1, 3), (3, 4), (4, 2)]


def test_a_node_at_the_end_of_a_bar_does_not_split_it() -> None:
    project = _bar_project(10.0)
    project.nodes.append(Node(id=3, coords=(10.0, 0.0, 0.0)))

    assert split_bars_at_nodes(project, {1}).is_empty


def test_a_node_slightly_off_a_bar_splits_it_within_the_tolerance() -> None:
    project = _bar_project(10.0)
    project.nodes.append(Node(id=3, coords=(5.0, 0.0, 1e-4)))

    assert split_bars_at_nodes(project, {1}, tolerance=1e-3).new_elements
    assert split_bars_at_nodes(project, {1}, tolerance=1e-6).is_empty


def test_crossing_bars_are_split_at_the_crossing() -> None:
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, -5.0, 0.0)),
            Node(id=2, coords=(0.0, 5.0, 0.0)),
            Node(id=3, coords=(-5.0, 0.0, 0.0)),
            Node(id=4, coords=(5.0, 0.0, 0.0)),
        ],
        sections=[_frame_section()],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1),
        ],
    )

    plan = split_bars_at_crossings(project, {1, 2})

    assert plan.removed_element_ids == [1, 2]
    assert len(plan.new_elements) == 4
    assert len(plan.new_nodes) == 1
    crossing = plan.new_nodes[0]
    assert crossing.coords == pytest.approx((0.0, 0.0, 0.0))
    # Both bars now use the crossing node.
    assert sum(1 for element in plan.new_elements if crossing.id in element.nodes) == 4


def test_parallel_bars_do_not_cross() -> None:
    project = _bar_project(10.0)
    project.nodes.extend([Node(id=3, coords=(0.0, 1.0, 0.0)), Node(id=4, coords=(10.0, 1.0, 0.0))])
    project.elements.append(ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1))

    assert split_bars_at_crossings(project, {1, 2}).is_empty


def test_bars_that_share_a_node_already_meet_there() -> None:
    project = _bar_project(10.0)
    project.nodes.append(Node(id=3, coords=(10.0, 10.0, 0.0)))
    project.elements.append(ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1))

    assert split_bars_at_crossings(project, {1, 2}).is_empty


def test_a_crossing_outside_the_segment_does_not_split() -> None:
    """Two collinear-ish bars that would cross beyond their ends."""
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(1.0, 0.0, 0.0)),
            Node(id=3, coords=(5.0, -1.0, 0.0)),
            Node(id=4, coords=(5.0, 1.0, 0.0)),
        ],
        sections=[_frame_section()],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1),
        ],
    )

    assert split_bars_at_crossings(project, {1, 2}, tolerance=0.01).is_empty


# ──────────────────────────── the whole thing ────────────────────────────
def test_auto_mesh_chains_the_stages() -> None:
    """A bar that crosses a shell's edge is split at the node the mesh created."""
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            # A shell 4 x 4 in the XY plane...
            Node(id=1, coords=(0.0, 0.0, 1.0)),
            Node(id=2, coords=(4.0, 0.0, 1.0)),
            Node(id=3, coords=(4.0, 4.0, 1.0)),
            Node(id=4, coords=(0.0, 4.0, 1.0)),
            # ...and a bar crossing it at y = 2, above the shell.
            Node(id=5, coords=(0.0, 2.0, 0.0)),
            Node(id=6, coords=(0.0, 2.0, 2.0)),
        ],
        sections=[_frame_section(), _plate_section()],
        elements=[
            ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=2),
            ElasticBeamColumn(id=2, nodes=(5, 6), section_id=1),
        ],
    )

    plan = auto_mesh(project, None, target_size=2.0)

    # The shell became 2x2 cells...
    shells = [element for element in plan.new_elements if len(element.nodes) == 4]
    assert len(shells) == 4
    # ...and the bar was split where the shell's new edge node lands on it: the
    # edge at y = 2 is a line of the mesh, and its middle node (2, 2, 1) is not
    # on the bar (which is vertical at x = 0), but the mesh did create a node at
    # (0, 2, 1) — a shell corner-to-corner line — so the bar splits there.
    bars = [element for element in plan.new_elements if len(element.nodes) == 2]
    assert len(bars) == 2
    split_node = next(
        node for node in plan.new_nodes if node.coords[:2] == pytest.approx((0.0, 2.0))
    )
    assert split_node.coords[2] == pytest.approx(1.0)
    assert any(split_node.id in element.nodes for element in bars)


def test_auto_mesh_can_do_one_thing_at_a_time() -> None:
    project = _bar_project(10.0)
    project.nodes.append(Node(id=3, coords=(5.0, 0.0, 0.0)))

    only_bars = auto_mesh(project, None, target_size=3.0, at_nodes=False, at_crossings=False)
    only_joins = auto_mesh(project, None, target_size=100.0, shells=False, bars=False)

    assert len(only_bars.new_elements) == 4  # split at the target, not at node 3
    assert [element.nodes for element in only_joins.new_elements] == [(1, 3), (3, 2)]


def test_the_summary_says_what_will_change() -> None:
    plan = mesh_bars(_bar_project(10.0), {1}, target_size=4.0)

    summary = plan.summary()
    assert "+3 element(s)" in summary
    assert "+2 node(s)" in summary
    assert "-1 element(s) replaced" in summary
    assert math.isclose(plan.new_nodes[0].coords[0], 10.0 / 3.0, rel_tol=1e-12)
