"""Support springs solved by OpenSees, against closed forms."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    ModalCase,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

E, INERTIA, L = 2e8, 1e-4, 3.0
SECTION = ElasticSection(id=1, E=E, A=0.01, Iz=INERTIA, Iy=INERTIA, G=8e7, J=1e-4)


def _static(nodes: list[Node], forces: tuple[float, ...], ndm: int, ndf: int) -> Project:
    return Project(
        ndm=ndm,
        ndf=ndf,
        nodes=nodes,
        sections=[SECTION],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1, time_series_id=1, nodal_loads=[NodalLoad(node_id=2, forces=forces)]
            )
        ],
        analyses=[StaticCase(id=1, name="push", pattern_ids=[1])],
    )


def _run(project: Project, tmp_path: Path):  # type: ignore[no-untyped-def]
    return OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)


def test_a_cantilever_propped_by_a_lateral_spring_2d(tmp_path: Path) -> None:
    k, p = 5e3, 10.0
    project = _static(
        [
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(0.0, 0.0, L), spring=(k, 0.0, 0.0, 0.0, 0.0, 0.0)),
        ],
        (p, 0.0, 0.0, 0.0, 0.0, 0.0),
        2,
        3,
    )
    results = _run(project, tmp_path)
    u = p / (3 * E * INERTIA / L**3 + k)
    assert float(results.node_disp[2][-1][0]) == pytest.approx(u, rel=1e-9)
    # The spring force is the joint's reaction; the two reactions balance P.
    assert float(results.node_reaction[2][-1][0]) == pytest.approx(-k * u, rel=1e-9)
    total = float(results.node_reaction[1][-1][0] + results.node_reaction[2][-1][0])
    assert total == pytest.approx(-p, rel=1e-9)


def test_a_rotational_base_spring_3d(tmp_path: Path) -> None:
    kr, p = 2e3, 4.0
    base = (True, True, True, True, False, True)  # Ry left to the spring
    project = _static(
        [
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=base, spring=(0, 0, 0, 0, kr, 0)),
            Node(id=2, coords=(0.0, 0.0, L)),
        ],
        (p, 0.0, 0.0, 0.0, 0.0, 0.0),
        3,
        6,
    )
    results = _run(project, tmp_path)
    tip = p * L**3 / (3 * E * INERTIA) + p * L / kr * L
    assert float(results.node_disp[2][-1][0]) == pytest.approx(tip, rel=1e-9)
    assert float(results.node_reaction[1][-1][4]) == pytest.approx(-p * L, rel=1e-9)


def test_a_mass_on_springs_vibrates_at_root_k_over_m(tmp_path: Path) -> None:
    k, m = 400.0, 4.0
    project = Project(
        ndm=2,
        ndf=2,
        nodes=[
            Node(
                id=1,
                coords=(0.0, 0.0, 0.0),
                mass=(m, 0.0, m, 0.0, 0.0, 0.0),
                spring=(k, 0.0, 4 * k, 0.0, 0.0, 0.0),
            )
        ],
        analyses=[ModalCase(id=1, name="modal", n_modes=2)],
    )
    results = _run(project, tmp_path)
    omegas = sorted(math.sqrt(v) for v in results.eigenvalues)
    assert omegas == pytest.approx([math.sqrt(k / m), math.sqrt(4 * k / m)], rel=1e-9)
