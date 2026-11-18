"""Staged construction against closed forms.

* A column built storey by storey, each storey loaded as it is finished: with
  new joints at their design position, the shortening of level k since it was
  built is ``k (N - k + 1) P h / EA`` — largest at mid-height, not at the top as
  in a one-shot analysis. With ``new_joints="follow"`` the total displacement of
  this statically determinate column equals the one-shot analysis.
* A beam on a temporary prop, loaded, then the prop removed: superposition says
  the end state is the beam without the prop under the same load,
  ``5 w L^4 / 384 EI`` at midspan.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    ConstructionStage,
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StagedCase,
    StaticCase,
    TrussElement,
    UniformElementLoad,
)
from opensees_studio.core.groups import Group
from opensees_studio.core.materials import ElasticUniaxial
from opensees_studio.services.opensees_runner import OpenSeesRunner

N, H, EA, P = 4, 3.0, 1e6, 100.0
FIXED = (True,) * 6
FREE = (False,) * 6


def _column() -> Project:
    nodes = [
        Node(id=i + 1, coords=(0.0, 0.0, H * i), restraint=FIXED if i == 0 else FREE)
        for i in range(N + 1)
    ]
    return Project(
        ndm=2,
        ndf=3,
        nodes=nodes,
        sections=[ElasticSection(id=1, E=EA, A=1.0, Iz=1.0, Iy=1.0, G=1.0, J=1.0)],
        elements=[
            ElasticBeamColumn(id=i + 1, nodes=(i + 1, i + 2), section_id=1) for i in range(N)
        ],
        groups=[Group(id=i + 1, name=f"Storey {i + 1}", element_ids=[i + 1]) for i in range(N)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=i + 1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=i + 2, forces=(0, 0, -P, 0, 0, 0))],
            )
            for i in range(N)
        ],
    )


def _stages() -> list[ConstructionStage]:
    return [
        ConstructionStage(name=f"Storey {i + 1}", add_group_ids=[i + 1], pattern_ids=[i + 1])
        for i in range(N)
    ]


def test_column_shortening_since_built_peaks_at_mid_height() -> None:
    project = _column()
    result = OpenSeesRunner(project).run(StagedCase(id=1, name="Build", stages=_stages()))
    assert result.n_steps == N
    unit = P * H / EA
    for k in range(1, N + 1):
        # Each storey is cast to fill the gap down to the shortened level below, so it
        # is h + u long, not h: a 1e-4 effect here.
        assert result.node_disp[k + 1][-1][1] == pytest.approx(-k * (N - k + 1) * unit, rel=1e-3)
    # Base reaction grows storey by storey; a joint not built yet has no displacement.
    assert [result.node_reaction[1][s][1] for s in range(N)] == pytest.approx([100, 200, 300, 400])
    assert result.node_disp[N + 1][0][1] == 0.0


def test_following_joints_reproduce_the_one_shot_column() -> None:
    project = _column()
    staged = OpenSeesRunner(project).run(
        StagedCase(id=1, name="Build", stages=_stages(), new_joints="follow")
    )
    once = OpenSeesRunner(project).run(StaticCase(id=2, name="Once", pattern_ids=[1, 2, 3, 4]))
    for k in range(2, N + 2):
        assert staged.node_disp[k][-1][1] == pytest.approx(once.node_disp[k][-1][1], rel=1e-9)


def test_removing_the_prop_leaves_the_unpropped_beam() -> None:
    span, w, e, inertia = 8.0, -10e3, 30e9, 1e-3
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, False, False)),
        Node(id=2, coords=(span / 2, 0.0, 0.0)),
        Node(id=3, coords=(span, 0.0, 0.0), restraint=(False, False, True, False, False, False)),
        Node(id=4, coords=(span / 2, 0.0, -3.0), restraint=FIXED),
    ]
    project = Project(
        ndm=2,
        ndf=3,
        nodes=nodes,
        materials=[ElasticUniaxial(id=1, E=200e9)],
        sections=[ElasticSection(id=1, E=e, A=0.1, Iz=inertia, Iy=inertia, G=1e10, J=1e-3)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
            TrussElement(id=3, nodes=(4, 2), area=0.01, material_id=1),
        ],
        groups=[Group(id=1, name="Prop", element_ids=[3])],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=k, wy=w) for k in (1, 2)],
            )
        ],
    )
    case = StagedCase(
        id=1,
        name="Pour, then strike the prop",
        stages=[
            ConstructionStage(name="Pour", pattern_ids=[1]),
            ConstructionStage(name="Strike", remove_group_ids=[1]),
        ],
    )
    result = OpenSeesRunner(project).run(case)
    propped, struck = result.node_disp[2][0][1], result.node_disp[2][1][1]
    assert abs(propped) < 0.05 * abs(struck)  # the prop carries the load at first
    expected = 5 * w * span**4 / (384 * e * inertia)
    assert struck == pytest.approx(expected, rel=1e-6)
    assert result.node_reaction[4][1][1] == pytest.approx(0.0, abs=1e-6)
    assert 3 not in result.element_forces or result.element_forces[3][1] == pytest.approx(0.0)


def test_a_load_on_an_element_that_does_not_exist_yet_is_refused() -> None:
    project = _column()
    project.load_patterns[0].element_loads.append(UniformElementLoad(element_id=4, wy=-1.0))
    with pytest.raises(ValueError, match="do not exist in that stage"):
        OpenSeesRunner(project).run(StagedCase(id=1, name="Build", stages=_stages()))
