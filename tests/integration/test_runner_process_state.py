"""A run's results do not depend on the models solved before it in the same process.

OpenSeesPy's ``truss`` keeps one class-wide force vector and stiffness matrix
for every truss with six DOFs, 3D with ndf 3 and 2D with ndf 3 alike, and in
2D it never writes their rotation rows. Without the runner clearing them, the
last 3D truss left a moment at the nodes of the next 2D truss with rotations:
in the reactions, and in the solution wherever a frame joint is free to rotate.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    ElasticUniaxial,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    TrussElement,
    TrussSpec,
    build_truss,
    ensure_dead_load_case,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner


def _truss_project(ndm: int, ndf: int) -> Project:
    spec = TrussSpec(
        span=12.0,
        depth=2.0,
        n_panels=6,
        material_id=1,
        chord_area=0.01,
        web_area=0.005,
        plane="XZ",
        unit_weight=77e3,
    )
    truss = build_truss(spec, ndm=ndm, ndf=ndf, first_node_id=1, first_element_id=1)
    project = Project(
        ndm=ndm,
        ndf=ndf,
        nodes=truss.nodes,
        elements=truss.elements,
        materials=[ElasticUniaxial(id=1, E=200e9)],
    )
    pattern = ensure_dead_load_case(project)
    for node in [n for n in truss.nodes if n.coords[2] > 0.0][:3]:
        pattern.nodal_loads.append(
            NodalLoad(node_id=node.id, forces=(0.0, 0.0, -10e3, 0.0, 0.0, 0.0))
        )
    return project


def _reactions(ndm: int, ndf: int, results_dir: Path) -> dict[int, np.ndarray]:
    project = _truss_project(ndm, ndf)
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=results_dir)
    return results.node_reaction


def test_a_2d_truss_with_rotations_ignores_the_3d_trusses_solved_before_it(tmp_path: Path) -> None:
    fresh = _reactions(2, 3, tmp_path / "fresh")
    _reactions(2, 2, tmp_path / "a")
    _reactions(3, 3, tmp_path / "b")
    after = _reactions(2, 3, tmp_path / "after")

    assert fresh.keys() == after.keys()
    for node_id, reaction in fresh.items():
        np.testing.assert_allclose(after[node_id], reaction, rtol=0.0, atol=1e-6)
    # A joint whose rotation is restrained but no member resists carries no moment.
    assert all(abs(r[-1, 2]) < 1e-6 for r in after.values())


def _braced_column(ndm: int, ndf: int) -> Project:
    """A column at node 1 braced by a bar to node 2, pushed sideways at its top, node 3.

    In 3D with three DOFs both members are bars (the top is held out of plane).
    """
    fixed = (True, True, True, True, True, True)
    if ndf == 3 and ndm == 3:
        column = TrussElement(id=1, nodes=(1, 3), area=0.01, material_id=1)
        top = (False, True, False, False, False, False)
        sections = []
    else:
        column = ElasticBeamColumn(id=1, nodes=(1, 3), section_id=1)
        top = (False,) * 6  # free to rotate: the column holds it
        sections = [ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-4)]
    return Project(
        ndm=ndm,
        ndf=ndf,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=fixed),
            Node(id=2, coords=(4.0, 0.0, 0.0), restraint=fixed),
            Node(id=3, coords=(0.0, 0.0, 3.0), restraint=top),
        ],
        materials=[ElasticUniaxial(id=1, E=200e9)],
        sections=sections,
        elements=[column, TrussElement(id=2, nodes=(3, 2), area=0.01, material_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=3, forces=(10e3, 0.0, 0.0, 0.0, 0.0, 0.0))],
            )
        ],
        analyses=[StaticCase(id=1, name="push", pattern_ids=[1])],
    )


def _top_displacement(ndm: int, ndf: int, results_dir: Path) -> np.ndarray:
    project = _braced_column(ndm, ndf)
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=results_dir)
    return results.node_disp[3][-1]


def test_a_braced_2d_column_ignores_the_3d_trusses_solved_before_it(tmp_path: Path) -> None:
    fresh = _top_displacement(2, 3, tmp_path / "fresh")
    _top_displacement(3, 3, tmp_path / "3d")  # the brace, last, has a Z force
    after = _top_displacement(2, 3, tmp_path / "after")

    np.testing.assert_allclose(after, fresh, rtol=1e-12, atol=0.0)
