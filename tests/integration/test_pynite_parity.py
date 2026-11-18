"""The PyNite engine against OpenSees: the same elastic models, the same numbers.

Every result family the application reads from a static case — nodal
displacements and reactions, frame ``localForce`` and truss end forces — is
compared in OpenSees' layout, on 2D and 3D frames with uniform, trapezoidal,
point and nodal loads, self weight, a moment release, support springs and two
load steps, and on trusses. P-Delta is checked against the closed form instead:
a single OpenSees element with a ``PDelta`` transformation leaves out the
member's own P-delta, PyNite's iteration is the closer of the two.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")
pytest.importorskip("Pynite")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticUniaxial,
    NodalLoad,
    Node,
    PointElementLoad,
    Project,
    TrussSpec,
    UniformElementLoad,
    build_truss,
    ensure_dead_load_case,
    make_default_section,
)
from opensees_studio.core.geometry.frame_options import EndRelease, FrameReleases
from opensees_studio.core.loads import TrapezoidalElementLoad
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.persistence import save_project
from opensees_studio.services.pynite_runner import PyNiteRunner
from opensees_studio.services.result_store import load_results

RTOL = 1e-7


def _frame(ndm: int) -> Project:
    project = Project(ndm=ndm, ndf=3 if ndm == 2 else 6)
    ensure_dead_load_case(project)
    project.sections.append(make_default_section(1))
    points = {1: (0, 0, 0), 2: (0, 0, 3), 3: (5, 0, 4), 4: (10, 0, 3), 5: (10, 0, 0)}
    if ndm == 3:
        points.update({6: (0, 4, 3), 7: (0, 4, 0)})
    for nid, xyz in points.items():
        fixed = nid in (1, 5, 7)
        project.nodes.append(
            Node(
                id=nid,
                coords=tuple(map(float, xyz)),  # type: ignore[arg-type]
                restraint=(True,) * 6 if fixed else (False,) * 6,
                spring=(0.0, 0.0, 0.0, 0.0, 2e6, 0.0) if nid == 4 else (0.0,) * 6,
            )
        )
    released = FrameReleases(j=EndRelease(released=("M3",)))
    project.elements += [
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
        ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
        ElasticBeamColumn(id=3, nodes=(3, 4), section_id=1, releases=released),
        ElasticBeamColumn(id=4, nodes=(5, 4), section_id=1),
    ]
    if ndm == 3:
        project.elements += [
            ElasticBeamColumn(id=5, nodes=(2, 6), section_id=1),
            ElasticBeamColumn(id=6, nodes=(7, 6), section_id=1),
        ]
    pattern = project.load_patterns[0]
    out_of_plane = 300.0 if ndm == 3 else 0.0
    pattern.element_loads.append(UniformElementLoad(element_id=2, wy=-2000.0, wz=out_of_plane))
    pattern.point_loads.append(
        PointElementLoad(element_id=3, py=-5000.0, pz=2 * out_of_plane, x=0.3)
    )
    pattern.distributed_loads.append(
        TrapezoidalElementLoad(
            element_id=4, x_start=0.2, x_end=0.9, wy_start=-3000.0, wy_end=-1000.0
        )
    )
    pattern.nodal_loads.append(
        NodalLoad(node_id=2, forces=(4000.0, 5 * out_of_plane, 0.0, 0.0, 0.0, 0.0))
    )
    project.analyses[0] = project.analyses[0].model_copy(
        update={"n_steps": 2, "load_factor_increment": 0.5}
    )
    return project


def _truss(ndm: int, ndf: int) -> Project:
    spec = TrussSpec(
        span=12,
        depth=2,
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
    ensure_dead_load_case(project)
    top = [n for n in truss.nodes if n.coords[2] > 0][:3]
    project.load_patterns[0].nodal_loads += [
        NodalLoad(node_id=n.id, forces=(0.0, 0.0, -1e4, 0.0, 0.0, 0.0)) for n in top
    ]
    return project


def _assert_same(expected: dict, actual: dict) -> None:  # type: ignore[type-arg]
    scale = max(float(np.max(np.abs(v))) for v in expected.values())
    assert set(actual) == set(expected)
    for key, value in expected.items():
        assert actual[key].shape == value.shape, key
        np.testing.assert_allclose(actual[key], value, rtol=0, atol=RTOL * scale)


@pytest.mark.parametrize(
    "project",
    [_frame(2), _frame(3), _truss(2, 2), _truss(3, 3)],
    ids=["frame-2d", "frame-3d", "truss-2d", "truss-3d"],
)
def test_pynite_matches_opensees(project: Project, tmp_path: Path) -> None:
    case = project.analyses[0]
    expected = OpenSeesRunner(project).run(case, results_dir=tmp_path)
    actual = PyNiteRunner(project).run(case)

    _assert_same(expected.node_disp, actual.node_disp)
    _assert_same(expected.node_reaction, actual.node_reaction)
    _assert_same(expected.element_forces, actual.element_forces)


@pytest.mark.parametrize("axial", [50e3, 150e3])
def test_p_delta_follows_the_closed_form(axial: float) -> None:
    e, i, length, lateral = 200e9, 8.33e-6, 4.0, 2000.0
    project = Project(ndm=3, ndf=6)
    ensure_dead_load_case(project)
    project.sections.append(make_default_section(1))
    project.nodes += [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
        Node(id=2, coords=(0.0, 0.0, length)),
    ]
    project.elements.append(
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1, geom_transf="PDelta")
    )
    project.load_patterns[0].nodal_loads.append(
        NodalLoad(node_id=2, forces=(lateral, 0.0, -axial, 0.0, 0.0, 0.0))
    )

    results = PyNiteRunner(project).run(project.analyses[0])

    k = (axial / (e * i)) ** 0.5
    exact = lateral * (np.tan(k * length) - k * length) / (axial * k)
    first_order = lateral * length**3 / (3 * e * i)
    sway = float(results.node_disp[2][0][0])
    assert sway == pytest.approx(exact, rel=0.02)
    assert sway > first_order * 1.2


def test_the_cli_runs_pynite_like_opensees(tmp_path: Path) -> None:
    path = save_project(_frame(3), tmp_path / "frame.osmodel")

    def run(engine: str) -> object:
        out = tmp_path / engine
        env = {**os.environ, "OPENSEES_STUDIO_ENGINE": engine}
        cmd = [sys.executable, "-m", "opensees_studio.run", "--project", str(path)]
        proc = subprocess.run(
            [*cmd, "--cases", "1", "--out", str(out)],
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        (entry,) = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["cases"]
        return load_results(entry, out)

    expected, actual = run("openseespy"), run("pynite")
    _assert_same(expected.node_disp, actual.node_disp)  # type: ignore[attr-defined]
    _assert_same(expected.element_forces, actual.element_forces)  # type: ignore[attr-defined]
