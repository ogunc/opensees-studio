"""Physical members and their bracing points (core.design.members), without a solver."""

from __future__ import annotations

import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    Node,
    Project,
    ShellMITC4Element,
)
from opensees_studio.core.design.members import design_members, members_by_element
from opensees_studio.core.diaphragms import RigidDiaphragm

FIX = (True,) * 6


def _section(sid: int = 1) -> ElasticSection:
    return ElasticSection(id=sid, E=29000.0, A=10.0, Iz=500.0, Iy=100.0, G=11200.0, J=2.0)


def _frame(eid: int, i: int, j: int, section: int = 1) -> ElasticBeamColumn:
    return ElasticBeamColumn(id=eid, nodes=(i, j), section_id=section)


def test_a_meshed_beam_is_one_member_braced_only_at_its_ends() -> None:
    nodes = [Node(id=k + 1, coords=(100.0 * k, 0.0, 0.0)) for k in range(5)]
    nodes[0] = nodes[0].model_copy(update={"restraint": FIX})
    nodes[4] = nodes[4].model_copy(update={"restraint": FIX})
    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[_section()],
        elements=[_frame(k + 1, k + 1, k + 2) for k in range(4)],
    )
    (member,) = design_members(project)
    assert member.element_ids == (1, 2, 3, 4)
    assert member.length == pytest.approx(400.0)
    assert member.role == "beam"
    for eid in (1, 2, 3, 4):
        assert member.unbraced_length(eid, "y") == pytest.approx(400.0)
        assert member.unbraced_length(eid, "z") == pytest.approx(400.0)


def test_elements_out_of_order_and_reversed_still_chain() -> None:
    nodes = [Node(id=k + 1, coords=(100.0 * k, 0.0, 0.0)) for k in range(4)]
    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[_section()],
        elements=[_frame(7, 3, 2), _frame(3, 1, 2), _frame(5, 3, 4)],
    )
    (member,) = design_members(project)
    assert member.element_ids == (3, 7, 5)
    assert member.node_ids == (1, 2, 3, 4)


def test_a_different_section_or_a_kink_ends_the_member() -> None:
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0)),
        Node(id=2, coords=(100.0, 0.0, 0.0)),
        Node(id=3, coords=(200.0, 0.0, 0.0)),
        Node(id=4, coords=(300.0, 0.0, 30.0)),
    ]
    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[_section(1), _section(2)],
        elements=[_frame(1, 1, 2), _frame(2, 2, 3, section=2), _frame(3, 3, 4, section=2)],
    )
    assert [m.element_ids for m in design_members(project)] == [(1,), (2,), (3,)]


def test_a_2d_column_continues_through_the_floors_braced_at_each_one() -> None:
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, True, False)),
        Node(id=2, coords=(0.0, 0.0, 144.0)),
        Node(id=3, coords=(0.0, 0.0, 288.0)),
        Node(id=4, coords=(240.0, 0.0, 144.0)),
        Node(id=5, coords=(240.0, 0.0, 288.0)),
    ]
    project = Project(
        ndm=2,
        ndf=3,
        nodes=nodes,
        sections=[_section(1), _section(2)],
        elements=[
            _frame(1, 1, 2),
            _frame(2, 2, 3),
            _frame(10, 2, 4, section=2),
            _frame(11, 3, 5, section=2),
        ],
    )
    column = members_by_element(design_members(project))[1]
    assert column.element_ids == (1, 2)
    assert column.role == "column"
    # In the plane, the beam holds the column; out of it, a 2D model assumes the floor does.
    assert column.unbraced_length(1, "y") == pytest.approx(144.0)
    assert column.unbraced_length(2, "z") == pytest.approx(144.0)


def test_in_3d_a_member_braces_only_along_its_own_direction() -> None:
    """A beam along X at mid-height holds a column along X, not along Y."""
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=FIX),
        Node(id=2, coords=(0.0, 0.0, 144.0)),
        Node(id=3, coords=(0.0, 0.0, 288.0)),
        Node(id=4, coords=(240.0, 0.0, 144.0), restraint=FIX),
    ]
    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[_section(1), _section(2)],
        elements=[_frame(1, 1, 2), _frame(2, 2, 3), _frame(3, 2, 4, section=2)],
    )
    from opensees_studio.core.geometry.local_axes import frame_local_axes

    column = members_by_element(design_members(project))[1]
    _x, local_y, _z = frame_local_axes(3, [0, 0, 0], [0, 0, 144.0])  # type: ignore[misc]
    along_global_x = "y" if abs(local_y[0]) > 0.5 else "z"
    across = "z" if along_global_x == "y" else "y"
    assert column.unbraced_length(1, along_global_x) == pytest.approx(144.0)
    assert column.unbraced_length(1, across) == pytest.approx(288.0)


def test_a_rigid_diaphragm_braces_the_column_horizontally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=FIX),
        Node(id=2, coords=(0.0, 0.0, 144.0)),
        Node(id=3, coords=(0.0, 0.0, 288.0)),
        Node(id=4, coords=(240.0, 240.0, 144.0)),
    ]
    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[_section()],
        elements=[_frame(1, 1, 2), _frame(2, 2, 3)],
    )
    project.diaphragms.append(
        RigidDiaphragm.model_construct(id=1, perp_dirn=3, retained_node=4, storey_id=None)
    )
    # The diaphragm ties node 2 (its storey lookup is not what is tested here).
    monkeypatch.setattr(
        "opensees_studio.core.diaphragms.constrained_node_ids", lambda _project, _d: (2,)
    )
    column = members_by_element(design_members(project))[1]
    assert column.unbraced_length(1, "y") == pytest.approx(144.0)
    assert column.unbraced_length(1, "z") == pytest.approx(144.0)


def test_a_slab_braces_a_beam_laterally_but_not_vertically() -> None:
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=FIX),
        Node(id=2, coords=(100.0, 0.0, 0.0)),
        Node(id=3, coords=(200.0, 0.0, 0.0), restraint=FIX),
        Node(id=4, coords=(100.0, 100.0, 0.0), restraint=FIX),
        Node(id=5, coords=(0.0, 100.0, 0.0), restraint=FIX),
    ]
    from opensees_studio.core import ElasticMembranePlateSection

    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[_section(), ElasticMembranePlateSection(id=9, E=3600.0, nu=0.2, h=6.0)],
        elements=[
            _frame(1, 1, 2),
            _frame(2, 2, 3),
            ShellMITC4Element(id=20, nodes=(1, 2, 4, 5), section_id=9),
        ],
    )
    beam = members_by_element(design_members(project))[1]
    lengths = sorted(beam.unbraced_length(1, a) for a in ("y", "z"))  # type: ignore[arg-type]
    assert lengths == [pytest.approx(100.0), pytest.approx(200.0)]


def test_a_role_set_by_hand_wins_over_the_direction() -> None:
    nodes = [Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(100.0, 0.0, 60.0))]
    project = Project(ndm=3, ndf=6, nodes=nodes, sections=[_section()], elements=[_frame(1, 1, 2)])
    assert design_members(project)[0].role == "brace"
    assert design_members(project, {1: "beam"})[0].role == "beam"
