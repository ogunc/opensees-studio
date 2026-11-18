"""Section cut geometry and references, without OpenSees."""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    Group,
    Node,
    Project,
    SectionCut,
)
from opensees_studio.core.section_cuts import cut_geometry, cut_resultant


def _project(**kwargs) -> Project:  # type: ignore[no-untyped-def]
    return Project(
        ndm=3,
        ndf=6,
        nodes=[Node(id=i, coords=(2.0 * i, 0.0, 0.0)) for i in (1, 2, 3)],
        sections=[ElasticSection(id=1, E=1.0, A=1.0, Iz=1.0, Iy=1.0, G=1.0, J=1.0)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
        ],
        groups=[Group(id=1, name="g", node_ids=[2], element_ids=[1, 2])],
        **kwargs,
    )


def test_geometry_takes_the_group_elements_at_the_group_joints() -> None:
    project = _project()
    geometry = cut_geometry(project, SectionCut(id=1, group_id=1))
    assert geometry.members == ((1, (1,)), (2, (0,)))
    assert geometry.joints == (2,) and geometry.centre == (4.0, 0.0, 0.0)
    typed = cut_geometry(project, SectionCut(id=1, group_id=1, centre=(0.0, 0.0, 1.0)))
    assert typed.centre == (0.0, 0.0, 1.0)


def test_two_elements_meeting_at_a_free_joint_cancel() -> None:
    project = _project()
    geometry = cut_geometry(project, SectionCut(id=1, group_id=1))
    end = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    forces = {1: np.concatenate([-end, end]), 2: np.concatenate([-end, end])}
    nodes = {e.id: e.nodes for e in project.elements}
    coords = {n.id: n.coords for n in project.nodes}
    # Element 1 at its j end gives +end, element 2 at its i end -end: nothing passes.
    assert cut_resultant(geometry, nodes, forces, coords, 3, 6) == pytest.approx(np.zeros(6))


def test_a_cut_on_a_missing_group_is_a_reference_problem() -> None:
    project = _project(section_cuts=[SectionCut(id=1, name="S", group_id=7)])
    with pytest.raises(ValueError, match="missing group 7"):
        project.validate_references()


def test_no_cuts_no_key() -> None:
    assert "section_cuts" not in _project().model_dump()
