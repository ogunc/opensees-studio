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


def test_pushover_drives_rotation_for_moment_curvature() -> None:
    """Full moment-curvature analysis via PushoverCase on DOF 3 (Rz).

    Mirrors the OpenSees Moment-Curvature example's driver: a
    DisplacementControl pushover on node 2's rotational DOF produces
    a moment-curvature curve. For a linear-elastic fibre section the
    base "shear" is actually the reactive moment, and the curve is a
    straight line through the origin with slope E·I.
    """
    from opensees_studio.core import PushoverCase
    E = 30000.0
    b, h = 10.0, 20.0
    I = b * h ** 3 / 12.0
    target_kappa = 1e-5
    steps = 20

    # PushoverCase with DisplacementControl scales the load pattern —
    # needs a *non-zero* reference moment at the control DOF.
    proj = _moment_curvature_project(moment=1.0)
    proj.analyses = [PushoverCase(
        id=1, name="MK-push",
        pattern_ids=[1],
        control_node=2, control_dof=3,     # DOF 3 = Rz
        target_disp=target_kappa,           # "displacement" == curvature here
        step_size=target_kappa / steps,
        base_nodes=[1],
    )]
    result = OpenSeesRunner(proj).run(proj.analyses[0])

    # Every (κ, M) point must satisfy M = E·I·κ (1 % tolerance allows
    # for the ~20-fibre discretisation of the rectangular section).
    for kappa, moment in zip(result.control_disp, result.base_shear):
        if abs(kappa) < 1e-12:
            continue
        expected_M = E * I * kappa
        assert moment == pytest.approx(expected_M, rel=1e-2), (
            f"at κ={kappa:.3e}: M={moment:.3e}, expected {expected_M:.3e}"
        )
    # Terminal curvature must reach the target.
    assert result.control_disp[-1] == pytest.approx(target_kappa, rel=1e-3)


def test_moment_curvature_with_constant_axial_preload() -> None:
    """OpenSees MK Example 2 recipe: Concrete01 + Steel01 fibre section,
    constant axial compression preloaded, then DisplacementControl ramps
    curvature. Verifies the runner's two-stage preload + pushover
    plumbing (the key fix that makes convergence possible on nonlinear
    RC sections).
    """
    from opensees_studio.core import (
        Concrete01,
        ConstantTimeSeries,
        FiberSection,
        LinearTimeSeries,
        NodalLoad,
        PlainLoadPattern,
        PushoverCase,
        RectangularPatch,
        Steel01,
        StraightLayer,
    )
    colWidth = 15.0
    colDepth = 24.0
    cover = 1.5
    As = 0.60
    y1 = colDepth / 2
    z1 = colWidth / 2

    proj = Project(
        ndm=2, ndf=3,
        nodes=[
            Node(id=1, coords=(0, 0, 0),
                 restraint=(True, True, False, False, False, True)),
            Node(id=2, coords=(0, 0, 0),
                 restraint=(False, True, False, False, False, False)),
        ],
        materials=[
            Concrete01(id=1, name="Core",
                       fpc=-6.0, epsc0=-0.004,
                       fpcu=-5.0, epsU=-0.014),
            Concrete01(id=2, name="Cover",
                       fpc=-5.0, epsc0=-0.002,
                       fpcu=0.0, epsU=-0.006),
            Steel01(id=3, name="Steel", Fy=60.0, E0=30000.0, b=0.01),
        ],
        sections=[FiberSection(
            id=1, name="RC",
            patches=[
                # Core (confined)
                RectangularPatch(material_id=1, n_fib_y=10, n_fib_z=1,
                                  y_i=cover - y1, z_i=cover - z1,
                                  y_j=y1 - cover, z_j=z1 - cover),
                # Top cover
                RectangularPatch(material_id=2, n_fib_y=10, n_fib_z=1,
                                  y_i=-y1, z_i=z1 - cover,
                                  y_j=y1, z_j=z1),
                # Bottom cover
                RectangularPatch(material_id=2, n_fib_y=10, n_fib_z=1,
                                  y_i=-y1, z_i=-z1,
                                  y_j=y1, z_j=cover - z1),
                # Left cover
                RectangularPatch(material_id=2, n_fib_y=2, n_fib_z=1,
                                  y_i=-y1, z_i=cover - z1,
                                  y_j=cover - y1, z_j=z1 - cover),
                # Right cover
                RectangularPatch(material_id=2, n_fib_y=2, n_fib_z=1,
                                  y_i=y1 - cover, z_i=cover - z1,
                                  y_j=y1, z_j=z1 - cover),
            ],
            layers=[
                StraightLayer(material_id=3, n_bars=3, bar_area=As,
                              y_start=y1 - cover, z_start=z1 - cover,
                              y_end=y1 - cover, z_end=cover - z1),
                StraightLayer(material_id=3, n_bars=2, bar_area=As,
                              y_start=0.0, z_start=z1 - cover,
                              y_end=0.0, z_end=cover - z1),
                StraightLayer(material_id=3, n_bars=3, bar_area=As,
                              y_start=cover - y1, z_start=z1 - cover,
                              y_end=cover - y1, z_end=cover - z1),
            ],
        )],
        elements=[ZeroLengthSectionElement(id=1, nodes=(1, 2), section_id=1)],
        time_series=[
            ConstantTimeSeries(id=1, name="AxialP"),
            LinearTimeSeries(id=2, name="RefMoment"),
        ],
        load_patterns=[
            PlainLoadPattern(
                id=1, name="AxialP", time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2,
                                        forces=(-180.0, 0, 0, 0, 0, 0))],
            ),
            PlainLoadPattern(
                id=2, name="RefMoment", time_series_id=2,
                nodal_loads=[NodalLoad(node_id=2,
                                        forces=(0, 0, 0, 0, 0, 1.0))],
            ),
        ],
        analyses=[],
    )
    # Yield curvature estimate from the Tcl example.
    d = colDepth - cover
    Ky = 60.0 / 30000.0 / (0.7 * d)
    target = Ky * 15            # μ = 15
    proj.analyses = [PushoverCase(
        id=1, name="MK",
        pattern_ids=[1, 2],
        control_node=2, control_dof=3,
        target_disp=target,
        step_size=target / 100,
        base_nodes=[1],
        test="NormUnbalance",
        tolerance=1e-9, max_iter=25,
    )]

    result = OpenSeesRunner(proj).run(proj.analyses[0])

    # Analysis must actually converge past yield (not collapse at
    # step 1 like it did before the two-stage preload fix).
    assert len(result.control_disp) > 50, (
        f"Converged for only {len(result.control_disp)} of 100 steps — "
        "preload stage broken?"
    )
    # Curvature reached or passed yield.
    kappa_max = float(max(abs(k) for k in result.control_disp))
    assert kappa_max > Ky, f"κ_max={kappa_max:.3e} < Ky={Ky:.3e}"
    # Nonlinear → curve has a distinct softening: slope late in the
    # run should be smaller than slope near the origin.
    d_early = (result.base_shear[5] - result.base_shear[1]) / (
        result.control_disp[5] - result.control_disp[1]
    )
    last = len(result.control_disp) - 1
    mid = last // 2
    d_late = (result.base_shear[last] - result.base_shear[mid]) / (
        result.control_disp[last] - result.control_disp[mid]
    )
    assert abs(d_late) < abs(d_early), (
        f"Late slope {d_late:.2e} not smaller than early {d_early:.2e} "
        "— section response looks linear, preload probably didn't apply."
    )
