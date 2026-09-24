"""Sliding bearing verification against the Coulomb closed form (live OpenSeesPy).

Displacement-controlled cyclic shear of one bearing under a constant axial
load ``W`` with Coulomb friction ``mu``: the flat slider must trace a
rectangular loop at ``mu W`` after the elastic branch ``k_init``, the single
friction pendulum a sloped loop with the post-slip stiffness ``W / Reff``
and the intercept ``mu W``; both dissipate ``4 mu W (u_max - u_y)`` per
cycle with ``u_y = mu W / k_init``.

Tolerances (measured on this build with 100 substeps per branch):

* plateau force and elastic stiffness: 1e-6 relative (exact to 1e-9);
* loop energy: 0.5 percent (measured 0.000 percent for the flat slider,
  -0.12 and -0.02 percent for the pendulum at 10 and 25 u_y; the trapezoid
  rule clips the two yield corners, at most one substep of ``2 u_y``);
* pendulum post-slip stiffness: 2 percent (measured +1.1 and +1.2 percent).
  ``SingleFPSimple2d`` takes the normal force on the curved surface as
  ``N = W + F u / Reff``, so the live force is
  ``W (mu + u / Reff) / (1 - (mu + u / Reff) u / Reff)``, which this test
  also checks to 1e-4 at ``u_max``; the plain ``mu W + W u / Reff`` is
  1.2 percent low in slope at ``u_max / Reff = 0.025``.

Velocity dependence: the same flat slider under an imposed constant
velocity (``MultipleSupport`` pattern, so the node carries the velocity)
approaches ``muSlow W`` at ``transRate v = 0.005`` and ``muFast W`` at
``transRate v = 10`` (both within 1 percent) and follows the exponential
law in between (0.1 percent).

Dynamics: a rigid mass on one pendulum with a tiny friction coefficient
free-vibrates at ``2 pi sqrt(Reff / g)`` (measured -0.09 percent, asserted
within 1 percent); under a 1 Hz sine (GM-3 ``TrigTimeSeries``) after a
static gravity preload the response is bounded, periodic and dissipates
the friction loop energy (5 percent).
"""

from __future__ import annotations

import itertools
import tempfile
from pathlib import Path

import numpy as np
import pytest

ops = pytest.importorskip("openseespy.opensees")
pytest.importorskip("h5py")

from opensees_studio.core import (  # noqa: E402
    CoulombFriction,
    ElasticUniaxial,
    FlatSliderBearingElement,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    SingleFPBearingElement,
    StaticCase,
    TransientCase,
    TrigTimeSeries,
    UniformExcitationPattern,
    UnitSystem,
    VelDependentFriction,
    friction_cycle_energy,
    gravity,
    pendulum_period,
)
from opensees_studio.services import OpenSeesRunner  # noqa: E402

MU, W, K_INIT, R_EFF = 0.1, 20.0, 1000.0, 2.0
U_Y = MU * W / K_INIT  # 0.002
N_SUB = 100  # substeps per half-cycle branch
AMPLITUDE_RATIOS = (10.0, 25.0)  # u_max / u_y, well beyond slip


def _bearing_project(element, friction) -> Project:  # type: ignore[no-untyped-def]
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(0.0, 0.0, 0.0), restraint=(False, False, False, False, False, True)),
        ],
        materials=[ElasticUniaxial(id=1, E=1.0e5), ElasticUniaxial(id=2, E=1.0e4)],
        friction_models=[friction],
        elements=[element],
    )


def _flat() -> FlatSliderBearingElement:
    return FlatSliderBearingElement(
        id=1, nodes=(1, 2), friction_model_id=1, k_init=K_INIT, p_material_id=1, mz_material_id=2
    )


def _pendulum() -> SingleFPBearingElement:
    return SingleFPBearingElement(
        id=1,
        nodes=(1, 2),
        friction_model_id=1,
        r_eff=R_EFF,
        k_init=K_INIT,
        p_material_id=1,
        mz_material_id=2,
    )


def _apply_axial_load(weight: float) -> None:
    ops.timeSeries("Constant", 1)
    ops.pattern("Plain", 1, 1)
    ops.load(2, 0.0, -weight, 0.0)
    ops.constraints("Plain")
    ops.numberer("Plain")
    ops.system("BandGeneral")
    ops.test("NormDispIncr", 1e-10, 100)
    ops.algorithm("Newton")
    ops.integrator("LoadControl", 1.0)
    ops.analysis("Static")
    assert ops.analyze(1) == 0
    ops.loadConst("-time", 0.0)


def _cyclic_shear(element, amplitude_ratio: float) -> tuple[np.ndarray, np.ndarray]:  # type: ignore[no-untyped-def]
    """Two and a half cycles of top-node X displacement; returns (u, shear force)."""
    OpenSeesRunner(_bearing_project(element, CoulombFriction(id=1, mu=MU))).build()
    _apply_axial_load(W)
    u_max = amplitude_ratio * U_Y
    ops.timeSeries("Linear", 2)
    ops.pattern("Plain", 2, 2)
    ops.load(2, 1.0, 0.0, 0.0)
    u, f = [0.0], [0.0]
    current = 0.0
    for target in (u_max, -u_max, u_max, -u_max, u_max, 0.0):
        ops.integrator("DisplacementControl", 2, 1, (target - current) / N_SUB)
        for _ in range(N_SUB):
            assert ops.analyze(1) == 0
            u.append(ops.nodeDisp(2, 1))
            f.append(-ops.eleForce(1)[0])  # shear carried by the bearing
        current = target
    ops.wipe()
    return np.asarray(u), np.asarray(f)


def _second_cycle(u: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Samples of the second full cycle: +u_max -> -u_max -> +u_max."""
    return u[3 * N_SUB : 5 * N_SUB + 1], f[3 * N_SUB : 5 * N_SUB + 1]


def _loop_energy(u: np.ndarray, f: np.ndarray) -> float:
    """Area enclosed by the loop (positive for a dissipating loop)."""
    return sum(
        0.5 * (f0 + f1) * (u1 - u0)
        for (u0, f0), (u1, f1) in itertools.pairwise(zip(u, f, strict=True))
    )


def _pendulum_force(u: float) -> float:
    """Live SingleFPSimple2d sliding force with the surface-normal correction."""
    ratio = MU + u / R_EFF
    return W * ratio / (1.0 - ratio * u / R_EFF)


@pytest.mark.parametrize("ratio", AMPLITUDE_RATIOS)
def test_flat_slider_loop_is_rectangular(ratio: float) -> None:
    u, f = _cyclic_shear(_flat(), ratio)
    u_max = ratio * U_Y
    # elastic branch: the first substep is stiff at k_init
    assert f[1] / u[1] == pytest.approx(K_INIT, rel=1e-6)
    uc, fc = _second_cycle(u, f)
    # descending branch (skip the 2 u_y elastic reversal): constant force -mu W
    descending = fc[int(0.15 * N_SUB) : N_SUB]
    assert descending == pytest.approx(-MU * W, rel=1e-6)
    ascending = fc[N_SUB + int(0.15 * N_SUB) : 2 * N_SUB]
    assert ascending == pytest.approx(MU * W, rel=1e-6)
    assert float(np.abs(fc).max()) == pytest.approx(MU * W, rel=1e-6)
    assert abs(fc[-1] - fc[0]) <= 1e-9 * MU * W  # closed loop
    assert _loop_energy(uc, fc) == pytest.approx(friction_cycle_energy(MU, W, u_max, U_Y), rel=5e-3)


@pytest.mark.parametrize("ratio", AMPLITUDE_RATIOS)
def test_single_fp_loop_is_sloped(ratio: float) -> None:
    u, f = _cyclic_shear(_pendulum(), ratio)
    u_max = ratio * U_Y
    assert f[1] / u[1] == pytest.approx(K_INIT, rel=1e-6)
    uc, fc = _second_cycle(u, f)
    # descending branch: F = -mu W + (W / Reff) u
    branch = slice(int(0.15 * N_SUB), N_SUB)
    slope, intercept = np.polyfit(uc[branch], fc[branch], 1)
    assert slope == pytest.approx(W / R_EFF, rel=0.02)
    assert intercept == pytest.approx(-MU * W, rel=5e-3)
    # force at +u_max: live element formula to 1e-4, plain closed form to 1 percent
    assert fc[0] == pytest.approx(_pendulum_force(u_max), rel=1e-4)
    assert fc[0] == pytest.approx(MU * W + W * u_max / R_EFF, rel=0.01)
    assert abs(fc[-1] - fc[0]) <= 1e-9 * MU * W  # closed loop
    assert _loop_energy(uc, fc) == pytest.approx(friction_cycle_energy(MU, W, u_max, U_Y), rel=5e-3)


# ---- velocity-dependent friction -----------------------------------------------------
MU_SLOW, MU_FAST, RATE = 0.05, 0.1, 0.5


def _friction_force_at_velocity(velocity: float) -> float:
    """Flat slider dragged at a constant velocity through an imposed support motion."""
    friction = VelDependentFriction(id=1, mu_slow=MU_SLOW, mu_fast=MU_FAST, trans_rate=RATE)
    OpenSeesRunner(_bearing_project(_flat(), friction)).build()
    _apply_axial_load(W)
    ops.wipeAnalysis()
    ops.timeSeries("Linear", 2, "-factor", velocity)
    ops.timeSeries("Constant", 3, "-factor", velocity)
    ops.pattern("MultipleSupport", 2)
    ops.groundMotion(1, "Plain", "-disp", 2, "-vel", 3)
    ops.imposedMotion(2, 1, 1)
    ops.constraints("Transformation")
    ops.numberer("Plain")
    ops.system("BandGeneral")
    ops.test("NormDispIncr", 1e-10, 100)
    ops.algorithm("Newton")
    ops.integrator("Newmark", 0.5, 0.25)
    ops.analysis("Transient")
    for _ in range(200):
        assert ops.analyze(1, 0.01) == 0
    assert ops.nodeVel(2, 1) == pytest.approx(velocity, rel=1e-6)
    force = -ops.eleForce(1)[0]
    ops.wipe()
    return float(force)


def test_vel_dependent_friction_approaches_slow_and_fast_coefficients() -> None:
    slow = _friction_force_at_velocity(0.01 / RATE)  # transRate v = 0.01
    fast = _friction_force_at_velocity(10.0 / RATE)  # transRate v = 10
    assert slow == pytest.approx(MU_SLOW * W, rel=0.01)
    assert fast == pytest.approx(MU_FAST * W, rel=0.01)
    assert MU_SLOW * W < slow < fast < MU_FAST * W * 1.0001
    mid = _friction_force_at_velocity(2.0)  # transRate v = 1
    law = VelDependentFriction(id=1, mu_slow=MU_SLOW, mu_fast=MU_FAST, trans_rate=RATE)
    assert mid == pytest.approx(law.coefficient(2.0) * W, rel=1e-3)


# ---- rigid mass on one single FP bearing ---------------------------------------------
G = gravity(UnitSystem.SI_M_N)
M_RIGID, R_ISO, K_ISO = 100.0, 2.0, 1.0e5  # t, m, kN/m
W_ISO = M_RIGID * G  # kN
DT, N_STEPS, FREQUENCY, AMPLITUDE, MU_ISO = 0.01, 2000, 1.0, 1.0, 0.05
# Peak |u| (m) measured on this run; the loop is periodic in steady state.
PEAK_U_FP = 0.034029


def _isolated_project(mu: float, **extra) -> Project:  # type: ignore[no-untyped-def]
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(
                id=2,
                coords=(0.0, 0.0, 0.0),
                mass=(M_RIGID, M_RIGID, 0.0, 0.0, 0.0, 0.0),
                restraint=(False, False, False, False, False, True),
            ),
        ],
        materials=[ElasticUniaxial(id=1, E=1.0e7), ElasticUniaxial(id=2, E=1.0e6)],
        friction_models=[CoulombFriction(id=1, mu=mu)],
        elements=[
            SingleFPBearingElement(
                id=1,
                nodes=(1, 2),
                friction_model_id=1,
                r_eff=R_ISO,
                k_init=K_ISO,
                p_material_id=1,
                mz_material_id=2,
            )
        ],
        **extra,
    )


def test_single_fp_free_vibration_period_matches_the_pendulum() -> None:
    OpenSeesRunner(_isolated_project(1e-6)).build()
    _apply_axial_load(W_ISO)
    ops.timeSeries("Linear", 2)
    ops.pattern("Plain", 2, 2)
    ops.load(2, 1.0, 0.0, 0.0)
    u0 = 0.1
    ops.integrator("DisplacementControl", 2, 1, u0 / 50)
    for _ in range(50):
        assert ops.analyze(1) == 0
    assert ops.nodeDisp(2, 1) == pytest.approx(u0)
    ops.remove("loadPattern", 2)
    ops.wipeAnalysis()
    ops.constraints("Plain")
    ops.numberer("Plain")
    ops.system("BandGeneral")
    ops.test("NormDispIncr", 1e-10, 100)
    ops.algorithm("Newton")
    ops.integrator("Newmark", 0.5, 0.25)
    ops.analysis("Transient")
    dt = 0.005
    u, t = [ops.nodeDisp(2, 1)], [0.0]
    for i in range(int(12.0 / dt)):
        assert ops.analyze(1, dt) == 0
        u.append(ops.nodeDisp(2, 1))
        t.append((i + 1) * dt)
    ops.wipe()
    ua, ta = np.asarray(u), np.asarray(t)
    down = np.where((ua[:-1] > 0.0) & (ua[1:] <= 0.0))[0]
    crossings = [ta[i] - ua[i] * (ta[i + 1] - ta[i]) / (ua[i + 1] - ua[i]) for i in down]
    periods = np.diff(crossings)
    assert len(periods) >= 3
    expected = pendulum_period(R_ISO, G)
    assert expected == pytest.approx(2.8375, abs=1e-4)
    assert periods == pytest.approx(expected, rel=0.01)
    assert float(np.abs(ua[-400:]).max()) == pytest.approx(u0, rel=0.01)  # no decay: mu tiny


def test_single_fp_under_sine_is_bounded_with_closed_loops() -> None:
    project = _isolated_project(
        MU_ISO,
        time_series=[
            TrigTimeSeries(id=1, factor=AMPLITUDE, t_end=N_STEPS * DT, period=1.0 / FREQUENCY),
            LinearTimeSeries(id=2),
        ],
        load_patterns=[
            UniformExcitationPattern(id=1, direction=1, accel_series_id=1),
            PlainLoadPattern(
                id=2,
                name="Weight",
                time_series_id=2,
                nodal_loads=[NodalLoad(node_id=2, forces=(0.0, -W_ISO, 0.0, 0.0, 0.0, 0.0))],
            ),
        ],
        analyses=[
            StaticCase(
                id=2,
                name="Gravity",
                pattern_ids=[2],
                n_steps=10,
                load_factor_increment=0.1,
                algorithm="Newton",
            ),
            TransientCase(
                id=1, name="Sine", pattern_ids=[1], preload_case_ids=[2], dt=DT, n_steps=N_STEPS
            ),
        ],
    )
    result = OpenSeesRunner(project).run(
        project.analyses[1], results_dir=Path(tempfile.mkdtemp(prefix="fp_sdof_"))
    )
    assert result.n_steps == N_STEPS
    u = result.node_disp_history(2)[:, 0]
    forces = result.element_force_history(1)
    shear = -forces[:, 1]  # localForce column V at node i
    assert forces[:, 0] == pytest.approx(W_ISO, rel=1e-6)  # axial load held by the preload
    peak = float(np.abs(u).max())
    assert peak == pytest.approx(PEAK_U_FP, rel=0.05)
    # bounded: below the static sweep (M a - mu W) / (W / Reff) of the sliding pendulum
    assert peak < (M_RIGID * AMPLITUDE - MU_ISO * W_ISO) / (W_ISO / R_ISO)
    assert float(np.abs(shear).max()) > MU_ISO * W_ISO  # the bearing slides
    n_period = round(1.0 / FREQUENCY / DT)
    last = slice(N_STEPS - n_period, N_STEPS)
    previous = slice(N_STEPS - 2 * n_period, N_STEPS - n_period)
    assert np.abs(u[last] - u[previous]).max() <= 1e-3 * peak
    assert np.abs(shear[last] - shear[previous]).max() <= 1e-3 * np.abs(shear).max()
    energy = float(np.trapezoid(shear[last], u[last]))
    u_max = float(np.abs(u[last]).max())
    assert energy == pytest.approx(
        friction_cycle_energy(MU_ISO, W_ISO, u_max, MU_ISO * W_ISO / K_ISO), rel=0.05
    )
