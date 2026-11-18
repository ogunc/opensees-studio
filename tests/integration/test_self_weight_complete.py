"""Every kind of weighted member, solved together: the supports carry the total weight."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    BeamWithHingesElement,
    DispBeamColumn,
    ElasticUniaxial,
    FiberSection,
    ForceBeamColumn,
    Node,
    Project,
    TrussElement,
    ensure_dead_load_case,
    total_self_weight,
)
from opensees_studio.core.sections import (
    AggregatorDOF,
    RectangularPatch,
    SectionAggregator,
    StraightLayer,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner


def test_fiber_aggregated_hinged_and_truss_members_rest_their_weight_on_the_supports(
    tmp_path: Path,
) -> None:
    project = Project(ndm=3, ndf=6)
    ensure_dead_load_case(project)
    project.materials += [ElasticUniaxial(id=1, E=30e9), ElasticUniaxial(id=2, E=200e9)]
    project.sections += [
        FiberSection(
            id=1,
            unit_weight=24e3,
            patches=[
                RectangularPatch(
                    material_id=1, n_fib_y=8, n_fib_z=8, y_i=-0.2, z_i=-0.15, y_j=0.2, z_j=0.15
                )
            ],
            layers=[
                StraightLayer(
                    material_id=2,
                    n_bars=3,
                    bar_area=3e-4,
                    y_start=-0.15,
                    z_start=0.1,
                    y_end=0.15,
                    z_end=0.1,
                )
            ],
        ),
        SectionAggregator(id=2, section_id=1, pairings=[AggregatorDOF(material_id=1, dof="T")]),
    ]
    fixed = (True,) * 6
    project.nodes += [
        Node(id=1, coords=(0, 0, 0), restraint=fixed),
        Node(id=2, coords=(0, 0, 3)),
        Node(id=3, coords=(5, 0, 3)),
        Node(id=4, coords=(5, 0, 0), restraint=fixed),
        Node(id=5, coords=(0, 4, 3), restraint=fixed),
    ]
    project.elements += [
        ForceBeamColumn(id=1, nodes=(1, 2), section_id=1),
        DispBeamColumn(id=2, nodes=(4, 3), section_id=2),
        BeamWithHingesElement(
            id=3,
            nodes=(2, 3),
            section_i_id=1,
            section_j_id=1,
            lp_i=0.3,
            lp_j=0.3,
            E=30e9,
            A=0.12,
            Iz=1e-3,
            Iy=1e-3,
            G=12e9,
            J=1e-3,
            unit_weight=24e3,
        ),
        TrussElement(id=4, nodes=(3, 5), area=0.002, material_id=2, unit_weight=77e3),
    ]

    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)

    supports = [n.id for n in project.nodes if any(n.restraint)]
    weight = total_self_weight(project)
    assert weight == pytest.approx(
        24e3 * 0.1209 * (3 + 3) + 24e3 * 0.12 * 5 + 77e3 * 0.002 * 6.4031242374328485
    )
    vertical = sum(float(results.node_reaction[n][0][2]) for n in supports)
    assert vertical == pytest.approx(weight, rel=1e-9)
    for axis in (0, 1):
        horizontal = sum(float(results.node_reaction[n][0][axis]) for n in supports)
        assert horizontal == pytest.approx(0.0, abs=weight * 1e-9)
