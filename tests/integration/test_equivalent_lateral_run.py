"""ELF loads in a solved model: the supports carry exactly the base shear."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    RigidDiaphragm,
    StaticCase,
    Storey,
)
from opensees_studio.core.equivalent_lateral import (
    ElfParameters,
    equivalent_lateral_forces,
    nodal_forces,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

FIXED = (True,) * 6
PARAMS = ElfParameters(code="asce7_16", period=0.4, sds=1.0, sd1=0.6, r=8.0)


def _frame(diaphragm: bool) -> Project:
    """A 6 x 4 m, two-storey 3D frame, 3 m storeys, 2.5 t per floor joint."""
    nodes: list[Node] = []
    elements: list[ElasticBeamColumn] = []
    plan = ((0.0, 0.0), (6.0, 0.0), (6.0, 4.0), (0.0, 4.0))
    for k, z in enumerate((0.0, 3.0, 6.0)):
        for j, (x, y) in enumerate(plan):
            m = 0.0 if z == 0.0 or diaphragm else 2.5
            nodes.append(
                Node(
                    id=10 * k + j + 1,
                    coords=(x, y, z),
                    restraint=FIXED if z == 0.0 else (False,) * 6,
                    mass=(m, m, 0.0, 0.0, 0.0, 0.0),
                )
            )
    eid = 1
    for k in (1, 2):
        for j in range(4):
            elements.append(
                ElasticBeamColumn(
                    id=eid, nodes=(10 * (k - 1) + j + 1, 10 * k + j + 1), section_id=1
                )
            )
            eid += 1
            elements.append(
                ElasticBeamColumn(
                    id=eid, nodes=(10 * k + j + 1, 10 * k + (j + 1) % 4 + 1), section_id=1
                )
            )
            eid += 1
    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[ElasticSection(id=1, E=3e10, A=0.09, Iz=6.75e-4, Iy=6.75e-4, G=1.2e10, J=1e-3)],
        elements=elements,
        storeys=[Storey(id=1, name="S1", elevation=3.0), Storey(id=2, name="S2", elevation=6.0)],
        time_series=[LinearTimeSeries(id=1)],
    )
    if diaphragm:
        for k in (1, 2):
            retained = 100 + k
            project.nodes.append(
                Node(
                    id=retained, coords=(3.0, 2.0, 3.0 * k), mass=(10.0, 10.0, 0.0, 0.0, 0.0, 43.3)
                )
            )
            project.diaphragms.append(
                RigidDiaphragm(
                    id=k,
                    perp_dirn=3,
                    retained_node=retained,
                    constrained_nodes=tuple(10 * k + j + 1 for j in range(4)),
                )
            )
    return project


@pytest.mark.parametrize("diaphragm", [False, True])
@pytest.mark.parametrize("sign", [0, 1])
def test_the_reactions_add_up_to_the_base_shear(diaphragm: bool, sign: int, tmp_path: Path) -> None:
    project = _frame(diaphragm)
    result = equivalent_lateral_forces(project, 0, PARAMS)
    loads = nodal_forces(project, result, eccentricity_sign=sign, ratio=0.05)
    project.load_patterns.append(
        PlainLoadPattern(
            id=1,
            time_series_id=1,
            nodal_loads=[NodalLoad(node_id=n, forces=f) for n, f in loads.items()],
        )
    )
    project.analyses.append(StaticCase(id=1, name="EQ X", pattern_ids=[1]))
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)
    supports = [n.id for n in project.nodes if n.restraint == FIXED]
    shear_x = -sum(float(results.node_reaction[n][0][0]) for n in supports)
    shear_y = -sum(float(results.node_reaction[n][0][1]) for n in supports)
    assert result.base_shear == pytest.approx(20.0 * 9.80665 / 8.0)
    assert shear_x == pytest.approx(result.base_shear, rel=1e-8)
    assert shear_y == pytest.approx(0.0, abs=1e-8 * result.base_shear)
    if sign:
        # The eccentric load twists the floor: the joints at y = 0 and y = 4 move differently.
        top_near = float(results.node_disp[21][0][0])
        top_far = float(results.node_disp[24][0][0])
        assert top_far > top_near
