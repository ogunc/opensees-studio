"""Line and area springs, solved: closed forms, and what a one-sided spring does.

* A long beam on an elastic foundation under a point load deflects ``P β / 2k``
  under the load (Hetényi), with ``β = (k / 4EI)^¼``.
* A raft on a uniform Winkler bed under a uniform pressure settles ``q / k``.
* On compression-only springs, a pull at one corner lifts that corner off and no
  spring pulls; linear springs pull. Statics holds either way.
* A tension-only tie holds a pull and lets a push go.
"""

from __future__ import annotations

import sys

import numpy as np
import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    AreaSpring,
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    LinearTimeSeries,
    LineSpring,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ShellMITC4Element,
    StaticCase,
    SurfaceLoad,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

PLANE = (True, True, False, False, False, True)


def _case(project: Project, **loads: object) -> Project:
    project.time_series.append(LinearTimeSeries(id=1))
    project.load_patterns.append(PlainLoadPattern(id=1, name="P", time_series_id=1, **loads))  # type: ignore[arg-type]
    project.analyses.append(StaticCase(id=1, name="P", pattern_ids=[1]))
    return project


def test_a_beam_on_an_elastic_foundation_matches_hetenyi() -> None:
    e, inertia, k, p = 2e11, 1e-4, 2e7, 1e5
    beta = (k / (4 * e * inertia)) ** 0.25
    length, pieces = 12 * np.pi / beta, 240  # long enough to be infinite, finely divided
    nodes = [
        Node(
            id=i + 1,
            coords=(length * i / pieces, 0.0, 0.0),
            restraint=(True, True, False, True, False, True),
        )
        for i in range(pieces + 1)
    ]
    section = ElasticSection(id=1, E=e, A=0.01, Iz=inertia, Iy=inertia, G=8e10, J=1e-5)
    beams = [
        ElasticBeamColumn(id=1000 + i, nodes=(i + 1, i + 2), section_id=1) for i in range(pieces)
    ]
    project = Project(
        nodes=nodes,
        sections=[section],
        elements=beams,
        line_springs=[LineSpring(element_id=b.id, stiffness=k, direction="Z") for b in beams],
    )
    middle = pieces // 2 + 1
    _case(project, nodal_loads=[NodalLoad(node_id=middle, forces=(0, 0, -p, 0, 0, 0))])
    results = OpenSeesRunner(project).run(project.analyses[0])

    assert results.node_disp[middle][-1][2] == pytest.approx(-p * beta / (2 * k), rel=2e-3)
    assert sum(results.node_reaction[n.id][-1][2] for n in nodes) == pytest.approx(p, rel=1e-9)


def _raft(
    behaviour: str, *, n: int = 6, size: float = 4.0, h: float = 0.15
) -> tuple[Project, dict]:
    nodes, ids = [], {}
    for j in range(n + 1):
        for i in range(n + 1):
            ids[(i, j)] = len(nodes) + 1
            nodes.append(
                Node(id=len(nodes) + 1, coords=(size * i / n, size * j / n, 0.0), restraint=PLANE)
            )
    shells = [
        ShellMITC4Element(
            id=100 + i + j * n,
            nodes=(ids[(i, j)], ids[(i + 1, j)], ids[(i + 1, j + 1)], ids[(i, j + 1)]),
            section_id=1,
        )
        for j in range(n)
        for i in range(n)
    ]
    project = Project(
        nodes=nodes,
        sections=[ElasticMembranePlateSection(id=1, E=3e10, nu=0.2, h=h)],
        elements=shells,
        area_springs=[
            AreaSpring(element_id=s.id, stiffness=2e7, direction="Z", behaviour=behaviour)  # type: ignore[arg-type]
            for s in shells
        ],
    )
    return project, ids


def test_a_raft_on_a_winkler_bed_settles_q_over_k() -> None:
    project, _ = _raft("both")
    q = -1e4
    _case(
        project,
        surface_loads=[
            SurfaceLoad(element_id=e.id, value=q, direction="Z") for e in project.elements
        ],
    )
    results = OpenSeesRunner(project).run(project.analyses[0])
    settlements = [results.node_disp[n.id][-1][2] for n in project.nodes]
    assert np.allclose(settlements, q / 2e7, rtol=1e-9)


def test_compression_only_springs_let_a_lifted_corner_go_and_never_pull() -> None:
    if sys.platform == "darwin":
        pytest.skip(
            "macOS OpenSees 3.8: the Newton solve returns -3 when the corner lifts off "
            "its compression-only springs; the same model converges on Windows and Linux"
        )

    def run(behaviour: str) -> tuple[Project, dict, object]:
        project, ids = _raft(behaviour)
        corner = ids[(6, 6)]
        _case(
            project,
            surface_loads=[
                SurfaceLoad(element_id=e.id, value=-1e3, direction="Z") for e in project.elements
            ],
            nodal_loads=[NodalLoad(node_id=corner, forces=(0, 0, 8e3, 0, 0, 0))],
        )
        return project, ids, OpenSeesRunner(project).run(project.analyses[0])

    linear, ids, lin = run("both")
    pulls = [n.id for n in linear.nodes if lin.node_reaction[n.id][-1][2] < -1e-6]
    assert pulls  # linear springs hold the corner down by pulling

    project, ids, res = run("compression")
    corner = ids[(6, 6)]
    reactions = [res.node_reaction[n.id][-1][2] for n in project.nodes]
    assert min(reactions) >= -1e-6  # no compression-only spring pulls
    assert res.node_reaction[corner][-1][2] == pytest.approx(0.0, abs=1e-6)
    assert res.node_disp[corner][-1][2] > 0.0  # it lifted
    assert sum(reactions) == pytest.approx(16 * 1e3 - 8e3, rel=1e-9)
    assert any("Newton" in w for w in res.warnings)
    assert any("let go" in w for w in res.warnings)


def test_a_tension_only_tie_holds_a_pull_and_lets_a_push_go() -> None:
    def run(force: float) -> float:
        section = ElasticSection(id=1, E=2e11, A=0.01, Iz=1e-4, Iy=1e-4, G=8e10, J=1e-5)
        project = Project(
            nodes=[
                Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
                Node(
                    id=2, coords=(2.0, 0.0, 0.0), restraint=(False, True, False, True, True, True)
                ),
            ],
            sections=[section],
            elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
            # A soft axial bed on the bar, tension only: the medium on the -X side.
            line_springs=[
                LineSpring(element_id=1, stiffness=1e6, direction="X", behaviour="tension")
            ],
        )
        _case(project, nodal_loads=[NodalLoad(node_id=2, forces=(force, 0, 0, 0, 0, 0))])
        results = OpenSeesRunner(project).run(project.analyses[0])
        return float(results.node_reaction[2][-1][0])

    # The medium is on the -X side: pulling node 2 along +X, away from it, stretches
    # the tie, which holds; pushing it toward the medium slackens it.
    assert run(1e4) < -1.0  # a reaction against the pull
    assert run(-1e4) == pytest.approx(0.0, abs=1e-6)
