"""Static analysis verification.

Cantilever beam: tip lateral load → tip displacement δ = P L³ / (3 E I).
Compares the runner's static result against the closed-form solution.
"""

from __future__ import annotations

import math

import pytest

ops = pytest.importorskip("openseespy.opensees")  # skip if OpenSeesPy not installed

from opensees_studio.core import (  # noqa: E402
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
)
from opensees_studio.services import OpenSeesRunner  # noqa: E402


def test_cantilever_tip_deflection_matches_closed_form() -> None:
    """Horizontal cantilever in 2D: P at tip, expect δ = P L³ / (3 E I)."""
    L = 5.0
    P = 1000.0
    E = 200e9
    A = 0.01
    I = 8.333e-6

    project = Project(
        ndm=2, ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, False, False, False, True)),
            Node(id=2, coords=(L, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=E, A=A, Iz=I)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1, time_series_id=1,
                # Fy at the tip (downward); Rz of node 1 is restrained, others free.
                nodal_loads=[NodalLoad(node_id=2, forces=(0.0, -P, 0.0, 0.0, 0.0, 0.0))],
            )
        ],
    )

    case = StaticCase(id=1, name="Cantilever", pattern_ids=[1])
    results = OpenSeesRunner(project).run(case)

    delta_expected = -P * L**3 / (3.0 * E * I)         # negative (downward)
    delta_actual = results.disp(node_id=2, dof=2)      # Uy at node 2

    assert math.isclose(delta_actual, delta_expected, rel_tol=1e-3), (
        f"Tip deflection mismatch: expected {delta_expected:.6e}, got {delta_actual:.6e}"
    )

    # Reaction at the support equals the applied load.
    Fy_reaction = results.node_reaction[1][0, 1]
    assert math.isclose(Fy_reaction, P, rel_tol=1e-6)
