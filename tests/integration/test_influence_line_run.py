"""Influence lines solved by OpenSees, against Müller-Breslau and statics.

* A simply supported beam: the reaction line is straight from 1 to 0 and the
  midspan moment line a triangle peaking at L/4.
* A two-span continuous beam: the middle reaction with the load at x in the
  first span is x (3L² - x²) / (2L³); 11/16 at the middle of the span.
* A 3D path that turns a corner, walked against the members' own direction.
* The whole thing through the analysis CLI, stored and read back.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    InfluenceLineCase,
    Node,
    Project,
)
from opensees_studio.core.analysis import Axle
from opensees_studio.services import save_project
from opensees_studio.services.influence import influence_line, vehicle_envelope
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.result_store import load_manifest, load_results
from opensees_studio.services.results import InfluenceLineResults

PIN = (True, False, True, False, False, False)
ROLLER = (False, False, True, False, False, False)


def _beam(supports: dict[int, tuple[bool, ...]], xs: list[float]) -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=k + 1, coords=(x, 0.0, 0.0), restraint=supports.get(k + 1, (False,) * 6))
            for k, x in enumerate(xs)
        ],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-4)],
        elements=[
            ElasticBeamColumn(id=k + 1, nodes=(k + 1, k + 2), section_id=1)
            for k in range(len(xs) - 1)
        ],
    )


def _run(project: Project, case: InfluenceLineCase) -> InfluenceLineResults:
    project.analyses.append(case)
    results = OpenSeesRunner(project).run(case)
    assert isinstance(results, InfluenceLineResults)
    return results


def test_simply_supported_beam() -> None:
    span = 10.0
    project = _beam({1: PIN, 3: ROLLER}, [0.0, span / 2, span])
    results = _run(project, InfluenceLineCase(id=1, name="IL", path=[1, 2], stations=10))
    x = results.distances
    reaction = influence_line(project, results, "reaction", 1, "Uz")
    np.testing.assert_allclose(reaction, 1.0 - x / span, atol=1e-12)
    # Midspan moment: the end-j moment of member 1, in the diagram's sign.
    moment = influence_line(project, results, "force", 1, "M3", end="j")
    expected = np.where(x <= span / 2, x / 2, (span - x) / 2)
    np.testing.assert_allclose(np.abs(moment), expected, atol=1e-9)
    # Two 100 kN axles 2 m apart: the midspan moment peaks at P (L - a) / 2.
    found = vehicle_envelope(
        results, np.abs(moment), [Axle(load=100.0), Axle(load=100.0, offset=2.0)]
    )
    assert found.maximum == pytest.approx(100.0 * (span - 2.0) / 2)


def test_two_span_continuous_beam_middle_reaction() -> None:
    span = 8.0
    project = _beam({1: PIN, 3: ROLLER, 5: ROLLER}, [0.0, span / 2, span, 1.5 * span, 2 * span])
    results = _run(project, InfluenceLineCase(id=1, name="IL", path=[1, 2, 3, 4], stations=8))
    reaction = influence_line(project, results, "reaction", 3, "Uz")
    x = results.distances
    first = x <= span
    xi = x[first]
    expected = xi * (3 * span**2 - xi**2) / (2 * span**3)
    np.testing.assert_allclose(reaction[first], expected, rtol=1e-9, atol=1e-12)
    middle = int(np.argmin(np.abs(x - span / 2)))
    assert reaction[middle] == pytest.approx(11 / 16)
    # Symmetric about the middle support.
    np.testing.assert_allclose(reaction, reaction[::-1], atol=1e-12)


def test_a_3d_path_around_a_corner() -> None:
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(4.0, 0.0, 0.0)),
            Node(id=3, coords=(4.0, 3.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=200e9, G=77e9, A=0.01, Iz=1e-4, Iy=1e-4, J=2e-4)],
        # Member 2 is drawn from the tip back to the corner.
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(3, 2), section_id=1),
        ],
    )
    results = _run(project, InfluenceLineCase(id=1, name="IL", path=[1, 2], stations=4))
    vertical = influence_line(project, results, "reaction", 1, "Uz")
    # Whatever the stop, the fixed base carries the whole unit load.
    np.testing.assert_allclose(vertical, 1.0, atol=1e-9)
    torsion = influence_line(project, results, "reaction", 1, "Rx")
    # On the second arm the load's lever arm about X is its distance along Y.
    np.testing.assert_allclose(np.abs(torsion[-4:]), [0.75, 1.5, 2.25, 3.0], atol=1e-9)


def test_through_the_analysis_cli(tmp_path: Path) -> None:
    from opensees_studio.child_cli import analysis_cli_command

    project = _beam({1: PIN, 3: ROLLER}, [0.0, 5.0, 10.0])
    project.analyses.append(InfluenceLineCase(id=4, name="Girder", path=[1, 2], stations=5))
    path = save_project(project, tmp_path / "girder.osmodel")
    out = tmp_path / "out"
    cmd = [*analysis_cli_command(), "--project", str(path), "--cases", "4", "--out", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    entry = load_manifest(out)["cases"][0]
    assert entry["result_type"] == "InfluenceLineResults"
    results = load_results(entry, out)
    assert isinstance(results, InfluenceLineResults)
    assert results.n_steps == 11
    np.testing.assert_allclose(
        influence_line(project, results, "reaction", 3, "Uz"), results.distances / 10.0, atol=1e-12
    )
