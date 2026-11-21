"""The pre-run auto-mesh: T-junctions and crossings, the per-member and project opt-outs."""

from __future__ import annotations

import json

from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node, Project, TrussElement
from opensees_studio.core.mesh import auto_mesh_ids, pre_run_auto_mesh


def _project(*elements: object, nodes: list[Node]) -> Project:
    project = Project(ndm=3, ndf=6)
    project.nodes.extend(nodes)
    project.sections.append(ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6))
    project.elements.extend(elements)  # type: ignore[arg-type]
    return project


def _tee(**beam: object) -> Project:
    """A 10 m beam and a column whose top lands at its middle."""
    return _project(
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1, **beam),
        ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1),
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 3.0)),
            Node(id=2, coords=(10.0, 0.0, 3.0)),
            Node(id=3, coords=(5.0, 0.0, 0.0)),
            Node(id=4, coords=(5.0, 0.0, 3.0)),
        ],
    )


def _cross(**first: object) -> Project:
    return _project(
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1, **first),
        ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1),
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(4.0, 0.0, 4.0)),
            Node(id=3, coords=(0.0, 0.0, 4.0)),
            Node(id=4, coords=(4.0, 0.0, 0.0)),
        ],
    )


def test_a_member_ending_on_another_splits_the_host_at_that_joint() -> None:
    plan = pre_run_auto_mesh(_tee())
    assert plan.removed_element_ids == [1]
    assert not plan.new_nodes  # the column's own top joint is reused
    assert sorted(e.nodes for e in plan.new_elements) == [(1, 4), (4, 2)]


def test_crossing_members_are_both_split_at_one_new_joint() -> None:
    plan = pre_run_auto_mesh(_cross())
    assert plan.removed_element_ids == [1, 2]
    assert len(plan.new_nodes) == 1
    assert plan.new_nodes[0].coords == (2.0, 0.0, 2.0)
    assert len(plan.new_elements) == 4


def test_a_member_with_auto_mesh_off_is_never_split() -> None:
    assert pre_run_auto_mesh(_tee(auto_mesh=False)).is_empty
    plan = pre_run_auto_mesh(_cross(auto_mesh=False))
    assert plan.is_empty


def test_the_project_switch_turns_it_off_for_every_member() -> None:
    project = _tee()
    project.auto_mesh_frames = False
    assert auto_mesh_ids(project) == set()
    assert pre_run_auto_mesh(project).is_empty


def test_pieces_keep_the_option_and_releases_stay_at_the_outer_ends() -> None:
    from opensees_studio.core.geometry.frame_options import EndRelease, FrameReleases

    released = EndRelease(released=("M3",))
    plan = pre_run_auto_mesh(
        _tee(local_axis_angle=30.0, releases=FrameReleases(i=released, j=released))
    )
    first, second = sorted(plan.new_elements, key=lambda e: e.nodes)
    assert first.releases.i == released and first.releases.j == EndRelease()
    assert second.releases.i == EndRelease() and second.releases.j == released
    assert {first.local_axis_angle, second.local_axis_angle} == {30.0}


def test_a_connected_model_has_nothing_to_do() -> None:
    project = _project(
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(1.0, 0.0, 0.0))],
    )
    assert pre_run_auto_mesh(project).is_empty


def test_the_options_are_left_out_of_the_file_at_their_default() -> None:
    project = _tee()
    project.elements.append(TrussElement(id=3, nodes=(1, 3), area=0.01, material_id=1))
    dumped = json.dumps(project.model_dump(mode="json"))
    assert "auto_mesh" not in dumped
    project.auto_mesh_frames = False
    project.elements[0].auto_mesh = False
    project.elements[2].auto_mesh = False
    payload = project.model_dump(mode="json")
    assert payload["auto_mesh_frames"] is False
    assert payload["elements"][0]["auto_mesh"] is False
    assert payload["elements"][2]["auto_mesh"] is False
