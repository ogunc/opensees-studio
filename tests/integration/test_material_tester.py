"""Integration tests for the headless Material Tester service.

Note on placement: the prompt requested ``tests/unit/services/``; however,
every test here invokes real openseespy, which disqualifies them from
``tests/unit/`` per the project convention (CLAUDE.md: "No Qt, no openseespy").
They live here instead and are fast (<2 s total on a modern laptop).
"""

from __future__ import annotations

import pytest

from opensees_studio.core import (
    Concrete04,
    ElasticBeamColumn,
    ElasticSection,
    ElasticUniaxial,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    StaticCase,
    Steel01,
    UnitSystem,
)
from opensees_studio.core.materials import ElasticPP
from opensees_studio.services import OpenSeesRunner
from opensees_studio.services.material_tester import (
    CyclicSegment,
    LoadProtocol,
    MaterialTestResult,
    test_uniaxial_material,
)

# ---- helpers ---------------------------------------------------------------


def _simple_cantilever() -> Project:
    """Minimal 2-node elastic cantilever for the interleave test."""
    return Project(
        meta=ProjectMeta(name="interleave-ref", units=UnitSystem.SI_M_N),
        ndm=2,
        ndf=3,
        nodes=[
            Node(
                id=1, name="Base",
                coords=(0.0, 0.0, 0.0),
                # 2D-frame DOF mapping: (Ux, Uy, Uz, Rx, Ry, Rz) -> runner uses (0,1,5).
                # Fixed base: Ux=True, Uy=True, Rz=True (index 5).
                restraint=(True, True, False, False, False, True),
            ),
            Node(id=2, name="Top", coords=(1.0, 0.0, 0.0)),
        ],
        materials=[ElasticUniaxial(id=1, E=200e9)],
        sections=[ElasticSection(id=1, E=200e9, A=0.09, Iz=6.75e-4)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1, geom_transf="Linear"),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1, time_series_id=1,
                # Downward tip load (Uy direction).
                nodal_loads=[NodalLoad(node_id=2, forces=(0.0, -1.0e4, 0.0, 0.0, 0.0, 0.0))],
            ),
        ],
        analyses=[
            StaticCase(
                id=1, pattern_ids=[1], n_steps=1, load_factor_increment=1.0,
                system="BandGeneral", constraints="Plain",
                integrator="LoadControl", algorithm="Newton",
                test="NormDispIncr", tolerance=1e-8, max_iter=10,
            ),
        ],
    )


# ---- elastic monotonic -----------------------------------------------------


def test_elastic_uniaxial_monotonic_stress_strain() -> None:
    """Elastic uniaxial: stress == E x strain within relative 1e-9."""
    e_mod = 200e9
    mat = ElasticUniaxial(id=1, E=e_mod)
    protocol = LoadProtocol(
        kind="monotonic",
        max_compressive=-0.01,
        max_tensile=0.01,
        n_steps_per_branch=50,
    )
    result = test_uniaxial_material(mat, protocol)

    assert isinstance(result, MaterialTestResult)
    assert len(result.strain) == 100  # 2 branches x 50 steps

    for strain_val, stress_val in zip(result.strain, result.stress, strict=True):
        # For a linear elastic spring, stress must equal E x strain to
        # within numerical precision.
        assert stress_val == pytest.approx(e_mod * strain_val, rel=1e-9), (
            f"stress mismatch at strain={strain_val:.4g}: "
            f"got {stress_val:.4g}, expected {e_mod * strain_val:.4g}"
        )


# ---- ElasticPP plateau -----------------------------------------------------


def test_elastic_pp_compressive_plateau() -> None:
    """ElasticPP: stress is exactly -Fy for all strains past compressive yield."""
    e_mod = 200e9
    epsy = 1.25e-3          # yield strain in tension
    fy = e_mod * epsy       # implied yield stress = 250 MPa

    mat = ElasticPP(id=1, E=e_mod, epsy_pos=epsy)
    protocol = LoadProtocol(
        kind="monotonic",
        max_compressive=-5.0 * epsy,
        n_steps_per_branch=100,
    )
    result = test_uniaxial_material(mat, protocol)

    past_yield = [
        (s, sig)
        for s, sig in zip(result.strain, result.stress, strict=True)
        if s < -epsy * 1.1  # clearly past compressive yield
    ]
    assert len(past_yield) > 0, "no post-yield data points found"

    for s, sig in past_yield:
        assert sig == pytest.approx(-fy, rel=1e-6), (
            f"plateau broken at strain={s:.4g}: got {sig:.4g}, expected {-fy:.4g}"
        )


# ---- Steel01 cyclic energy -------------------------------------------------


def test_steel01_cyclic_hysteresis_energy() -> None:
    """Steel01 (EPP, b=0): dissipated energy per stable cycle within 1% of theory.

    Analytical reference for symmetric EPP cycles with amplitude ea:
        E_per_cycle = 4 x Fy x (ea - ey)
    Derived from the area of the parallelogram in stress-strain space.
    """
    fy = 250e6
    e0 = 200e9
    b = 0.0
    ey = fy / e0          # = 1.25e-3
    ea = 5.0 * ey         # = 6.25e-3
    n = 100               # steps per branch

    mat = Steel01(id=1, Fy=fy, E0=e0, b=b)
    protocol = LoadProtocol(
        kind="cyclic",
        max_compressive=-ea,
        max_tensile=ea,
        n_steps_per_branch=n,
        cycles=[CyclicSegment(compressive_peak=-ea, tensile_peak=ea, n_cycles=3)],
    )
    result = test_uniaxial_material(mat, protocol)

    # Theoretical energy per stable cycle (EPP closed-form)
    e_ref = 4.0 * fy * (ea - ey)   # = 5 000 000 J/m^3

    pts_per_cycle = 3 * n   # = 300  (three branches per cycle)
    total_pts = len(result.strain)
    assert total_pts == 3 * pts_per_cycle, f"expected 900 points, got {total_pts}"

    for i_cycle in [1, 2]:   # stable cycles 1 and 2 (0-indexed); closed loops
        # Include the last point of the preceding cycle as the opening vertex
        # so the integration path is a closed loop.
        lo = i_cycle * pts_per_cycle - 1
        hi = (i_cycle + 1) * pts_per_cycle   # Python slice: exclusive upper bound
        strain_loop = result.strain[lo:hi]
        stress_loop = result.stress[lo:hi]
        assert len(strain_loop) == pts_per_cycle + 1  # 301 points

        # Trapezoidal area of closed stress-strain loop = dissipated energy.
        e_num = sum(
            0.5 * (stress_loop[j] + stress_loop[j + 1])
            * (strain_loop[j + 1] - strain_loop[j])
            for j in range(len(strain_loop) - 1)
        )
        assert abs(e_num) == pytest.approx(e_ref, rel=0.01), (
            f"cycle {i_cycle + 1}: numerical energy {abs(e_num):.4g} "
            f"vs reference {e_ref:.4g}"
        )


# ---- Concrete04 Popovics envelope ------------------------------------------


def test_concrete04_monotonic_popovics_envelope() -> None:
    """Concrete04: smooth Popovics ascent to peak with C1 continuity.

    Three checks:
    1. Stress is monotonically non-decreasing (numerically more negative)
       on the ascending branch (0 -> epsc0).
    2. Stress is monotonically non-increasing (numerically less negative)
       on the softening branch (epsc0 -> epscu).
    3. The tangent slope at the peak is near zero from both sides
       (C1 continuity -- no kink like Concrete01's bilinear softening).
    """
    fpc = -30e6
    epsc0 = -0.002
    epscu = -0.005
    ec = 30e9
    n_steps = 200   # enough resolution to detect a kink clearly

    mat = Concrete04(id=1, fpc=fpc, epsc0=epsc0, epscu=epscu, Ec=ec)
    protocol = LoadProtocol(
        kind="monotonic",
        max_compressive=epscu,
        n_steps_per_branch=n_steps,
    )
    result = test_uniaxial_material(mat, protocol)

    strain = result.strain
    stress = result.stress
    assert len(strain) == n_steps

    # Find the peak (most compressive = minimum stress value).
    peak_idx = stress.index(min(stress))
    assert peak_idx > 0, "peak at first step -- protocol or model may be wrong"
    assert peak_idx < len(stress) - 1, "peak at last step -- no softening branch captured"

    tol = 1e-3  # 1 mPa tolerance for floating-point monotonicity checks

    # Ascending branch: stress becomes monotonically more negative.
    for i in range(peak_idx):
        assert stress[i + 1] <= stress[i] + tol, (
            f"non-monotone ascending branch at index {i}: "
            f"stress[{i}]={stress[i]:.4g}, stress[{i + 1}]={stress[i + 1]:.4g}"
        )

    # Softening branch: stress becomes monotonically less negative.
    for i in range(peak_idx, len(stress) - 1):
        assert stress[i + 1] >= stress[i] - tol, (
            f"non-monotone softening branch at index {i}: "
            f"stress[{i}]={stress[i]:.4g}, stress[{i + 1}]={stress[i + 1]:.4g}"
        )

    # C1 continuity at peak: tangent slope ~ 0 from both sides.
    d_eps = strain[peak_idx] - strain[peak_idx - 1]   # negative step size
    slope_before = (stress[peak_idx] - stress[peak_idx - 1]) / d_eps
    slope_after = (stress[peak_idx + 1] - stress[peak_idx]) / (
        strain[peak_idx + 1] - strain[peak_idx]
    )

    # Both slopes must be near zero (Popovics curve is C1 at the peak).
    assert abs(slope_before) / ec < 0.05, (
        f"slope before peak too large: {slope_before / ec:.4f} x Ec"
    )
    assert abs(slope_after) / ec < 0.05, (
        f"slope after peak too large: {slope_after / ec:.4f} x Ec"
    )
    # No kink: slope change at the peak must be smooth (< 5% of Ec).
    assert abs(slope_before - slope_after) / ec < 0.05, (
        f"kink detected at peak: delta_slope = {abs(slope_before - slope_after) / ec:.4f} x Ec"
    )


# ---- state-cleanup proof ---------------------------------------------------


def test_state_cleanup_ten_consecutive_calls() -> None:
    """10 consecutive calls return identical results -- wipe() isolates each run."""
    e_mod = 70e9
    mat = ElasticUniaxial(id=1, E=e_mod)
    protocol = LoadProtocol(
        kind="monotonic",
        max_compressive=-0.005,
        max_tensile=0.005,
        n_steps_per_branch=20,
    )

    results = [test_uniaxial_material(mat, protocol) for _ in range(10)]

    ref_strain = results[0].strain
    ref_stress = results[0].stress
    for i, r in enumerate(results[1:], start=1):
        assert r.strain == pytest.approx(ref_strain, rel=1e-9), (
            f"strain diverged on call {i + 1}"
        )
        assert r.stress == pytest.approx(ref_stress, rel=1e-9), (
            f"stress diverged on call {i + 1}"
        )


# ---- interleave test -------------------------------------------------------


def test_interleave_with_runner_analysis() -> None:
    """Material tester between two runner analyses does not corrupt the runner.

    Sequence:
    1. Run a reference static analysis with OpenSeesRunner.
    2. Call test_uniaxial_material (resets the OpenSees domain).
    3. Re-run the same analysis.
    4. Assert that results 1 and 3 are identical to 1e-9 relative tolerance.
    """
    project = _simple_cantilever()
    case = project.analyses[0]
    runner = OpenSeesRunner(project)

    # Run 1.
    result1 = runner.run(case)

    # Interleaved material test (resets OpenSees state via wipe()).
    tester_mat = ElasticUniaxial(id=99, E=200e9)
    tester_protocol = LoadProtocol(
        kind="monotonic",
        max_compressive=-0.01,
        n_steps_per_branch=10,
    )
    test_uniaxial_material(tester_mat, tester_protocol)

    # Run 2 (runner calls wipe() internally, then rebuilds the domain).
    result2 = runner.run(case)

    # Uy at node 2 (DOF 1 in 0-indexed = DOF 2 in 1-indexed) must be identical.
    uy1 = float(result1.node_disp[2][0, 1])
    uy2 = float(result2.node_disp[2][0, 1])
    assert uy1 == pytest.approx(uy2, rel=1e-9), (
        f"runner Uy changed after interleaved material test: {uy1} vs {uy2}"
    )
