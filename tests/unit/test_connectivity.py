"""Connectivity faults, Merge Joints on a subset, and what the mesher splits."""

from __future__ import annotations

from opensees_studio.core import (
    ElasticBeamColumn,
    Node,
    Project,
    ShellMITC4Element,
    TrussElement,
    ZeroLengthElement,
    make_default_section,
)
from opensees_studio.core.connectivity import check_connectivity
from opensees_studio.core.duplicates import find_node_clusters
from opensees_studio.core.mesh import split_bars_at_nodes


def _project() -> Project:
    nodes = [
        Node(id=1, coords=(0, 0, 0)),
        Node(id=2, coords=(4, 0, 0)),
        Node(id=3, coords=(2, 0, 0)),  # inside beam 1
        Node(id=4, coords=(2, 0, 3)),  # top of a column standing on node 3
        Node(id=5, coords=(9, 9, 9)),  # loose
        # a shell 10..13 with node 14 on its bottom edge
        Node(id=10, coords=(0, 5, 0)),
        Node(id=11, coords=(4, 5, 0)),
        Node(id=12, coords=(4, 8, 0)),
        Node(id=13, coords=(0, 8, 0)),
        Node(id=14, coords=(2, 5, 0)),
        Node(id=15, coords=(2, 5, -3)),
    ]
    return Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[make_default_section(1)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1),
            ShellMITC4Element(id=3, nodes=(10, 11, 12, 13), section_id=1),
            TrussElement(id=4, nodes=(14, 15), area=1.0, material_id=1),
        ],
    )


def test_the_three_faults() -> None:
    report = check_connectivity(_project(), tolerance=1e-6)
    assert report.loose_joints == [5]
    assert report.joints_on_bars == [(1, 3)]
    assert report.joints_on_shell_edges == [(3, 14)]
    assert not report.is_clean
    assert "1 loose joint(s)" in report.summary()


def test_a_clean_model() -> None:
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(1, 0, 0))],
        sections=[make_default_section(1)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
    )
    assert check_connectivity(project).summary() == "Every joint is connected."


def test_merging_only_among_the_selected_joints() -> None:
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0)),
            Node(id=2, coords=(0.002, 0, 0)),
            Node(id=3, coords=(5, 0, 0)),
            Node(id=4, coords=(5.002, 0, 0)),
        ],
    )
    everything, _ = find_node_clusters(project, tolerance=0.01)
    assert [c.ids for c in everything] == [(1, 2), (3, 4)]
    selected, _ = find_node_clusters(project, tolerance=0.01, node_ids={3, 4})
    assert [c.ids for c in selected] == [(3, 4)]
    assert find_node_clusters(project, tolerance=0.001)[0] == []


def test_the_mesher_never_splits_a_link() -> None:
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0)),
            Node(id=2, coords=(4, 0, 0)),
            Node(id=3, coords=(2, 0, 0)),
        ],
        elements=[ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(1,))],
    )
    assert split_bars_at_nodes(project).is_empty
