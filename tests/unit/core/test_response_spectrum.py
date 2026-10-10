"""Elastic response spectrum (Nigam-Jennings) verification tests.

Tolerances, and why:

* T = 0 and the very short period: Sa equals PGA exactly at T = 0 and
  within 2 % at T = 0.01 s for a record sampled at 0.005 s (the stiff
  oscillator tracks the input; the residual is dynamic amplification of
  the record's highest-frequency content).
* Long period: Sd approaches PGD within 1 % at T = 50 s for a 2 s
  displacement pulse (the mass stays still, u = -u_g up to (tau/T)^2).
* Resonance: the closed-form steady-state magnification 1/(2 xi) is met
  within 1e-3 after 60 cycles (the transient decays as exp(-xi w t), and
  the piecewise-linear sampling at 100 points per cycle carries a 3e-4
  amplitude bias).
* dt independence: a linearly upsampled record reproduces the coarse
  response history to 1e-9 (the method is exact for piecewise-linear
  input) and its Sd agrees within 1 %; a sine resampled at 4 times the
  rate agrees within 1 %.
* Independent method: Newmark average acceleration with 50 sub-steps
  (its period elongation is (w h)^2 / 12 per cycle, which over the 75
  undamped cycles of the 0.2 s case is what sets the 1e-3 tolerance)
  agrees within 1e-3 for T >= 0.2 s at dt = 0.01 s, peaks compared at
  the record's own instants.
"""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import (
    ElasticSpectrum,
    default_periods,
    response_spectrum,
    sdof_response,
)


def _newmark_sd(
    dt: float, accel: np.ndarray, period: float, damping: float, sub: int = 50
) -> float:
    """Peak |u| by Newmark average acceleration on a ``sub``-times finer grid."""
    w = 2.0 * np.pi / period
    k, c = w * w, 2.0 * damping * w
    h = dt / sub
    t = np.arange(accel.size) * dt
    tf = np.arange((accel.size - 1) * sub + 1) * h
    af = np.interp(tf, t, accel)
    u = v = 0.0
    acc = -af[0]
    umax = 0.0
    keff = k + 4.0 / h**2 + 2.0 * c / h
    for i in range(af.size - 1):
        peff = -af[i + 1] + (4.0 / h**2 * u + 4.0 / h * v + acc) + c * (2.0 / h * u + v)
        un = peff / keff
        vn = 2.0 / h * (un - u) - v
        accn = 4.0 / h**2 * (un - u) - 4.0 / h * v - acc
        u, v, acc = un, vn, accn
        if (i + 1) % sub == 0:  # peak over the record's own instants, like the spectrum
            umax = max(umax, abs(u))
    return umax


@pytest.fixture
def broadband() -> tuple[float, np.ndarray]:
    """A smooth, zero-mean, band-limited synthetic record at dt = 0.005 s."""
    dt = 0.005
    t = np.arange(0.0, 20.0, dt)
    rng = np.random.default_rng(7)
    a = np.zeros_like(t)
    for f in np.linspace(0.3, 8.0, 25):
        a += rng.uniform(0.2, 1.0) * np.sin(2.0 * np.pi * f * t + rng.uniform(0, 2 * np.pi))
    a *= np.exp(-((t - 8.0) ** 2) / 20.0)  # envelope: starts and ends near zero
    return dt, a


def test_default_periods_grid() -> None:
    p = default_periods()
    assert p[0] == 0.0
    assert p[1] == pytest.approx(0.01)
    assert p[-1] == pytest.approx(10.0)
    assert p.size == 101
    assert np.all(np.diff(p) > 0)


def test_returns_named_tuple_in_record_units(broadband) -> None:  # type: ignore[no-untyped-def]
    dt, a = broadband
    rs = response_spectrum(dt, a, periods=[0.0, 0.5, 1.0])
    assert isinstance(rs, ElasticSpectrum)
    assert rs.damping == 0.05
    w = 2.0 * np.pi / rs.periods[1:]
    assert rs.sv[1:] == pytest.approx(w * rs.sd[1:])
    assert rs.sa[1:] == pytest.approx(w * w * rs.sd[1:])
    assert rs.sd[0] == 0.0 and rs.sv[0] == 0.0


def test_sa_at_zero_and_very_short_period_is_pga(broadband) -> None:  # type: ignore[no-untyped-def]
    dt, a = broadband
    pga = float(np.max(np.abs(a)))
    rs = response_spectrum(dt, a, periods=[0.0, 0.01])
    assert rs.sa[0] == pga
    assert rs.sa[1] == pytest.approx(pga, rel=2e-2)


def test_sd_at_long_period_approaches_pgd() -> None:
    """Ground displacement pulse u_g = D sin^2(pi t / tau) on [0, tau].

    Its acceleration is analytic, so the record has a clean, drift-free
    displacement history with PGD = D.
    """
    dt, tau, D = 0.005, 2.0, 0.1
    t = np.arange(0.0, 30.0, dt)
    inside = t <= tau
    accel = np.zeros_like(t)
    accel[inside] = 2.0 * D * (np.pi / tau) ** 2 * np.cos(2.0 * np.pi * t[inside] / tau)
    rs = response_spectrum(dt, accel, damping=0.05, periods=[50.0])
    assert rs.sd[0] == pytest.approx(D, rel=1e-2)


def test_resonant_harmonic_matches_steady_state_magnification() -> None:
    period, xi, amp = 1.0, 0.05, 1.0
    w = 2.0 * np.pi / period
    dt = period / 100.0
    t = np.arange(0.0, 60.0 * period, dt)
    accel = amp * np.sin(w * t)
    rs = response_spectrum(dt, accel, damping=xi, periods=[period])
    assert rs.sa[0] == pytest.approx(amp / (2.0 * xi), rel=1e-3)
    assert rs.sd[0] == pytest.approx(amp / (2.0 * xi * w * w), rel=1e-3)


def test_zero_damping_resonance_grows_linearly() -> None:
    """Undamped resonance: |u| ~ (amp t)/(2 w) envelope, so Sd grows with duration."""
    period, w = 0.5, 2.0 * np.pi / 0.5
    dt = period / 50.0
    t1 = np.arange(0.0, 10.0 * period, dt)
    t2 = np.arange(0.0, 20.0 * period, dt)
    sd1 = response_spectrum(dt, np.sin(w * t1), damping=0.0, periods=[period]).sd[0]
    sd2 = response_spectrum(dt, np.sin(w * t2), damping=0.0, periods=[period]).sd[0]
    assert sd2 / sd1 == pytest.approx(2.0, rel=5e-2)


def test_linearly_upsampled_record_gives_identical_response(broadband) -> None:  # type: ignore[no-untyped-def]
    """Exact for piecewise-linear input: the finer run reproduces the coarse
    instants to 1e-9; its peak can only be larger (more instants checked)."""
    dt, a = broadband
    t = np.arange(a.size) * dt
    t4 = np.arange((a.size - 1) * 4 + 1) * (dt / 4.0)
    a4 = np.interp(t4, t, a)
    for period in (0.05, 0.2, 1.0, 4.0):
        u, _v = sdof_response(dt, a, period)
        u4, _v4 = sdof_response(dt / 4.0, a4, period)
        assert u4[::4] == pytest.approx(u, rel=1e-9, abs=1e-9 * float(np.max(np.abs(u))))
    periods = [0.05, 0.2, 1.0, 4.0]
    rs = response_spectrum(dt, a, periods=periods)
    rs4 = response_spectrum(dt / 4.0, a4, periods=periods)
    assert np.all(rs4.sd >= rs.sd * (1.0 - 1e-12))
    assert rs4.sd == pytest.approx(rs.sd, rel=1e-2)


def test_resampled_sine_agrees_within_one_percent() -> None:
    w = 2.0 * np.pi / 0.8
    periods = [0.2, 0.8, 2.0]
    spectra = []
    for dt in (0.02, 0.005):
        t = np.arange(0.0, 20.0, dt)
        spectra.append(response_spectrum(dt, np.sin(w * t), periods=periods).sd)
    assert spectra[1] == pytest.approx(spectra[0], rel=1e-2)


@pytest.mark.parametrize("period", [0.2, 1.0, 3.0])
@pytest.mark.parametrize("damping", [0.0, 0.05, 0.2])
def test_matches_newmark_average_acceleration(period: float, damping: float) -> None:
    dt = 0.01
    rng = np.random.default_rng(0)
    a = np.convolve(rng.standard_normal(1500) * 0.3, np.ones(5) / 5.0, mode="same")
    rs = response_spectrum(dt, a, damping=damping, periods=[period])
    assert rs.sd[0] == pytest.approx(_newmark_sd(dt, a, period, damping), rel=1e-3)


def test_sdof_response_history_peak_equals_spectrum(broadband) -> None:  # type: ignore[no-untyped-def]
    dt, a = broadband
    u, v = sdof_response(dt, a, period=0.7)
    assert u.shape == a.shape and v.shape == a.shape
    assert u[0] == 0.0 and v[0] == 0.0
    rs = response_spectrum(dt, a, periods=[0.7])
    assert float(np.max(np.abs(u))) == pytest.approx(rs.sd[0], rel=1e-12)


def test_invalid_inputs_raise(broadband) -> None:  # type: ignore[no-untyped-def]
    dt, a = broadband
    with pytest.raises(ValueError, match="dt must be positive"):
        response_spectrum(0.0, a)
    with pytest.raises(ValueError, match="damping ratio"):
        response_spectrum(dt, a, damping=1.0)
    with pytest.raises(ValueError, match="periods"):
        response_spectrum(dt, a, periods=[-1.0])
    with pytest.raises(ValueError, match="at least 2 samples"):
        response_spectrum(dt, [1.0])
    with pytest.raises(ValueError, match="period must be positive"):
        sdof_response(dt, a, period=0.0)
    with pytest.raises(ValueError):
        default_periods(n=1)
