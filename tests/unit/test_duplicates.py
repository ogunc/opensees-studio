"""Finding what the model defines twice — and what must not be touched.

The dangerous half of this feature is the one that decides *not* to act: a
bearing joins two coincident nodes on purpose, and a hinge can be two
coincident nodes tied by ``equalDOF``. Both are pinned here.
"""

from __future__ import annotations

import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    EqualDOFConstraint,
    Node,
    PlainLoadPattern,
    Project,
    QuadElement,
    ShellMITC4Element,
    TrussElement,
    ZeroLengthElement,
    ZeroLengthSectionElement,
)
from opensees_studio.core.duplicates import (
    ZERO_LENGTH_CLASSES,
    check_duplicates,
    default_tolerance,
    find_element_clusters,
    find_node_clusters,
)
from opensees_studio.core.geometry.bearings import BEARING_CLASSES


def _section(sid: int = 1, *, name: str = "S") -> ElasticSection:
    return ElasticSection(id=sid, name=name, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6)


def _project(nodes: list[Node], elements: list, **extra: object) -> Project:
    fields: dict[str, object] = {
        "ndm": 3,
        "ndf": 6,
        "nodes": nodes,
        "sections": [_section()],
        "elements": elements,
    }
    fields.update(extra)
    return Project(**fields)  # type: ignore[arg-type]


def _node(node_id: int, coords: tuple[float, float, float] = (0.0, 0.0, 0.0), **kw: object) -> Node:
    return Node(id=node_id, coords=coords, **kw)  # type: ignore[arg-type]


# ──────────────────────────── coincident nodes ────────────────────────────
def test_two_nodes_at_the_same_point_are_one_group() -> None:
    project = _project(
        [_node(1), _node(2), _node(3, (5.0, 0.0, 0.0))],
        [],
    )
    mergeable, exempt = find_node_clusters(project)

    assert exempt == []
    assert len(mergeable) == 1
    assert mergeable[0].keeper_id == 1
    assert mergeable[0].duplicate_ids == (2,)
    assert mergeable[0].coords == (0.0, 0.0, 0.0)


def test_the_lowest_id_is_the_one_that_stays() -> None:
    project = _project([_node(7), _node(3), _node(5)], [])
    (cluster,), _ = find_node_clusters(project)
    assert cluster.keeper_id == 3
    assert cluster.duplicate_ids == (5, 7)


def test_nodes_further_apart_than_the_tolerance_are_left_alone() -> None:
    project = _project([_node(1), _node(2, (0.001, 0.0, 0.0))], [])
    assert find_node_clusters(project, tolerance=1e-6) == ([], [])


def test_the_default_tolerance_follows_the_size_of_the_model() -> None:
    """One part per million of the model's extent, so a model in metres and one
    in millimetres need no different numbers from the user."""
    metres = _project([_node(1), _node(2, (100.0, 0.0, 0.0))], [])
    millimetres = _project([_node(1), _node(2, (100_000.0, 0.0, 0.0))], [])

    assert default_tolerance(metres) == pytest.approx(1e-4)
    assert default_tolerance(millimetres) == pytest.approx(1e-1)

    def two_nodes_a_hair_apart(extent: float) -> Project:
        # A third node gives the model its size; the other two are 0.05 apart.
        return _project(
            [_node(1), _node(2, (0.05, 0.0, 0.0)), _node(3, (extent, 5.0, 0.0))],
            [],
        )

    assert find_node_clusters(two_nodes_a_hair_apart(100_000.0))[0]  # the same node
    assert find_node_clusters(two_nodes_a_hair_apart(100.0)) == ([], [])  # two nodes


def test_an_empty_model_has_nothing_to_compare() -> None:
    project = Project()
    assert default_tolerance(project) > 0.0
    assert check_duplicates(project).is_clean


def test_three_coincident_nodes_make_one_group() -> None:
    project = _project([_node(1), _node(2), _node(3)], [])
    (cluster,), _ = find_node_clusters(project)
    assert cluster.ids == (1, 2, 3)


# ──────────────────────────── deliberate pairs ────────────────────────────
def test_a_zero_length_element_makes_its_pair_deliberate() -> None:
    project = _project(
        [_node(1), _node(2)],
        [ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(1, 2))],
    )
    mergeable, exempt = find_node_clusters(project)

    assert mergeable == []
    assert len(exempt) == 1
    assert "zero-length" in (exempt[0].exempt_reason or "")
    assert not exempt[0].mergeable


def test_a_bearing_is_a_zero_length_element_too() -> None:
    """The rule the exemption exists for: an isolator is two coincident nodes."""
    assert set(BEARING_CLASSES) <= set(ZERO_LENGTH_CLASSES)
    assert ZeroLengthSectionElement in ZERO_LENGTH_CLASSES


def test_nodes_tied_by_equal_dof_are_deliberate() -> None:
    project = _project(
        [_node(1), _node(2)],
        [],
        mp_constraints=[EqualDOFConstraint(retained_node=1, constrained_node=2, dofs=(1, 2))],
    )
    mergeable, exempt = find_node_clusters(project)

    assert mergeable == []
    assert "equalDOF" in (exempt[0].exempt_reason or "")


def test_a_third_coincident_node_is_still_reported_when_the_pair_is_deliberate() -> None:
    """The exemption is about the pair; the extra copy is still a mistake."""
    project = _project(
        [_node(1), _node(2), _node(3)],
        [ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(1, 2))],
    )
    mergeable, exempt = find_node_clusters(project)

    assert mergeable == []  # the whole group shares one reason
    assert len(exempt) == 1


# ──────────────────────────── repeated elements ────────────────────────────
def test_the_same_beam_twice_is_a_duplicate() -> None:
    project = _project(
        [_node(1), _node(2, (1.0, 0.0, 0.0))],
        [
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(1, 2), section_id=1),
        ],
    )
    duplicates, parallel = find_element_clusters(project)

    assert parallel == []
    assert len(duplicates) == 1
    assert duplicates[0].keeper_id == 1
    assert duplicates[0].duplicate_ids == (2,)


def test_a_beam_listed_backwards_is_the_same_beam() -> None:
    project = _project(
        [_node(1), _node(2, (1.0, 0.0, 0.0))],
        [
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(2, 1), section_id=1),
        ],
    )
    duplicates, _ = find_element_clusters(project)
    assert duplicates and duplicates[0].ids == (1, 2)


def test_the_same_nodes_with_a_different_section_are_parallel_not_duplicate() -> None:
    """Two members over one pair of nodes can be a deliberate choice."""
    project = _project(
        [_node(1), _node(2, (1.0, 0.0, 0.0))],
        [
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(1, 2), section_id=2),
        ],
        sections=[_section(1, name="A"), _section(2, name="B")],
    )
    duplicates, parallel = find_element_clusters(project)

    assert duplicates == []
    assert len(parallel) == 1
    assert parallel[0].parallel_only
    assert "1 parallel element group" in check_duplicates(project).summary()


def test_the_same_nodes_with_a_different_material_are_parallel() -> None:
    project = _project(
        [_node(1), _node(2, (1.0, 0.0, 0.0))],
        [
            TrussElement(id=1, nodes=(1, 2), area=1e-3, material_id=1),
            TrussElement(id=2, nodes=(1, 2), area=1e-3, material_id=2),
        ],
    )
    duplicates, parallel = find_element_clusters(project)
    assert duplicates == [] and len(parallel) == 1


def test_a_face_listed_from_another_corner_is_the_same_face() -> None:
    coords = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    project = _project(
        [_node(i + 1, point) for i, point in enumerate(coords)],
        [
            QuadElement(id=1, nodes=(1, 2, 3, 4), thickness=0.2, material_id=1),
            QuadElement(id=2, nodes=(3, 4, 1, 2), thickness=0.2, material_id=1),
        ],
    )
    duplicates, _ = find_element_clusters(project)
    assert duplicates and duplicates[0].duplicate_ids == (2,)


def test_a_shell_and_a_quad_over_the_same_nodes_are_different_elements() -> None:
    coords = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    project = _project(
        [_node(i + 1, point) for i, point in enumerate(coords)],
        [
            QuadElement(id=1, nodes=(1, 2, 3, 4), thickness=0.2, material_id=1),
            ShellMITC4Element(id=2, nodes=(1, 2, 3, 4), section_id=1),
        ],
    )
    duplicates, parallel = find_element_clusters(project)
    assert duplicates == [] and parallel == []


def test_elements_that_only_share_one_node_are_not_a_group() -> None:
    project = _project(
        [
            _node(1),
            _node(2, (1.0, 0.0, 0.0)),
            _node(3, (2.0, 0.0, 0.0)),
        ],
        [
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
        ],
    )
    assert find_element_clusters(project) == ([], [])


# ──────────────────────────── the report ────────────────────────────
def test_the_report_counts_nodes_and_elements_separately() -> None:
    project = _project(
        [
            _node(1),
            _node(2, (1.0, 0.0, 0.0)),
            _node(3),  # a copy of node 1
            _node(4, (1.0, 0.0, 0.0)),  # a copy of node 2
        ],
        [
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(1, 2), section_id=1),  # the same member twice
        ],
    )
    report = check_duplicates(project)

    assert not report.is_clean
    assert report.duplicate_node_count == 2
    assert report.duplicate_element_count == 1
    assert "2 coincident node group(s) (2 node(s) to merge)" in report.summary()
    assert "1 duplicate element group(s) (1 element(s) to remove)" in report.summary()


def test_a_clean_model_says_so() -> None:
    project = _project(
        [_node(1), _node(2, (1.0, 0.0, 0.0))],
        [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
    )
    report = check_duplicates(project)

    assert report.is_clean
    assert report.summary() == "No duplicate nodes or elements found."


def test_patterns_are_not_part_of_duplicate_detection() -> None:
    """A load pattern is not an element; the checker must not walk into it."""
    project = _project(
        [_node(1), _node(2, (1.0, 0.0, 0.0))],
        [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1)],
    )
    assert check_duplicates(project).is_clean
