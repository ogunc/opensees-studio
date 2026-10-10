"""Ground-motion intensity measures against closed-form cases."""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import (
    arias_intensity,
    compute_metadata,
    pga,
    pgd,
    pgv,
    significant_duration_5_95,
    total_duration,
)

# A 1 Hz sine sampled densely over whole cycles: every closed form below
# is exact up to discretisation error.
AMP = 3.0
FREQ = 1.0
OMEGA = 2.0 * np.pi * FREQ
DT = 1.0e-3
T_END = 10.0
N = round(T_END / DT) + 1


@pytest.fixture(scope="module")
def sine() -> np.ndarray:
    t = np.arange(N) * DT
    return AMP * np.sin(OMEGA * t)


def test_pga_of_sine_is_amplitude_at_first_peak(sine) -> None:
    value, time = pga(DT, sine)
    assert value == pytest.approx(AMP, rel=1e-9)
    # First peak of sin at a quarter period.
    assert time == pytest.approx(0.25 / FREQ, abs=DT)


def test_pgv_of_sine_matches_amp_over_omega(sine) -> None:
    # v(t) = (A/w) (1 - cos wt) has mean A/w and zero slope over whole
    # cycles; the linear detrend removes exactly that mean, leaving
    # -(A/w) cos wt with peak A/w.
    assert pgv(DT, sine) == pytest.approx(AMP / OMEGA, rel=1e-4)


def test_pgd_of_sine_matches_amp_over_omega_squared(sine) -> None:
    # After detrend, v = -(A/w) cos wt integrates to -(A/w^2) sin wt.
    # The residual detrend slope (endpoint asymmetry of the fit) grows
    # quadratically once integrated, so PGD is the least exact measure:
    # about 0.6 % here. That is inherent to linear-detrend baseline
    # correction, hence the loose tolerance.
    assert pgd(DT, sine) == pytest.approx(AMP / OMEGA**2, rel=1e-2)


def test_arias_of_sine_matches_closed_form(sine) -> None:
    # Ia = pi/(2g) * integral(A^2 sin^2) = pi/(2g) * A^2 T / 2 over whole cycles.
    g = 9.80665
    expected = np.pi / (2.0 * g) * AMP**2 * T_END / 2.0
    assert arias_intensity(DT, sine, g) == pytest.approx(expected, rel=1e-6)


def test_arias_with_g_of_one_for_records_in_g() -> None:
    a = np.ones(1001) * 0.5
    # Constant |a| = 0.5 g for 1 s: Ia = pi/2 * 0.25 * 1.0 in g units.
    assert arias_intensity(1.0e-3, a, g=1.0) == pytest.approx(np.pi / 2.0 * 0.25, rel=1e-6)


def test_d5_95_of_single_pulse_is_zero() -> None:
    a = np.zeros(1000)
    a[400] = 5.0
    t5, t95, d = significant_duration_5_95(0.01, a)
    # All the energy arrives in one sample: the 5 % and 95 % crossings
    # coincide there (within one dt).
    assert t5 == pytest.approx(4.0, abs=0.01)
    assert t95 == pytest.approx(4.0, abs=0.01)
    assert d == pytest.approx(0.0, abs=0.01)


def test_d5_95_of_constant_burst_covers_90_percent_of_it() -> None:
    # Zero everywhere except a constant-amplitude burst from t=2 s to
    # t=3 s: cumulative energy rises linearly across the burst, so the
    # 5 %..95 % window is 0.9 of the burst length.
    dt = 1.0e-3
    n = 5001
    a = np.zeros(n)
    t = np.arange(n) * dt
    a[(t >= 2.0) & (t <= 3.0)] = 1.0
    t5, t95, d = significant_duration_5_95(dt, a)
    assert t5 == pytest.approx(2.05, abs=2 * dt)
    assert t95 == pytest.approx(2.95, abs=2 * dt)
    assert d == pytest.approx(0.9, abs=4 * dt)


def test_d5_95_rejects_zero_record() -> None:
    with pytest.raises(ValueError, match="zero energy"):
        significant_duration_5_95(0.01, np.zeros(100))


def test_total_duration() -> None:
    assert total_duration(0.02, np.zeros(1001)) == pytest.approx(20.0)


def test_compute_metadata_bundles_everything(sine) -> None:
    md = compute_metadata(DT, sine)
    assert md.pga == pytest.approx(AMP, rel=1e-9)
    assert md.pgv == pytest.approx(AMP / OMEGA, rel=1e-4)
    assert md.duration == pytest.approx(T_END)
    assert md.t95 > md.t5
    assert md.d5_95 == pytest.approx(md.t95 - md.t5)


def test_rejects_scalar_or_too_short_input() -> None:
    with pytest.raises(ValueError, match="at least 2 samples"):
        pga(0.01, [1.0])
