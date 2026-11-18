"""The element window's data from a solved, uniformly loaded beam."""

from __future__ import annotations

from pathlib import Path

import numpy as np
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
    StaticCase,
    UniformElementLoad,
)
from opensees_studio.services.element_diagrams import element_diagram_bundle
from opensees_studio.services.element_forces import ForceComponent
from opensees_studio.services.opensees_runner import OpenSeesRunner

E = 2.0e8
A = 0.02
I_SEC = 2.0e-4
L = 6.0
W = 10.0


def _simply_supported() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(
                id=1,
                coords=(0.0, 0.0, 0.0),
                restraint=(True, False, True, False, False, False),
            ),
            Node(
                id=2,
                coords=(L, 0.0, 0.0),
                restraint=(False, False, True, False, False, False),
            ),
        ],
        sections=[ElasticSection(id=1, E=E, A=A, Iz=I_SEC)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=1, wy=-W)],
            )
        ],
        analyses=[StaticCase(id=1, name="static", n_steps=1, pattern_ids=[1])],
    )


def test_a_solved_beam_gives_its_moment_deformation_and_load_curves(tmp_path: Path) -> None:
    project = _simply_supported()
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)

    bundle = element_diagram_bundle(project, results, 1, stations=True)

    moment = next(item for item in bundle.forces if item.component is ForceComponent.M3)
    assert np.max(np.abs(moment.values)) == pytest.approx(W * L**2 / 8.0, rel=1e-5)

    assert bundle.absolute is not None and bundle.relative is not None
    mid = len(bundle.relative[0]) // 2
    expected = 5.0 * W * L**4 / (384.0 * E * I_SEC)
    # The moment diagram is sampled at 25 stations; the double integration is
    # within a fraction of a per cent of the closed-form quartic.
    assert bundle.relative[1][mid] == pytest.approx(expected, rel=2e-3)
    assert bundle.absolute[1][mid] == pytest.approx(expected, rel=2e-3)
    assert bundle.relative[0][mid] == pytest.approx(L / 2.0, rel=1e-9)

    assert len(bundle.segments) == 1
    segment = bundle.segments[0]
    assert (segment.x0, segment.x1) == pytest.approx((0.0, L))
    assert segment.w0[1] == pytest.approx(-W, rel=1e-9)
    assert segment.w1[1] == pytest.approx(-W, rel=1e-9)
    assert bundle.points == ()

    assert not any("interpolates the end rotations" in note for note in bundle.notes)


def test_a_3d_cantilever_uses_the_m2_curvature_for_its_absolute_curve(tmp_path: Path) -> None:
    """A load along local z is carried by M2; the sign must keep the chord."""
    tip = 10.0
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(L, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=E, A=A, Iz=I_SEC, Iy=I_SEC, G=8e7, J=3e-4)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(0.0, 0.0, -tip, 0.0, 0.0, 0.0))],
            )
        ],
        analyses=[StaticCase(id=1, name="cantilever-3d", n_steps=1, pattern_ids=[1])],
    )
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)

    bundle = element_diagram_bundle(project, results, 1, stations=True)

    assert bundle.absolute is not None and bundle.relative is not None
    mid = len(bundle.absolute[0]) // 2
    tip_deflection = tip * L**3 / (3.0 * E * I_SEC)
    mid_deflection = 5.0 * tip * L**3 / (48.0 * E * I_SEC)
    assert bundle.absolute[1][mid] == pytest.approx(mid_deflection, rel=2e-3)
    assert bundle.relative[1][mid] == pytest.approx(
        abs(mid_deflection - tip_deflection / 2.0), rel=2e-3
    )
    assert results.node_disp[2][-1, 2] == pytest.approx(-tip_deflection, rel=2e-3)


def test_a_cantilever_absolute_curve_keeps_the_chord_sign(tmp_path: Path) -> None:
    """A tip load bends a cantilever; the chord is part of the absolute curve."""
    tip = 10.0
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(L, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=E, A=A, Iz=I_SEC)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(0.0, 0.0, -tip, 0.0, 0.0, 0.0))],
            )
        ],
        analyses=[StaticCase(id=1, name="cantilever", n_steps=1, pattern_ids=[1])],
    )
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)

    bundle = element_diagram_bundle(project, results, 1, stations=True)

    assert bundle.absolute is not None and bundle.relative is not None
    mid = len(bundle.absolute[0]) // 2
    tip_deflection = tip * L**3 / (3.0 * E * I_SEC)
    mid_deflection = 5.0 * tip * L**3 / (48.0 * E * I_SEC)
    assert bundle.absolute[1][mid] == pytest.approx(mid_deflection, rel=2e-3)
    assert bundle.relative[1][mid] == pytest.approx(
        abs(mid_deflection - tip_deflection / 2.0), rel=2e-3
    )
    assert results.node_disp[2][-1, 1] == pytest.approx(-tip_deflection, rel=2e-3)
