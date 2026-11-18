"""Creep and shrinkage of a concrete column against the fib Model Code 2010.

A concrete bar (TDConcreteMC10 from :class:`core.mc2010.Mc2010Concrete`), cast
at time 0, loaded in compression at 28 days and held for ten thousand days in a
time-dependent staged case. Its strain must be the Model Code's: the elastic
strain times ``1 + phi(t, 28)`` plus the shrinkage since casting.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    ConstructionStage,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StagedCase,
    TrussElement,
)
from opensees_studio.core.mc2010 import Mc2010Concrete, tdconcrete_material
from opensees_studio.services.opensees_runner import OpenSeesRunner

MIX = Mc2010Concrete(fcm=38.0, relative_humidity=60.0, h0=200.0, cement="42.5R/52.5N/R")
AREA, STRESS = 0.09, -10e6  # m², Pa: 10 MPa on a 300 mm square column


def _column(duration: float, steps: int) -> tuple[Project, StagedCase]:
    material = tdconcrete_material(MIX, 1, name="C30/37")
    project = Project(
        ndm=2,
        ndf=2,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(0.0, 0.0, 3.0), restraint=(True, False, False, False, False, False)),
        ],
        materials=[material],
        elements=[TrussElement(id=1, nodes=(1, 2), area=AREA, material_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(0, 0, STRESS * AREA, 0, 0, 0))],
            )
        ],
    )
    case = StagedCase(
        id=1,
        name="Sustained",
        time_dependent=True,
        start_time=28.0,
        algorithm="Newton",
        tolerance=1e-12,
        stages=[
            ConstructionStage(
                name="Load at 28 d", pattern_ids=[1], duration=duration, time_steps=steps
            )
        ],
    )
    return project, case


def test_the_column_creeps_and_shrinks_as_the_model_code_says() -> None:
    project, case = _column(9972.0, 400)
    result = OpenSeesRunner(project).run(case)
    strain = result.node_disp[2][-1][1] / 3.0
    ecm = MIX.elastic_modulus * 1e6
    expected = STRESS / ecm * (1.0 + MIX.creep_coefficient(10000.0, 28.0)) + MIX.shrinkage(10000.0)
    assert strain == pytest.approx(expected, rel=0.02)


def test_creep_coefficient_alone() -> None:
    """With shrinkage off, the long-term strain over the elastic one is 1 + phi."""
    project, case = _column(9972.0, 400)
    material = project.materials[0]
    project.materials[0] = material.model_copy(update={"epsba": 0.0, "epsda": 0.0})
    result = OpenSeesRunner(project).run(case)
    elastic = STRESS / (MIX.elastic_modulus * 1e6)
    ratio = result.node_disp[2][-1][1] / 3.0 / elastic
    assert ratio - 1.0 == pytest.approx(MIX.creep_coefficient(10000.0, 28.0), rel=0.02)
