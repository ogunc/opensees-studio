"""Integration test: Concrete04 in a fiber-section cantilever.

Verifies that the full stack (model → runner → OpenSeesPy → result) works
end-to-end with Concrete04 (Popovics concrete) as the sole material.

Reference: for very small compressive strains the Popovics curve is
linear with slope Ec, so the axial shortening of a column under a
small axial load is:

    delta = P * L / (Ec * A)

with negligible Popovics nonlinearity at the applied strain level.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (  # noqa: E402
    Concrete04,
    FiberSection,
    ForceBeamColumn,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    RectangularPatch,
    StaticCase,
    UnitSystem,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402

# ── Model constants ────────────────────────────────────────────────────────────
L = 1.0          # column height [m]
B = H = 0.3      # cross-section dimensions [m]
A = B * H        # section area [m²]

FC = -30e6       # peak compressive strength [Pa]  (negative)
EPSC0 = -0.002   # strain at peak strength          (negative)
EPSCU = -0.005   # ultimate compressive strain      (negative)
EC = 30e9        # initial tangent modulus [Pa]

# Applied axial load: small enough (< 1 % of capacity) that the Popovics
# curve is indistinguishable from its linear tangent at origin.
P_AXIAL = -1200.0   # N  (downward → compressive)

# Analytical axial shortening: P * L / (Ec * A)
EXPECTED_UY = P_AXIAL * L / (EC * A)   # ≈ -1.333e-7 m


def _build_project() -> Project:
    return Project(
        meta=ProjectMeta(
            name="Concrete04 fiber-section cantilever",
            units=UnitSystem.SI_M_N,
        ),
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, name="Base", coords=(0.0, 0.0, 0.0),
                 restraint=(True, True, True, False, False, False)),
            Node(id=2, name="Top",  coords=(0.0, L, 0.0)),
        ],
        materials=[
            Concrete04(
                id=1, name="C30-Popovics",
                fpc=FC, epsc0=EPSC0, epscu=EPSCU, Ec=EC,
            ),
        ],
        sections=[
            FiberSection(
                id=1, name="RC-Fiber",
                patches=[
                    RectangularPatch(
                        material_id=1,
                        n_fib_y=4, n_fib_z=4,
                        y_i=-H / 2, z_i=-B / 2,
                        y_j= H / 2, z_j= B / 2,
                    ),
                ],
            ),
        ],
        elements=[
            ForceBeamColumn(
                id=1, name="Column",
                nodes=(1, 2),
                section_id=1,
                integration_points=3,
                geom_transf="Linear",
            ),
        ],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            PlainLoadPattern(
                id=1, name="Gravity", time_series_id=1,
                nodal_loads=[
                    NodalLoad(node_id=2, forces=(0.0, P_AXIAL, 0.0, 0.0, 0.0, 0.0)),
                ],
            ),
        ],
        analyses=[
            StaticCase(
                id=1, name="Gravity",
                pattern_ids=[1],
                n_steps=1,
                load_factor_increment=1.0,
                system="BandGeneral",
                constraints="Plain",
                integrator="LoadControl",
                algorithm="Newton",
                test="NormDispIncr",
                tolerance=1e-12,
                max_iter=10,
            ),
        ],
    )


def test_concrete04_gravity_axial_shortening() -> None:
    """Axial shortening under small gravity load matches the linear reference."""
    proj = _build_project()
    case = proj.analyses[0]
    result = OpenSeesRunner(proj).run(case)

    # Uy at the top node (DOF index 1 = Y in 2D 3-DOF).
    uy = result.node_disp[2][0, 1]

    # Tolerance: 0.1 % relative — the Popovics curve at the applied strain
    # level (|ε| ≈ 1.5e-8) deviates from linear by < 1e-12 relative.
    assert uy == pytest.approx(EXPECTED_UY, rel=1e-3)


def test_concrete04_with_tension_does_not_raise() -> None:
    """Smoke-test: optional tensile branch accepted by OpenSeesPy without error."""
    proj = _build_project()
    # Replace material with tensile-branch variant.
    proj.materials[0] = Concrete04(
        id=1, name="C30-WithTension",
        fpc=FC, epsc0=EPSC0, epscu=EPSCU, Ec=EC,
        fct=3.0e6, et=1e-4,
    )
    case = proj.analyses[0]
    result = OpenSeesRunner(proj).run(case)
    assert result.node_disp[2][0, 1] == pytest.approx(EXPECTED_UY, rel=1e-3)
