"""Hover text of a joint or an element: what it is, what it carries."""

from __future__ import annotations

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    UniformElementLoad,
)
from opensees_studio.core.hover import MAX_LOAD_LINES, element_summary, node_summary


def _project() -> Project:
    project = Project()
    project.nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
        Node(id=2, coords=(0.0, 0.0, 3.0), mass=(10.0, 10.0, 0.0, 0.0, 0.0, 0.0)),
        Node(id=3, coords=(5.0, 5.0, 5.0)),
    ]
    project.sections = [
        ElasticSection(id=1, name="W10X12", E=2e11, A=0.01, Iz=1e-4, Iy=1e-4, G=8e10, J=1e-5)
    ]
    project.elements = [ElasticBeamColumn(id=7, nodes=(1, 2), section_id=1)]
    project.time_series = [LinearTimeSeries(id=1)]
    project.load_patterns = [
        PlainLoadPattern(
            id=1,
            name="DEAD",
            time_series_id=1,
            nodal_loads=[NodalLoad(node_id=2, forces=(0, 0, -5000.0, 0, 0, 0))],
            element_loads=[UniformElementLoad(element_id=7, wz=-1000.0)],
            point_loads=[PointElementLoad(element_id=7, pz=-1.0, x=0.5)],
        )
    ]
    return project


def test_a_joint_says_where_it_is_and_what_it_carries() -> None:
    text = node_summary(_project(), 1)
    assert text.splitlines()[0] == "Joint 1  (0, 0, 0) m"
    assert "Restraint: fixed (Ux, Uy, Uz, Rx, Ry, Rz)" in text
    assert "Elements: 7" in text
    second = node_summary(_project(), 2)
    assert "Mass: 10, 10, 0, 0, 0, 0" in second
    assert "DEAD: Fz -5000 N" in second
    assert "No element (loose)" in node_summary(_project(), 3)
    assert node_summary(_project(), 99) is None


def test_a_member_says_its_section_length_and_loads() -> None:
    text = element_summary(_project(), 7)
    assert text.splitlines()[:3] == [
        "ElasticBeamColumn 7",
        "Joints 1-2, L = 3 m",
        "Section 1: W10X12",
    ]
    assert "DEAD: uniform wz -1000 N/m (local)" in text
    assert "DEAD: 1 point load(s)" in text
    assert element_summary(_project(), 99) is None


def test_a_2d_joint_shows_x_and_z_and_long_load_lists_are_cut() -> None:
    project = _project().model_copy(update={"ndm": 2, "ndf": 3})
    pattern = project.load_patterns[0]
    pattern.nodal_loads += [
        NodalLoad(node_id=2, forces=(float(i), 0, 0, 0, 0, 0)) for i in range(1, 10)
    ]
    text = node_summary(project, 2)
    assert "(0, 3) m" in text.splitlines()[0]
    assert f"… and {10 - MAX_LOAD_LINES} more load(s)" in text


def test_node_displacements_reads_the_shown_step_with_the_model_dof_labels() -> None:
    import numpy as np

    from opensees_studio.core.hover import node_displacements

    project = Project(ndm=2, ndf=3)
    project.nodes = [Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(3.0, 0.0, 0.0))]

    class _Results:
        def __init__(self) -> None:
            self.node_disp = {2: np.array([[0.0, 0.0, 0.0], [0.006, -0.008, 0.002]])}

    assert node_displacements(project, _Results(), 2) == [
        ("Ux", 0.006, False),
        ("Uz", -0.008, False),
        ("Ry", 0.002, True),
    ]
    assert node_displacements(project, _Results(), 2, step=0) == [
        ("Ux", 0.0, False),
        ("Uz", 0.0, False),
        ("Ry", 0.0, True),
    ]
    assert node_displacements(project, _Results(), 1) is None  # not recorded


def test_node_mode_shape_reads_the_mode_by_its_one_based_number() -> None:
    import numpy as np

    from opensees_studio.core.hover import node_mode_shape

    project = Project(ndm=2, ndf=3)
    project.nodes = [Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(3.0, 0.0, 0.0))]

    class _Modal:
        def __init__(self) -> None:
            self.mode_shapes = {1: {2: np.array([1.0, 0.0, -0.25])}}

    assert node_mode_shape(project, _Modal(), 2, 1) == [
        ("Ux", 1.0, False),
        ("Uz", 0.0, False),
        ("Ry", -0.25, True),
    ]
    assert node_mode_shape(project, _Modal(), 2, 2) is None  # no such mode
    assert node_mode_shape(project, _Modal(), 1, 1) is None  # joint not recorded
