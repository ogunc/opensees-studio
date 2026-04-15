"""Modal analysis verification.

A 1-DOF lumped-mass cantilever pole. The fundamental natural frequency
of the lateral mode is ω = √(k/m), where k = 3EI/L³ for a tip-mass
cantilever flexural spring.
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

    case = ModalCase(id=1, name="SDOF-Pole", n_modes=2)
    results = OpenSeesRunner(project).run(case)

    # Lateral cantilever spring stiffness:
    k = 3.0 * E * I / L**3
    omega_expected = math.sqrt(k / m_tip)

    # The smaller of the first two modal frequencies should be the lateral mode.
    omega_actual_min = float(results.angular_frequencies.min())
    assert math.isclose(omega_actual_min, omega_expected, rel_tol=5e-3), (
        f"ω₁ mismatch: expected {omega_expected:.4f} rad/s, got {omega_actual_min:.4f} rad/s"
    )
