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

ops = pytest.importorskip("openseespy.opensees")  # noqa: F401

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
    I = 8.333e-6
    m_tip = 1000.0

    project = Project(
        ndm=2, ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, False, False, False, True)),
            Node(id=2, coords=(0.0, L, 0.0),
                 mass=(m_tip, m_tip, 0.0, 0.0, 0.0, 0.0)),
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
        ndm=2, ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, False, False, False, True)),
            Node(id=2, coords=(0.0, 3.0, 0.0),
                 mass=(1000.0, 1000.0, 0.0, 0.0, 0.0, 0.0)),
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
