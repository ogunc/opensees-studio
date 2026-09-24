"""Elastomeric bearing verification against the bilinear closed form.

One bearing between a fixed bottom node and a coincident top node, built by
``OpenSeesRunner`` (so the emitted ``element`` call is the one under test)
and driven by displacement control: constant axial load, then two and a
half shear cycles at 0.5, 1.0, 2.0 and 4.0 times the yield displacement
``u_y = Qd / (Kinit (1 - alpha1))``.

Closed form of the bilinear loop (OpenSees 3.8 elastomericBearingPlasticity):
yield force ``Fy = Kinit u_y = Qd / (1 - alpha1)``, post-yield branch
``Qd + alpha1 Kinit u`` and energy per full cycle ``4 Qd (u_max - u_y)``.

Tolerances: forces on the linear branches are exact to solver precision
(1e-6 relative). The loop energy is a trapezoid integral over 100 substeps
per branch with the yield corners falling between grid points, so its error
is bounded by four corner triangles ``(1 - alpha1) Kinit du^2 / 2`` with
``du = 2 u_max / 100``: 0.03 % at 2 u_y and 0.11 % at 4 u_y; 0.5 % is used
as a round bound above that.
The Bouc-Wen loop with eta = 50 is a smooth version of the same loop;
its energy is checked against the bilinear value with the same 0.5 %.
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
    ElasticUniaxial,
    ElastomericBearingBoucWenElement,
    ElastomericBearingPlasticityElement,
    Node,
    Project,
    TransientCase,
    TrigTimeSeries,
    UniformExcitationPattern,
    bilinear_cycle_energy,
)
from opensees_studio.services import OpenSeesRunner  # noqa: E402

K_INIT, QD, ALPHA1 = 10.0, 5.0, 0.1
U_Y = QD / (K_INIT * (1.0 - ALPHA1))
F_Y = QD / (1.0 - ALPHA1)
P_AXIAL = 20.0
N_SUB = 100  # substeps per half cycle branch
AMPLITUDE_RATIOS = (0.5, 1.0, 2.0, 4.0)


def _single_bearing_project(element) -> Project:  # type: ignore[no-untyped-def]
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(0.0, 0.0, 0.0), restraint=(False, False, False, False, False, True)),
        ],
        materials=[ElasticUniaxial(id=1, E=1.0e5), ElasticUniaxial(id=2, E=1.0e4)],
        elements=[element],
    )


def _cyclic_shear(element, amplitude_ratio: float) -> tuple[np.ndarray, np.ndarray]:  # type: ignore[no-untyped-def]
    """Two full cycles of top-node X displacement; returns (u, shear force)."""
    OpenSeesRunner(_single_bearing_project(element)).build()
    u_max = amplitude_ratio * U_Y
    ops.timeSeries("Constant", 1)
    ops.pattern("Plain", 1, 1)
    ops.load(2, 0.0, -P_AXIAL, 0.0)
    ops.constraints("Plain")
    ops.numberer("Plain")
    ops.system("BandGeneral")
    ops.test("NormDispIncr", 1e-10, 100)
    ops.algorithm("Newton")
    ops.integrator("LoadControl", 1.0)
    ops.analysis("Static")
    assert ops.analyze(1) == 0
    ops.loadConst("-time", 0.0)
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


def _plasticity() -> ElastomericBearingPlasticityElement:
    return ElastomericBearingPlasticityElement(
        id=1, nodes=(1, 2), k_init=K_INIT, qd=QD, alpha1=ALPHA1, p_material_id=1, mz_material_id=2
    )


def _bouc_wen(eta: float) -> ElastomericBearingBoucWenElement:
    return ElastomericBearingBoucWenElement(
        id=1,
        nodes=(1, 2),
        k_init=K_INIT,
        qd=QD,
        alpha1=ALPHA1,
        p_material_id=1,
        mz_material_id=2,
        eta=eta,
        beta=0.5,
        gamma=0.5,
    )


@pytest.mark.parametrize("ratio", AMPLITUDE_RATIOS)
def test_plasticity_loop_is_bilinear(ratio: float) -> None:
    u, f = _cyclic_shear(_plasticity(), ratio)
    u_max = ratio * U_Y
    assert u[N_SUB] == pytest.approx(u_max)
    # initial stiffness on the first loading branch (all of it below yield for ratio <= 1)
    n_elastic = int(N_SUB * min(1.0, 1.0 / ratio))
    assert f[1 : n_elastic + 1] == pytest.approx(K_INIT * u[1 : n_elastic + 1], rel=1e-6)
    if ratio >= 1.0:
        # yield force at u = u_y
        i_y = round(N_SUB / ratio)
        assert u[i_y] == pytest.approx(U_Y, rel=1e-9)
        assert f[i_y] == pytest.approx(F_Y, rel=1e-6)
    if ratio > 1.0:
        # post-yield branch: slope alpha1 Kinit and intercept Qd (characteristic strength)
        uc, fc = _second_cycle(u, f)
        loading = slice(
            N_SUB + int(0.75 * N_SUB), 2 * N_SUB + 1
        )  # last quarter of -u_max -> +u_max
        slope, intercept = np.polyfit(uc[loading], fc[loading], 1)
        assert slope == pytest.approx(ALPHA1 * K_INIT, rel=1e-6)
        assert intercept == pytest.approx(QD, rel=1e-6)
        assert fc[-1] == pytest.approx(QD + ALPHA1 * K_INIT * u_max, rel=1e-6)
    # dissipated energy per full cycle against 4 Qd (u_max - u_y); zero below yield
    uc, fc = _second_cycle(u, f)
    energy = float(np.trapezoid(fc, uc))
    expected = bilinear_cycle_energy(QD, u_max, U_Y)
    if expected == 0.0:
        assert abs(energy) < 1e-9
    else:
        assert energy == pytest.approx(expected, rel=0.005)
    # the loop is closed: same force at the same displacement one cycle later
    assert abs(fc[-1] - fc[0]) < 1e-9 * F_Y


@pytest.mark.parametrize("ratio", AMPLITUDE_RATIOS)
def test_bouc_wen_sharp_transition_matches_bilinear_energy(ratio: float) -> None:
    u, f = _cyclic_shear(_bouc_wen(eta=50.0), ratio)
    uc, fc = _second_cycle(u, f)
    u_max = ratio * U_Y
    # closed loop (steady state reached in the second cycle)
    assert abs(fc[-1] - fc[0]) <= 0.01 * F_Y
    energy = float(np.trapezoid(fc, uc))
    expected = bilinear_cycle_energy(QD, u_max, U_Y)
    if ratio > 1.0:
        assert energy == pytest.approx(expected, rel=0.005)
        assert fc[-1] == pytest.approx(QD + ALPHA1 * K_INIT * u_max, rel=1e-3)
    else:
        # at or below the yield displacement the smooth loop dissipates little
        # (the bilinear value is zero; the rounded corners give a thin loop)
        assert -1e-9 <= energy <= 0.1 * F_Y * u_max


def test_bouc_wen_effective_stiffness_decreases_with_amplitude() -> None:
    k_eff = []
    for ratio in AMPLITUDE_RATIOS:
        u, f = _cyclic_shear(_bouc_wen(eta=50.0), ratio)
        uc, fc = _second_cycle(u, f)
        k_eff.append(fc[-1] / uc[-1])
    assert k_eff[0] == pytest.approx(K_INIT, rel=1e-3)
    assert all(a > b for a, b in itertools.pairwise(k_eff))
    # beyond yield the secant stiffness follows the bilinear backbone
    assert k_eff[2] == pytest.approx((QD + ALPHA1 * K_INIT * 2.0 * U_Y) / (2.0 * U_Y), rel=1e-3)
    assert k_eff[3] == pytest.approx((QD + ALPHA1 * K_INIT * 4.0 * U_Y) / (4.0 * U_Y), rel=1e-3)


def test_bouc_wen_smooth_transition_dissipates_less_than_bilinear() -> None:
    """eta = 1 rounds the corners: smaller loop, still closed."""
    u, f = _cyclic_shear(_bouc_wen(eta=1.0), 4.0)
    uc, fc = _second_cycle(u, f)
    energy = float(np.trapezoid(fc, uc))
    expected = bilinear_cycle_energy(QD, 4.0 * U_Y, U_Y)
    assert 0.8 * expected < energy < expected
    assert abs(fc[-1] - fc[0]) <= 0.01 * F_Y


# ---- isolated SDOF under a sine (GM-3 TrigTimeSeries) ----------------------------
M_RIGID, K_ISO, QD_ISO, ALPHA_ISO = 100.0, 10000.0, 50.0, 0.1  # t, kN/m, kN
DT, N_STEPS, FREQUENCY, AMPLITUDE = 0.01, 2000, 1.0, 1.0  # s, steps, Hz, m/s^2
# Peak |u| (m) measured on this run; the loop is periodic (closed) in steady state.
PEAK_U_ISOLATED = 0.057447


def test_isolated_sdof_under_sine_is_bounded_with_closed_loops() -> None:
    bearing = ElastomericBearingPlasticityElement(
        id=1,
        nodes=(1, 2),
        k_init=K_ISO,
        qd=QD_ISO,
        alpha1=ALPHA_ISO,
        p_material_id=1,
        mz_material_id=2,
    )
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(0.0, 0.0, 0.0), mass=(M_RIGID, M_RIGID, 0.0, 0.0, 0.0, 0.0)),
        ],
        materials=[ElasticUniaxial(id=1, E=1.0e7), ElasticUniaxial(id=2, E=1.0e6)],
        elements=[bearing],
        time_series=[
            TrigTimeSeries(id=1, factor=AMPLITUDE, t_end=N_STEPS * DT, period=1.0 / FREQUENCY)
        ],
        load_patterns=[UniformExcitationPattern(id=1, direction=1, accel_series_id=1)],
        analyses=[TransientCase(id=1, name="Sine", pattern_ids=[1], dt=DT, n_steps=N_STEPS)],
    )
    result = OpenSeesRunner(project).run(
        project.analyses[0], results_dir=Path(tempfile.mkdtemp(prefix="iso_sdof_"))
    )
    assert result.n_steps == N_STEPS
    u = result.node_disp_history(2)[:, 0]
    shear = -result.element_force_history(1)[:, 1]  # localForce column V at node i
    peak = float(np.abs(u).max())
    # bounded: well below the post-yield static estimate m a / (alpha1 Kinit) = 0.1 m
    assert peak < M_RIGID * AMPLITUDE / (ALPHA_ISO * K_ISO)
    assert peak == pytest.approx(PEAK_U_ISOLATED, rel=0.05)
    assert float(np.abs(shear).max()) > QD_ISO / (1.0 - ALPHA_ISO)  # the bearing yields
    # closed hysteresis: the last excitation period repeats the previous one
    n_period = round(1.0 / FREQUENCY / DT)
    last, previous = (
        slice(N_STEPS - n_period, N_STEPS),
        slice(N_STEPS - 2 * n_period, N_STEPS - n_period),
    )
    assert np.abs(shear[last] - shear[previous]).max() <= 1e-3 * np.abs(shear).max()
    assert np.abs(u[last] - u[previous]).max() <= 1e-3 * peak
    u_y = QD_ISO / (K_ISO * (1.0 - ALPHA_ISO))
    energy = float(np.trapezoid(shear[last], u[last]))
    assert energy == pytest.approx(
        bilinear_cycle_energy(QD_ISO, float(np.abs(u[last]).max()), u_y), rel=0.05
    )
