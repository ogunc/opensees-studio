"""A hydrostatic pressure by joint pattern, solved: the supports carry its resultant and moment.

A cantilever wall fixed along its base, meshed so the pressure varies over many
shells, under water to its top. Statics fixes the answer whatever the mesh: the
base reactions add up to ``½ γ H² B`` against the pressure, and their moment
about the base is that force times ``H / 3``.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    ElasticMembranePlateSection,
    JointPattern,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
    ShellMITC4Element,
    StaticCase,
    SurfaceLoad,
)
from opensees_studio.core.joint_patterns import assign, hydrostatic_values
from opensees_studio.services.opensees_runner import OpenSeesRunner

WATER = 9810.0  # N/m³
H, B = 3.0, 2.0
NX, NZ = 4, 6


def _meshed_wall() -> Project:
    nodes: list[Node] = []
    ids: dict[tuple[int, int], int] = {}
    for k in range(NZ + 1):
        for i in range(NX + 1):
            ids[(i, k)] = len(nodes) + 1
            nodes.append(
                Node(
                    id=len(nodes) + 1,
                    coords=(B * i / NX, 0.0, H * k / NZ),
                    restraint=(True,) * 6 if k == 0 else (False,) * 6,
                )
            )
    shells = [
        ShellMITC4Element(
            id=len(ids) + 1 + i + k * NX,
            nodes=(ids[(i, k)], ids[(i + 1, k)], ids[(i + 1, k + 1)], ids[(i, k + 1)]),
            section_id=1,
        )
        for k in range(NZ)
        for i in range(NX)
    ]
    values = hydrostatic_values({n.id: n.coords for n in nodes}, H, WATER)
    return Project(
        nodes=nodes,
        sections=[ElasticMembranePlateSection(id=1, name="Wall", E=3e10, nu=0.2, h=0.25)],
        elements=shells,
        joint_patterns=[assign(JointPattern(id=1, name="WATER"), values, "replace")],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="HYDRO",
                time_series_id=1,
                surface_loads=[
                    SurfaceLoad(element_id=s.id, value=1.0, direction="normal", joint_pattern_id=1)
                    for s in shells
                ],
            )
        ],
        analyses=[StaticCase(id=1, name="HYDRO", pattern_ids=[1])],
    )


def test_the_base_carries_the_hydrostatic_resultant_and_its_moment() -> None:
    project = _meshed_wall()
    results = OpenSeesRunner(project).run(project.analyses[0])
    base = [n for n in project.nodes if n.coords[2] == 0.0]

    force = sum(results.node_reaction[n.id][-1][:3] for n in base)
    resultant = 0.5 * WATER * H**2 * B
    # The normal of nodes 1-2-3-4 in the X-Z plane is -Y: the water pushes along -Y.
    assert force[1] == pytest.approx(resultant, rel=1e-9)
    assert abs(force[0]) < 1e-6 * resultant and abs(force[2]) < 1e-6 * resultant

    moment = sum(results.node_reaction[n.id][-1][3] for n in base)  # about global X
    assert abs(moment) == pytest.approx(resultant * H / 3, rel=1e-9)

    tip = max(project.nodes, key=lambda n: (n.coords[2], n.coords[0]))
    assert results.node_disp[tip.id][-1][1] < 0.0  # the top leans away from the water
    assert np.isfinite(results.node_disp[tip.id][-1]).all()
