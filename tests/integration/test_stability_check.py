"""Analyze → Check Model Stability against models whose stability is known."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    ElasticUniaxial,
    EndRelease,
    EqualDOFConstraint,
    FrameReleases,
    Node,
    Project,
    TrussElement,
)
from opensees_studio.services.persistence import save_project
from opensees_studio.services.stability import check_stability

PIN_2D = (True, False, True, False, False, False)
ROLLER_2D = (False, False, True, False, False, False)
FIXED = (True,) * 6


def _truss(diagonal: bool) -> Project:
    """A 4 x 3 square truss on a pin and a roller, in the X-Z plane."""
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=PIN_2D),
        Node(id=2, coords=(4.0, 0.0, 0.0), restraint=ROLLER_2D),
        Node(id=3, coords=(4.0, 0.0, 3.0)),
        Node(id=4, coords=(0.0, 0.0, 3.0)),
    ]
    pairs = [(1, 2), (2, 3), (3, 4), (4, 1)] + ([(1, 3)] if diagonal else [])
    elements = [
        TrussElement(id=k, nodes=p, area=0.01, material_id=1) for k, p in enumerate(pairs, 1)
    ]
    return Project(
        ndm=2, ndf=2, nodes=nodes, elements=elements, materials=[ElasticUniaxial(id=1, E=2e8)]
    )


def _portal(*, base: tuple[bool, ...], beam_releases: FrameReleases | None = None) -> Project:
    """A 2D portal frame: columns 1-2 and 4-3, beam 2-3."""
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=base),
        Node(id=2, coords=(0.0, 0.0, 3.0)),
        Node(id=3, coords=(5.0, 0.0, 3.0)),
        Node(id=4, coords=(5.0, 0.0, 0.0), restraint=base),
    ]
    beam = ElasticBeamColumn(
        id=2, nodes=(2, 3), section_id=1, releases=beam_releases or FrameReleases()
    )
    elements = [
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
        beam,
        ElasticBeamColumn(id=3, nodes=(4, 3), section_id=1),
    ]
    return Project(
        ndm=2,
        ndf=3,
        nodes=nodes,
        elements=elements,
        sections=[ElasticSection(id=1, E=2e8, A=0.01, Iz=1e-4)],
    )


def test_a_braced_truss_is_stable() -> None:
    report = check_stability(_truss(diagonal=True))
    assert report.stable
    assert report.n_equations == report.rank == 5


def test_the_default_capture_is_sparse_and_the_small_diagnosis_is_dense() -> None:
    report = check_stability(_truss(diagonal=True))
    assert report.method.startswith("python_sparse_csr+")
    assert report.backend.startswith("PythonSparse+")
    assert report.nnz > 0
    assert report.completion == "complete"
    assert report.classification == "no_mechanisms"
    assert report.count_kind == "exact"
    assert report.versions["scipy"]
    assert report.model_fingerprint


def test_a_singular_sparse_capture_still_returns_the_mechanism() -> None:
    report = check_stability(_truss(diagonal=False))
    assert report.method.startswith("python_sparse_csr+")
    assert report.nnz > 0
    assert report.completion == "complete"
    assert report.n_mechanisms == 1
    mechanism = report.mechanisms[0]
    assert mechanism.eigenvalue is not None
    assert mechanism.residual is not None and mechanism.residual < 1e-8


def test_a_square_without_a_diagonal_sways() -> None:
    report = check_stability(_truss(diagonal=False))
    assert not report.stable
    assert report.n_mechanisms == 1 and report.rank == 4
    movers = {(m.node, m.dof) for m in report.mechanisms[0].movers}
    assert movers == {(3, "Ux"), (4, "Ux")}  # the top chord slides sideways
    assert sorted(report.nodes) == [3, 4]


def test_an_ungrounded_component_returns_a_verified_free_body_mechanism() -> None:
    project = Project(
        ndm=2,
        ndf=2,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(1.0, 0.0, 0.0)),
        ],
        elements=[TrussElement(id=1, nodes=(1, 2), area=0.01, material_id=1)],
        materials=[ElasticUniaxial(id=1, E=2e8)],
    )
    report = check_stability(project)

    assert not report.stable
    assert report.completion == "partial"
    assert report.classification == "mechanism"
    assert report.count_kind == "lower_bound"
    assert report.n_mechanisms == 1
    mechanism = report.mechanisms[0]
    assert mechanism.kind == "free_body"
    assert mechanism.residual is not None and mechanism.residual < 1e-7
    assert {(m.node, m.dof) for m in mechanism.movers} == {(1, "Ux"), (2, "Ux")}


def test_a_fixed_base_portal_is_stable() -> None:
    fixed_2d = (True, False, True, False, True, False)
    assert check_stability(_portal(base=fixed_2d)).stable


def test_a_pinned_portal_with_a_pinned_beam_is_a_mechanism() -> None:
    both_ends = FrameReleases(i=EndRelease(released=("M3",)), j=EndRelease(released=("M3",)))
    report = check_stability(_portal(base=PIN_2D, beam_releases=both_ends))
    assert not report.stable
    assert report.n_mechanisms >= 1
    moved = {m.node for mech in report.mechanisms for m in mech.movers}
    assert moved & {2, 3}


def test_a_fully_restrained_model_is_reported_as_such() -> None:
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6)],
    )
    report = check_stability(project)
    assert report.n_equations == 0
    assert report.completion == "complete"
    assert report.classification == "no_free_equations"
    assert report.stable
    assert "fully restrained" in report.summary()


def test_a_time_limit_or_cancel_returns_cancelled_not_stable() -> None:
    timed = check_stability(_truss(diagonal=True), timeout_s=1e-9)
    assert timed.completion == "cancelled"
    assert timed.classification == "indeterminate"
    assert not timed.stable
    assert "time limit" in (timed.failure_reason or "")

    cancelled = check_stability(_truss(diagonal=True), should_cancel=lambda: True)
    assert cancelled.completion == "cancelled"
    assert not cancelled.stable


def test_phase_progress_is_reported() -> None:
    phases: list[str] = []
    report = check_stability(
        _truss(diagonal=True),
        progress=lambda phase, _message: phases.append(phase),
    )
    assert report.completion == "complete"
    assert phases[:4] == ["precheck", "build", "capture", "reconstruct"]
    assert phases[-1] == "done"


def test_a_node_nothing_connects_to_is_reported() -> None:
    project = _truss(diagonal=True)
    project.nodes.append(Node(id=9, coords=(8.0, 0.0, 0.0)))
    report = check_stability(project)
    assert not report.stable
    assert any("Node 9" in line for line in report.uncovered)


def test_an_equal_dof_tie_braces_a_3d_column_pair() -> None:
    """Two cantilevers stay stable when tied; the tie removes DOFs, not stiffness."""
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=FIXED),
        Node(id=2, coords=(0.0, 0.0, 3.0)),
        Node(id=3, coords=(4.0, 0.0, 0.0), restraint=FIXED),
        Node(id=4, coords=(4.0, 0.0, 3.0)),
    ]
    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[ElasticSection(id=1, E=2e8, A=0.01, Iz=1e-4, Iy=1e-4, G=8e7, J=2e-4)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1),
        ],
        mp_constraints=[EqualDOFConstraint(retained_node=2, constrained_node=4, dofs=(1, 2))],
    )
    report = check_stability(project)
    assert report.stable
    assert report.n_equations == 12 - 2


def test_the_cli_prints_one_stability_line(tmp_path: Path) -> None:
    path = tmp_path / "truss.osmodel"
    save_project(_truss(diagonal=False), path)
    done = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(path), "--check-stability"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    lines = [json.loads(line) for line in done.stdout.splitlines() if line.strip()]
    (stability,) = [line for line in lines if line["type"] == "stability"]
    assert stability["report"]["n_mechanisms"] == 1
    assert any(line.get("type") == "stability_progress" for line in lines)


def test_the_cli_stability_timeout_reports_cancelled(tmp_path: Path) -> None:
    path = tmp_path / "truss.osmodel"
    save_project(_truss(diagonal=True), path)
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(path),
            "--check-stability",
            "--stability-timeout",
            "1e-9",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    lines = [json.loads(line) for line in done.stdout.splitlines() if line.strip()]
    (stability,) = [line for line in lines if line["type"] == "stability"]
    assert stability["report"]["completion"] == "cancelled"
    assert stability["report"]["classification"] == "indeterminate"


def test_the_cli_still_wants_cases_without_the_flag(tmp_path: Path) -> None:
    path = tmp_path / "truss.osmodel"
    save_project(_truss(diagonal=True), path)
    done = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 2  # argparse usage error
    assert "--cases and --out are required" in done.stderr
