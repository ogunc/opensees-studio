"""The model check and OpenSees agree on zeroLength rotational springs.

Two coincident nodes, node 1 fully fixed, node 2 held in translation and joined
to node 1 by an elastic spring of stiffness k; a moment M on node 2 must rotate
it by M / k. The pre-run check has to pass the same model the solver accepts,
in the direction numbering OpenSees uses (1-3 translations, 4-6 rotations; in
2D the rotation about z is direction 6, and OpenSees also reads 3 as 6).
"""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    ElasticUniaxial,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    ZeroLengthElement,
)
from opensees_studio.core.model_check import check_model
from opensees_studio.services.opensees_runner import OpenSeesRunner

K = 100.0
M = 10.0


def _spring(ndm: int, ndf: int, direction: int, slot: int) -> Project:
    held = [True] * 6
    held[slot] = False
    forces = [0.0] * 6
    forces[slot] = M
    return Project(
        ndm=ndm,
        ndf=ndf,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=(0, 0, 0), restraint=tuple(held)),  # type: ignore[arg-type]
        ],
        materials=[ElasticUniaxial(id=1, E=K)],
        elements=[ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(direction,))],
        time_series=[LinearTimeSeries(id=1, name="ramp")],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="moment",
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=tuple(forces))],  # type: ignore[arg-type]
            )
        ],
        analyses=[StaticCase(id=1, name="static", pattern_ids=[1], n_steps=1)],
    )


@pytest.mark.parametrize(
    ("ndm", "ndf", "direction", "slot", "column"),
    [
        (2, 3, 6, 4, 2),  # 2D in this fork: Ry is the third nodal DOF
        (2, 3, 3, 4, 2),
        (3, 6, 4, 3, 3),
        (3, 6, 5, 4, 4),
        (3, 6, 6, 5, 5),
    ],
)
def test_check_passes_and_the_spring_carries_the_moment(
    ndm: int, ndf: int, direction: int, slot: int, column: int
) -> None:
    project = _spring(ndm, ndf, direction, slot)

    report = check_model(project)
    assert report.is_clean, [f.summary() for f in report.findings]

    results = OpenSeesRunner(project).run(project.analyses[0])
    rotation = results.node_disp[2][-1][column]
    assert rotation == pytest.approx(M / K, rel=1e-12)
