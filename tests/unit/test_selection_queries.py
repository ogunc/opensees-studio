"""Select-menu queries: by type, section, material, load pattern, and inversion."""

from __future__ import annotations

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    ElasticUniaxial,
    FiberSection,
    ForceBeamColumn,
    NodalLoad,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    TrussElement,
)
from opensees_studio.core import selection as q
from opensees_studio.core.sections import Fibre


def _project() -> Project:
    return Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=(4, 0, 0)),
            Node(id=3, coords=(0, 0, 3), mass=(1.0, 1.0, 1.0, 0.0, 0.0, 0.0)),
            Node(id=4, coords=(9, 9, 9)),
        ],
        materials=[ElasticUniaxial(id=1, name="steel", E=1.0), ElasticUniaxial(id=2, E=2.0)],
        sections=[
            ElasticSection(id=1, name="beam", E=1, A=1, Iz=1, Iy=1, G=1, J=1, unit_weight=1.0),
            FiberSection(id=2, name="fibre", fibres=[Fibre(y=0, z=0, area=1, material_id=2)]),
        ],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ForceBeamColumn(id=2, nodes=(1, 3), section_id=2),
            TrussElement(id=3, nodes=(2, 3), area=1.0, material_id=1),
        ],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=3, forces=(1, 0, 0, 0, 0, 0))],
                point_loads=[PointElementLoad(element_id=3 - 1, py=1.0)],
            ),
            PlainLoadPattern(id=2, time_series_id=1, self_weight=1.0),
        ],
    )


def test_by_type() -> None:
    project = _project()
    assert q.element_types(project) == ["ElasticBeamColumn", "ForceBeamColumn", "Truss"]
    assert q.elements_of_type(project, "Truss") == {3}


def test_by_section_lists_only_used_sections() -> None:
    project = _project()
    assert [s.id for s in q.sections_in_use(project)] == [1, 2]
    assert q.elements_with_section(project, 2) == {2}


def test_by_material_reaches_through_a_fibre_section() -> None:
    project = _project()
    assert [m.id for m in q.materials_in_use(project)] == [1, 2]
    assert q.elements_with_material(project, 1) == {3}  # the truss's own material
    assert q.elements_with_material(project, 2) == {2}  # a fibre of the frame's section


def test_by_load_pattern_includes_the_self_weight() -> None:
    project = _project()
    assert q.loaded_by_pattern(project, 1) == ({3}, {2})
    assert q.loaded_by_pattern(project, 2) == (set(), {1})  # only frame 1 has a weight
    assert q.loaded_by_pattern(project, 99) == (set(), set())


def test_node_queries() -> None:
    project = _project()
    assert q.restrained_nodes(project) == {1}
    assert q.nodes_with_mass(project) == {3}
    assert q.nodes_of_elements(project, {1}) == {1, 2}
    assert q.elements_within_nodes(project, {1, 2, 3}) == {1, 2, 3}
    assert q.elements_within_nodes(project, {1, 2}) == {1}


def test_invert() -> None:
    project = _project()
    assert q.invert(project, {1, 2}, {3}) == ({3, 4}, {1, 2})


def test_a_selected_member_brings_its_joints() -> None:
    """Move/copy/mirror act on a member's joints, so the selection must imply them."""
    project = _project()

    joints = q.implied_node_ids(project, node_ids=set(), element_ids={1})

    element = next(e for e in project.elements if e.id == 1)
    assert joints == set(element.nodes)


def test_implied_joints_union_the_explicit_node_selection() -> None:
    project = _project()
    element = next(e for e in project.elements if e.id == 1)
    explicit = {99}

    joints = q.implied_node_ids(project, node_ids=explicit, element_ids={element.id})

    assert joints == set(element.nodes) | explicit


def test_without_elements_the_selection_is_untouched() -> None:
    project = _project()

    assert q.implied_node_ids(project, node_ids={3, 4}, element_ids=set()) == {3, 4}


def test_an_unknown_element_id_adds_nothing() -> None:
    project = _project()

    assert q.implied_node_ids(project, node_ids={1}, element_ids={12345}) == {1}


def test_a_box_takes_a_member_only_when_both_joints_are_inside() -> None:
    """The agreed rule for a rubber-band selection."""
    project = _project()
    element = next(e for e in project.elements if e.id == 1)
    first, second = element.nodes

    assert q.elements_with_nodes_inside(project, {first, second}) == {element.id}
    assert q.elements_with_nodes_inside(project, {first}) == set(), "one end is not enough"
    assert q.elements_with_nodes_inside(project, set()) == set()


def _line_project() -> Project:
    """Two members on a line; the display positions are set by each test."""
    return Project(
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(1.0, 0.0, 0.0)),
            Node(id=3, coords=(5.0, 0.0, 0.0)),
            Node(id=4, coords=(6.0, 0.0, 0.0)),
        ],
        elements=[
            TrussElement(id=1, nodes=(1, 2), material_id=1, area=0.01),
            TrussElement(id=2, nodes=(3, 4), material_id=1, area=0.01),
        ],
    )


def test_a_box_selects_the_joints_inside_and_their_members() -> None:
    project = _line_project()
    display = {1: (0.0, 0.0), 2: (10.0, 0.0), 3: (50.0, 0.0), 4: (60.0, 0.0)}

    nodes, elements = q.box_selection(project, display, (-5.0, 15.0, -5.0, 5.0), crossing=False)

    assert nodes == {1, 2}
    assert elements == {1}


def test_a_member_that_only_crosses_is_left_out_of_a_plain_box() -> None:
    project = _line_project()
    display = {1: (0.0, 0.0), 2: (10.0, 0.0), 3: (50.0, 0.0), 4: (60.0, 0.0)}

    nodes, elements = q.box_selection(project, display, (4.0, 6.0, -5.0, 5.0), crossing=False)

    assert nodes == set()
    assert elements == set(), "no joint is inside, so the member is not taken"


def test_a_crossing_box_takes_a_member_that_cuts_through_it() -> None:
    project = _line_project()
    display = {1: (0.0, 0.0), 2: (10.0, 0.0), 3: (50.0, 0.0), 4: (60.0, 0.0)}

    nodes, elements = q.box_selection(project, display, (4.0, 6.0, -5.0, 5.0), crossing=True)

    assert nodes == set(), "the box touches the edge, not a joint"
    assert elements == {1}


def test_a_crossing_box_still_takes_the_members_with_a_joint_inside() -> None:
    project = _line_project()
    display = {1: (0.0, 0.0), 2: (10.0, 0.0), 3: (50.0, 0.0), 4: (60.0, 0.0)}

    nodes, elements = q.box_selection(project, display, (45.0, 55.0, -5.0, 5.0), crossing=True)

    assert nodes == {3}
    assert elements == {2}


def test_the_two_drag_directions_differ_only_in_what_they_touch() -> None:
    """The same box: downwards takes the whole member, upwards also a crossed one."""
    project = _line_project()
    display = {1: (0.0, 0.0), 2: (10.0, 0.0), 3: (50.0, 0.0), 4: (60.0, 0.0)}
    box = (4.0, 6.0, -5.0, 5.0)

    down_nodes, down_elements = q.box_selection(project, display, box, crossing=False)
    up_nodes, up_elements = q.box_selection(project, display, box, crossing=True)

    assert down_nodes == up_nodes == set()
    assert down_elements == set()
    assert up_elements == {1}


def test_a_box_skips_nodes_and_elements_hidden_in_the_viewport() -> None:
    project = _line_project()
    display = {1: (0.0, 0.0), 2: (10.0, 0.0), 3: (50.0, 0.0), 4: (60.0, 0.0)}

    nodes, elements = q.box_selection(
        project,
        display,
        (-5.0, 65.0, -5.0, 5.0),
        crossing=False,
        hidden_nodes={1, 3},
        hidden_elements={2},
    )

    assert nodes == {2, 4}
    assert elements == {1}, "the visible member stays eligible; the hidden one does not"
