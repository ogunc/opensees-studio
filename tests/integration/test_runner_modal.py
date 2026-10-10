"""Modal analysis verification.

A 1-DOF lumped-mass cantilever pole. The fundamental natural frequency
of the lateral mode is ω = √(k/m), where k = 3EI/L³ for a tip-mass
cantilever flexural spring.

The runner auto-falls back to ``-fullGenLapack`` for small models —
ARPACK can't allocate enough Arnoldi workspace when the active DOF
count is tiny, which is exactly the SDOF case.
"""

from __future__ import annotations

import math

import pytest

ops = pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (  # noqa: E402
    ElasticBeamColumn,
    ElasticSection,
    ModalCase,
    Node,
    Project,
)
from opensees_studio.services import OpenSeesRunner  # noqa: E402


def test_sdof_pole_first_frequency_matches_kspring_over_m() -> None:
    """Vertical pole, mass at top, fixed base. ω₁ = √(3EI/(mL³))."""
    L = 3.0
    E = 200e9
    A = 0.01
    I = 8.333e-6  # noqa: E741 - I is the second moment of area (moment of inertia)
    m_tip = 1000.0

    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, False, False, False, True)),
            Node(id=2, coords=(0.0, L, 0.0), mass=(m_tip, m_tip, 0.0, 0.0, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=E, A=A, Iz=I)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
    )

    case = ModalCase(id=1, name="SDOF-Pole", n_modes=1)
    results = OpenSeesRunner(project).run(case)

    # Lateral cantilever spring stiffness:
    k = 3.0 * E * I / L**3
    omega_expected = math.sqrt(k / m_tip)

    omega_actual = float(results.angular_frequencies[0])
    assert math.isclose(omega_actual, omega_expected, rel_tol=5e-3), (
        f"ω₁ mismatch: expected {omega_expected:.4f} rad/s, got {omega_actual:.4f} rad/s"
    )


def test_runner_falls_back_to_lapack_for_small_models() -> None:
    """Verify the fallback rule: small n_free triggers Lapack instead of ARPACK."""
    from unittest.mock import MagicMock

    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, False, False, False, True)),
            Node(id=2, coords=(0.0, 3.0, 0.0), mass=(1000.0, 1000.0, 0.0, 0.0, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=8.333e-6)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
    )
    mock_ops = MagicMock()
    mock_ops.eigen.return_value = [1.0]
    mock_ops.nodeEigenvector.return_value = 0.0

    runner = OpenSeesRunner(project, ops_module=mock_ops)
    runner.run(ModalCase(id=1, name="t", n_modes=1))  # default solver = 'genBandArpack'

    # n_free = (3 - 2) + (3 - 1) = 3, and 2 * n_modes = 2 >= n_free? No, 2 < 3.
    # Adjust: ask for 2 modes — 2*2 = 4 >= 3 → must trigger fallback.
    mock_ops.reset_mock()
    mock_ops.eigen.return_value = [1.0, 4.0]
    runner.run(ModalCase(id=2, name="t2", n_modes=2))
    mock_ops.eigen.assert_called_with("-fullGenLapack", 2)


# ─────────────────────── history independence ───────────────────────
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

from opensees_studio.core.modal import (  # noqa: E402
    DENSE_EIGEN_MAX_FREE_DOF_ENV,
    SIGN_TIE_REL_TOL,
    SYMM_BAND_REFUSAL,
    free_dof_count,
)
from opensees_studio.services import load_project  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _modal_case(project: Project, case_id: int) -> ModalCase:
    case = next(c for c in project.analyses if c.id == case_id)
    assert isinstance(case, ModalCase)
    return case


def _shape_diff(a, b) -> float:  # type: ignore[no-untyped-def]
    return max(
        float(np.max(np.abs(a.mode_shapes[m][n] - b.mode_shapes[m][n])))
        for m in a.mode_shapes
        for n in a.mode_shapes[m]
    )


@pytest.mark.parametrize(
    ("example", "case_id"),
    [("cantilever", 3), ("elastic_frame", 3), ("space_frame_3d", 2)],
)
def test_two_eigen_calls_in_one_process_give_identical_results(
    monkeypatch, example: str, case_id: int
) -> None:  # type: ignore[no-untyped-def]
    """Below the threshold the dense solver runs, and a repeat is bit-identical.

    With ARPACK a second call in the same process flipped signs (cantilever,
    elastic_frame) and rotated the repeated pair of space_frame_3d.
    """
    monkeypatch.delenv(DENSE_EIGEN_MAX_FREE_DOF_ENV, raising=False)
    project = load_project(EXAMPLES / f"{example}.osmodel")
    case = _modal_case(project, case_id)
    assert case.solver == "auto"
    first = OpenSeesRunner(project).run(case)
    second = OpenSeesRunner(project).run(case)
    assert first.solver == second.solver == "fullGenLapack"
    assert first.n_free_dof == free_dof_count(project) <= 500
    assert np.array_equal(first.eigenvalues, second.eigenvalues)
    assert _shape_diff(first, second) == 0.0


def test_explicit_arpack_choice_is_honoured_and_recorded() -> None:
    project = load_project(EXAMPLES / "space_frame_3d.osmodel")
    case = _modal_case(project, 2).model_copy(update={"solver": "genBandArpack"})
    results = OpenSeesRunner(project).run(case)
    assert results.solver == "genBandArpack"
    assert results.n_free_dof == 48


def test_environment_override_routes_a_small_model_to_arpack(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(DENSE_EIGEN_MAX_FREE_DOF_ENV, "10")
    project = load_project(EXAMPLES / "space_frame_3d.osmodel")
    results = OpenSeesRunner(project).run(_modal_case(project, 2))
    assert results.solver == "genBandArpack"


def test_symm_band_lapack_is_refused_before_any_eigen_call() -> None:
    project = load_project(EXAMPLES / "space_frame_3d.osmodel")
    case = _modal_case(project, 2).model_copy(update={"solver": "symmBandLapack"})
    with pytest.raises(ValueError, match="positive definite mass"):
        OpenSeesRunner(project).run(case)
    assert SYMM_BAND_REFUSAL.startswith("symmBandLapack")


def test_elastic_frame_mirror_tie_is_broken_by_the_lowest_dof_index() -> None:
    """elastic_frame is symmetric: the two largest components of every mode are
    equal to roundoff (relative gap around 1e-15). The tie tolerance makes the
    lowest DOF index the reference, so the sign no longer depends on which of
    the two mirror nodes the solver rounds up.
    """
    project = load_project(EXAMPLES / "elastic_frame.osmodel")
    results = OpenSeesRunner(project).run(_modal_case(project, 3))
    node_ids = sorted(project.nodes, key=lambda n: n.id)
    ties_seen = 0
    for mode, shape in results.mode_shapes.items():
        flat = np.concatenate([shape[n.id] for n in node_ids])
        magnitudes = np.abs(flat)
        largest = magnitudes.max()
        tied = np.flatnonzero(magnitudes >= largest * (1.0 - SIGN_TIE_REL_TOL))
        strict = np.flatnonzero(magnitudes == largest)
        if tied.size > strict.size or strict.size > 1:
            ties_seen += 1
        # The reference component (lowest tied index) is positive.
        assert flat[tied[0]] > 0.0, f"mode {mode}: reference component not positive"
    assert ties_seen >= 1, "elastic_frame no longer shows the mirror tie this test covers"


def test_mode_shapes_are_sign_normalized_for_every_mode() -> None:
    project = load_project(EXAMPLES / "space_frame_3d.osmodel")
    results = OpenSeesRunner(project).run(_modal_case(project, 2))
    node_ids = sorted(project.nodes, key=lambda n: n.id)
    for shape in results.mode_shapes.values():
        flat = np.concatenate([shape[n.id] for n in node_ids])
        largest = np.abs(flat).max()
        tied = np.flatnonzero(np.abs(flat) >= largest * (1.0 - SIGN_TIE_REL_TOL))
        assert flat[tied[0]] > 0.0
