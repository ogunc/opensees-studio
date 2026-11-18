"""Every truss the wizard builds is stable and in equilibrium, in every model it allows."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticUniaxial,
    LinearTimeSeries,
    NodalLoad,
    PlainLoadPattern,
    Project,
    StaticCase,
    TrussSpec,
    TrussType,
    build_truss,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

CASES = list(itertools.product([(2, 2), (2, 3), (3, 3), (3, 6)], list(TrussType), [None, 0.0, 0.5]))


@pytest.mark.parametrize(("model", "truss_type", "end_depth"), CASES)
def test_the_truss_carries_a_load_on_every_top_node(
    model, truss_type, end_depth, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    ndm, ndf = model
    pitched_warren = truss_type is TrussType.WARREN and end_depth is not None
    plane = "XZ"  # Z up, in 2D (the X-Z plane) and 3D
    spec = TrussSpec(
        span=12.0,
        depth=2.0,
        n_panels=5 if pitched_warren else 6,
        material_id=1,
        chord_area=0.01,
        web_area=0.005,
        truss_type=truss_type,
        end_depth=end_depth,
        plane=plane,
    )
    truss = build_truss(spec, ndm=ndm, ndf=ndf, first_node_id=1, first_element_id=1)
    up = 2
    tops = [node for node in truss.nodes if node.coords[up] > 0.0]
    loads = []
    for node in tops:
        force = [0.0] * 6
        force[up] = -1000.0
        loads.append(NodalLoad(node_id=node.id, forces=tuple(force)))  # type: ignore[arg-type]
    project = Project(
        ndm=ndm,
        ndf=ndf,
        nodes=truss.nodes,
        elements=truss.elements,
        materials=[ElasticUniaxial(id=1, E=200e9)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1, nodal_loads=loads)],
        analyses=[StaticCase(id=1, name="g", pattern_ids=[1])],
    )

    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)

    supports = [node.id for node in truss.nodes if node.restraint[up]]
    col = 1 if ndm == 2 else 2  # result columns follow the DOFs: a 2D model is (Ux, Uz, ...)
    reaction = sum(float(results.node_reaction[n][0][col]) for n in supports)
    assert reaction == pytest.approx(1000.0 * len(tops), rel=1e-9)
