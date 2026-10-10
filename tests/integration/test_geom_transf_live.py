"""Every offered geometric transformation runs in the live build and changes the result."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    GEOM_TRANSF_TYPES,
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
)
from opensees_studio.services import load_project
from opensees_studio.services.opensees_runner import OpenSeesRunner

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
E, A, IZ, L, H, P = 2e8, 0.01, 1e-4, 3.0, 10.0, -500.0


def _cantilever(ndm: int, transf: str) -> Project:
    ndf = 3 if ndm == 2 else 6
    top = (0.0, L, 0.0) if ndm == 2 else (0.0, 0.0, L)
    load = (H, P, 0.0, 0.0, 0.0, 0.0) if ndm == 2 else (H, 0.0, P, 0.0, 0.0, 0.0)
    return Project(
        ndm=ndm,
        ndf=ndf,
        nodes=[Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6), Node(id=2, coords=top)],
        sections=[ElasticSection(id=1, E=E, A=A, Iz=IZ, Iy=IZ, G=8e7, J=2e-4)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1, geom_transf=transf)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1, time_series_id=1, nodal_loads=[NodalLoad(node_id=2, forces=load)]
            )
        ],
        analyses=[
            StaticCase(
                id=1,
                pattern_ids=[1],
                n_steps=10,
                load_factor_increment=0.1,
                algorithm="Newton",
                tolerance=1e-10,
                max_iter=50,
            )
        ],
    )


@pytest.mark.parametrize("ndm", [2, 3])
def test_each_transformation_runs_and_takes_effect(ndm: int) -> None:
    tip = {}
    for transf in GEOM_TRANSF_TYPES:
        project = _cantilever(ndm, transf)
        tip[transf] = OpenSeesRunner(project).run(project.analyses[0]).disp(2, 1)
    assert tip["Linear"] == pytest.approx(H * L**3 / (3 * E * IZ), rel=1e-12)
    # The compressive load amplifies the sway under PDelta and Corotational.
    assert tip["PDelta"] > tip["Linear"] * 1.05
    assert tip["Corotational"] > tip["Linear"] * 1.05
    assert tip["PDelta"] != tip["Corotational"]


def test_rc_frame_gravity_with_pdelta_columns_runs_in_the_live_build() -> None:
    linear = load_project(EXAMPLES / "rc_frame_gravity.osmodel")
    pdelta = load_project(EXAMPLES / "rc_frame_gravity.osmodel")
    pdelta.elements = [
        el.model_copy(update={"geom_transf": "PDelta"}) if el.id in (1, 2) else el
        for el in pdelta.elements
    ]
    case = linear.analyses[0]
    a = OpenSeesRunner(linear).run(case)
    b = OpenSeesRunner(pdelta).run(case)
    assert a.n_steps == b.n_steps == case.n_steps
    # Symmetric gravity: no sway, and the vertical response stays close.
    assert b.disp(3, 2) == pytest.approx(a.disp(3, 2), rel=1e-3)
