"""Sections from the Section Designer solve with the stiffness of their geometry.

A cantilever of a drawn I-shape deflects ``P L³ / (3 E Iz)`` with the drawing's
Iz, as an elastic section and as a fibre section of an elastic material (whose
fibres carry the area exactly and Iz to the grid's accuracy).
"""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticUniaxial,
    ForceBeamColumn,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    StaticCase,
)
from opensees_studio.core.sections.drawing import elastic_section, fiber_section, run_command
from opensees_studio.core.sections.geometry import section_properties
from opensees_studio.services.opensees_runner import OpenSeesRunner

E = 200e9
LENGTH = 4.0
LOAD = 1000.0


def _tip(section, element) -> float:  # type: ignore[no-untyped-def]
    project = Project(
        meta=ProjectMeta(),
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, True, False)),
            Node(id=2, coords=(0.0, 0.0, LENGTH)),
        ],
        materials=[ElasticUniaxial(id=1, E=E)],
        sections=[section],
        elements=[element],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(LOAD, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[StaticCase(id=1, name="tip", pattern_ids=[1])],
    )
    results = OpenSeesRunner(project).run(project.analyses[0])
    return float(results.node_disp[2][-1][0])


def test_drawn_section_as_elastic_and_fibre() -> None:
    regions = run_command("ishape 0.3 0.15 0.012 0.008", []).regions
    regions = run_command("hole rect 0.004 0.1 0 0", regions).regions  # a slot in the web
    iz = section_properties(regions).Iz
    expected = LOAD * LENGTH**3 / (3 * E * iz)
    elastic = elastic_section(regions, section_id=1, name="I", modulus=E)
    assert _tip(elastic, ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)) == pytest.approx(
        expected, rel=1e-6
    )
    fiber = fiber_section(regions, section_id=1, name="I", material_id=1, cells=60)
    assert _tip(fiber, ForceBeamColumn(id=1, nodes=(1, 2), section_id=1)) == pytest.approx(
        expected, rel=0.02
    )
