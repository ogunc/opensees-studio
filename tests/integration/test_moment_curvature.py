"""Integration: verify zeroLengthSection runs and traces moment-curvature.

Mirrors OpenSees's Example 2 (Moment-Curvature of a rectangular RC
section) but with a simplified elastic material so we can check the
slope against a closed-form value. Full Concrete01/Steel01 fiber
behaviour is exercised by the Phase 9 pushover tests.
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (  # noqa: E402
    ElasticUniaxial,
    FiberSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    RectangularPatch,
    StaticCase,
    ZeroLengthSectionElement,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


def _moment_curvature_project(moment: float) -> Project:
    """Two coincident nodes + a rectangular fibre section + one moment step.

    Node 1 clamped; node 2 free in Ux and Rz. Applied moment = ``moment``
    at node 2's DOF 3 (Rz). With a linear-elastic fibre material the
    curvature should be ``moment / (E·I)``.
    """
    E = 30000.0                  # Elastic modulus
    b, h = 10.0, 20.0            # width × depth (in)
    return Project(
        ndm=2, ndf=3,
        nodes=[
            Node(id=1, coords=(0, 0, 0),
                 restraint=(True, True, False, False, False, True)),
            Node(id=2, coords=(0, 0, 0),
                 restraint=(False, True, False, False, False, False)),
        ],
        materials=[ElasticUniaxial(id=1, name="Elastic", E=E)],
        sections=[FiberSection(
            id=1, name="Rect", patches=[RectangularPatch(
                material_id=1, n_fib_y=20, n_fib_z=1,
                y_i=-h / 2, z_i=-b / 2, y_j=h / 2, z_j=b / 2,
            )],
        )],
        elements=[ZeroLengthSectionElement(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1, name="R")],
        load_patterns=[PlainLoadPattern(
            id=1, time_series_id=1,
            # NodalLoad.forces = (Fx, Fy, Fz, Mx, My, Mz). Moment around
            # z (= curvature driver in 2D) goes into index 5, not 2.
            nodal_loads=[NodalLoad(node_id=2,
                                    forces=(0, 0, 0, 0, 0, moment))],
        )],
        analyses=[StaticCase(id=1, name="MK", pattern_ids=[1], n_steps=1)],
    )


def test_zero_length_section_elastic_curvature_matches_closed_form() -> None:
    """For a linear fibre section, curvature = M / (E·I)."""
    # Moment M → curvature κ = M / (E·I). Rectangle: I = b·h³/12.
    M = 500.0
    E = 30000.0
    b, h = 10.0, 20.0
    I = b * h ** 3 / 12.0
    expected_kappa = M / (E * I)

    proj = _moment_curvature_project(moment=M)
    result = OpenSeesRunner(proj).run(proj.analyses[0])
    # Rz at node 2 IS the curvature for a zero-length section.
    ux, uy, rz = result.node_disp[2][-1]
    assert rz == pytest.approx(expected_kappa, rel=5e-3), (
        f"κ = {rz:.6e}, expected {expected_kappa:.6e}"
    )
