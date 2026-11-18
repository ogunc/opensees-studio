"""The stage plan: what exists at each stage, and the mistakes it refuses."""

from __future__ import annotations

from opensees_studio.core import (
    ConstructionStage,
    ElasticBeamColumn,
    ElasticSection,
    Node,
    Project,
    StagedCase,
)
from opensees_studio.core.groups import Group
from opensees_studio.core.staging import stage_plan


def _project() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=i, coords=(float(i), 0.0, 0.0)) for i in range(1, 5)],
        sections=[ElasticSection(id=1, E=1.0, A=1.0, Iz=1.0, Iy=1.0, G=1.0, J=1.0)],
        elements=[ElasticBeamColumn(id=i, nodes=(i, i + 1), section_id=1) for i in range(1, 4)],
        groups=[Group(id=1, name="B", element_ids=[2]), Group(id=2, name="C", element_ids=[3])],
    )


def test_elements_of_later_stages_are_pending() -> None:
    case = StagedCase(
        id=1,
        name="s",
        stages=[
            ConstructionStage(add_group_ids=[1]),
            ConstructionStage(add_group_ids=[2], remove_group_ids=[1]),
        ],
    )
    plan = stage_plan(_project(), case)
    assert plan.errors == []
    assert plan.initial == {1}
    assert plan.active_after(-1) == {1}
    assert plan.active_after(0) == {1, 2}
    assert plan.active_after(1) == {1, 3}


def test_mistakes_are_named() -> None:
    case = StagedCase(
        id=1,
        name="s",
        stages=[
            ConstructionStage(remove_group_ids=[2]),
            ConstructionStage(add_group_ids=[2, 9]),
            ConstructionStage(add_group_ids=[2]),
        ],
    )
    errors = " ".join(stage_plan(_project(), case).errors)
    assert "removed before it is built" in errors
    assert "group 9 does not exist" in errors
    assert "added twice" in errors


def test_a_staged_case_saves_without_its_defaults() -> None:
    case = StagedCase(id=1, name="s", stages=[ConstructionStage(pattern_ids=[1])])
    text = case.model_dump_json()
    assert "new_joints" not in text
    assert case.pattern_ids == [1]
