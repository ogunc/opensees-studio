"""Join Frames: collinear pieces become one member; a joint with a reason stays."""

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
from opensees_studio.core.geometry.join import join_frames


def _beam_in_pieces(n: int = 3, *, bend: bool = False) -> Project:
    project = Project()
    project.nodes = [Node(id=i + 1, coords=(2.0 * i, 0.0, 3.0)) for i in range(n + 1)]
    if bend:
        project.nodes[-1] = Node(id=n + 1, coords=(2.0 * (n - 1), 2.0, 3.0))
    project.sections = [ElasticSection(id=1, E=2e11, A=0.01, Iz=1e-4, Iy=1e-4, G=8e10, J=1e-5)]
    project.elements = [
        ElasticBeamColumn(id=10 + i, nodes=(i + 1, i + 2), section_id=1) for i in range(n)
    ]
    project.time_series = [LinearTimeSeries(id=1)]
    project.load_patterns = [
        PlainLoadPattern(
            id=1,
            name="DEAD",
            time_series_id=1,
            element_loads=[UniformElementLoad(element_id=10 + i, wz=-5.0) for i in range(n)],
        )
    ]
    return project


def test_a_chain_of_pieces_becomes_one_member_with_one_load() -> None:
    project = _beam_in_pieces()
    report = join_frames(project, {10, 11, 12})
    assert report.joined == 2
    assert [(e.id, e.nodes) for e in project.elements] == [(10, (1, 4))]
    assert sorted(n.id for n in project.nodes) == [1, 4]
    assert [(x.element_id, x.wz) for x in project.load_patterns[0].element_loads] == [(10, -5.0)]


def test_a_reversed_piece_still_joins_and_keeps_the_first_direction() -> None:
    project = _beam_in_pieces(2)
    project.elements[1] = project.elements[1].model_copy(update={"nodes": (3, 2)})
    join_frames(project, {10, 11})
    assert project.elements[0].nodes == (1, 3)


def test_joints_with_a_reason_are_kept_and_named() -> None:
    project = _beam_in_pieces()
    project.nodes[1] = project.nodes[1].model_copy(update={"restraint": (True,) * 6})
    project.load_patterns[0].nodal_loads.append(NodalLoad(node_id=3, forces=(0, 0, -1, 0, 0, 0)))
    report = join_frames(project, {10, 11, 12})
    assert report.joined == 0
    assert report.kept == {2: "it is restrained", 3: "it has a nodal load"}
    assert len(project.elements) == 3


def test_a_bend_a_point_load_or_unselected_member_keeps_the_joint() -> None:
    bent = _beam_in_pieces(2, bend=True)
    assert join_frames(bent, {10, 11}).kept == {2: "the members are not in a straight line"}

    loaded = _beam_in_pieces(2)
    loaded.load_patterns[0].point_loads.append(PointElementLoad(element_id=11, pz=-1.0, x=0.5))
    assert "point" in join_frames(loaded, {10, 11}).kept[2]

    partial = _beam_in_pieces(2)
    assert join_frames(partial, {10}).joined == 0


def test_different_uniform_loads_keep_the_joint() -> None:
    project = _beam_in_pieces(2)
    project.load_patterns[0].element_loads[1] = UniformElementLoad(element_id=11, wz=-7.0)
    assert join_frames(project, {10, 11}).kept == {2: "the members have different uniform loads"}
