"""Elastic response spectra of an acceleration record (numpy only).

Method: the piecewise-exact recurrence of Nigam and Jennings (1969).
Between two samples the ground acceleration is taken as linear, and for
that excitation the damped linear SDOF equation

    u'' + 2 xi w u' + w^2 u = -a_g(t)

has a closed-form solution, so the state (u, u') is advanced one sample
at a time with constant coefficient matrices A and B that depend only
on (w, xi, dt). Chosen over Newmark average acceleration because it is
exact for the interpolated input: there is no period-elongation or
amplitude error at short periods (T close to dt), it is unconditionally
stable, and it needs no sub-stepping, so the spectrum depends only on
the record's own sampling and not on a solver step. The remaining
modelling assumption is the linear interpolation between samples, which
is also what OpenSees' ``timeSeries Path`` applies during a transient
analysis. Peaks are taken at the sample instants, so for periods shorter
than about ten times dt the true peak between two samples can be missed
by a few percent; the default grid starts at 0.01 s, which is fine for
records sampled at 0.005 s or finer at the PGA end (where the stiff
oscillator simply tracks the input).

Outputs per period T: Sd = max |u|, pseudo-velocity Sv = w Sd and
pseudo-acceleration Sa = w^2 Sd, all in the record's own units (Sa in
the acceleration unit of the samples, Sd in that unit times s^2). T = 0
is the rigid oscillator: Sa = PGA, Sd = Sv = 0.

This module is part of ``core``: no Qt, no openseespy.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

#: Default damping ratio for response spectra.
DEFAULT_DAMPING = 0.05

#: Default period grid: T = 0 plus DEFAULT_N_PERIODS log-spaced periods
#: between DEFAULT_T_MIN and DEFAULT_T_MAX seconds.
DEFAULT_T_MIN = 0.01
DEFAULT_T_MAX = 10.0
DEFAULT_N_PERIODS = 100


class ElasticSpectrum(NamedTuple):
    """Spectral ordinates on a period grid (record units, see module doc)."""

    periods: np.ndarray
    sd: np.ndarray
    sv: np.ndarray
    sa: np.ndarray
    damping: float


def default_periods(
    n: int = DEFAULT_N_PERIODS,
    t_min: float = DEFAULT_T_MIN,
    t_max: float = DEFAULT_T_MAX,
) -> np.ndarray:
    """T = 0 followed by ``n`` log-spaced periods from ``t_min`` to ``t_max``."""
    if n < 2 or t_min <= 0.0 or t_max <= t_min:
        raise ValueError("default_periods needs n >= 2 and 0 < t_min < t_max.")
    return np.concatenate(([0.0], np.geomspace(t_min, t_max, n)))


def _check_inputs(dt: float, accel: np.ndarray | list[float], damping: float) -> np.ndarray:
    if dt <= 0.0:
        raise ValueError(f"dt must be positive, got {dt}.")
    if not 0.0 <= damping < 1.0:
        raise ValueError(f"damping ratio must be in [0, 1), got {damping}.")
    a = np.asarray(accel, dtype=float)
    if a.ndim != 1 or a.size < 2:
        raise ValueError(f"accel must be a 1-D array with at least 2 samples, got shape {a.shape}.")
    return a


def _nigam_jennings_coefficients(
    omega: np.ndarray,
    damping: float,
    dt: float,
) -> tuple[np.ndarray, ...]:
    """Recurrence coefficients (a11, a12, a21, a22, b11, b12, b21, b22).

    Vectorised over ``omega``. Forcing sign convention: the state is
    advanced as ``x[i+1] = A x[i] + B [a_g[i], a_g[i+1]]`` for the
    equation ``u'' + 2 xi w u' + w^2 u = -a_g``.
    """
    xi = damping
    sq = np.sqrt(1.0 - xi * xi)
    wd = omega * sq
    w2 = omega * omega
    w3 = w2 * omega
    e = np.exp(-xi * omega * dt)
    s = np.sin(wd * dt)
    c = np.cos(wd * dt)

    a11 = e * (xi / sq * s + c)
    a12 = e / wd * s
    a21 = -omega / sq * e * s
    a22 = e * (c - xi / sq * s)

    k1 = (2.0 * xi * xi - 1.0) / (w2 * dt)
    k2 = 2.0 * xi / (w3 * dt)
    b11 = e * ((k1 + xi / omega) * s / wd + (k2 + 1.0 / w2) * c) - k2
    b12 = -e * (k1 * s / wd + k2 * c) - 1.0 / w2 + k2
    ds = c - xi / sq * s  # d/dt of (e * s / wd) without the e factor, times 1
    dc = wd * s + xi * omega * c
    b21 = e * ((k1 + xi / omega) * ds - (k2 + 1.0 / w2) * dc) + 1.0 / (w2 * dt)
    b22 = -e * (k1 * ds - k2 * dc) - 1.0 / (w2 * dt)
    return a11, a12, a21, a22, b11, b12, b21, b22


def sdof_response(
    dt: float,
    accel: np.ndarray | list[float],
    period: float,
    damping: float = DEFAULT_DAMPING,
) -> tuple[np.ndarray, np.ndarray]:
    """Relative displacement and velocity histories of one oscillator.

    Returns ``(u, v)`` sampled at the record's instants, starting from
    rest. Mainly for verification; :func:`response_spectrum` computes
    all periods at once.
    """
    a = _check_inputs(dt, accel, damping)
    if period <= 0.0:
        raise ValueError(f"period must be positive, got {period}.")
    omega = np.array([2.0 * np.pi / period])
    a11, a12, a21, a22, b11, b12, b21, b22 = _nigam_jennings_coefficients(omega, damping, dt)
    u = np.zeros(a.size)
    v = np.zeros(a.size)
    for i in range(a.size - 1):
        u[i + 1] = a11[0] * u[i] + a12[0] * v[i] + b11[0] * a[i] + b12[0] * a[i + 1]
        v[i + 1] = a21[0] * u[i] + a22[0] * v[i] + b21[0] * a[i] + b22[0] * a[i + 1]
    return u, v


def response_spectrum(
    dt: float,
    accel: np.ndarray | list[float],
    damping: float = DEFAULT_DAMPING,
    periods: np.ndarray | list[float] | None = None,
) -> ElasticSpectrum:
    """Elastic Sd, pseudo-Sv and pseudo-Sa of ``accel`` on ``periods``.

    ``periods`` defaults to :func:`default_periods`; any T = 0 entries
    give the PGA. Ordinates are in the record's units.
    """
    a = _check_inputs(dt, accel, damping)
    t = default_periods() if periods is None else np.asarray(periods, dtype=float)
    if t.ndim != 1 or t.size == 0 or np.any(t < 0.0):
        raise ValueError("periods must be a non-empty 1-D array of T >= 0.")

    sd = np.zeros(t.size)
    pga = float(np.max(np.abs(a)))
    sa = np.full(t.size, pga)
    sv = np.zeros(t.size)

    flexible = t > 0.0
    if np.any(flexible):
        omega = 2.0 * np.pi / t[flexible]
        a11, a12, a21, a22, b11, b12, b21, b22 = _nigam_jennings_coefficients(omega, damping, dt)
        u = np.zeros(omega.size)
        v = np.zeros(omega.size)
        umax = np.zeros(omega.size)
        for i in range(a.size - 1):
            u, v = (
                a11 * u + a12 * v + b11 * a[i] + b12 * a[i + 1],
                a21 * u + a22 * v + b21 * a[i] + b22 * a[i + 1],
            )
            np.maximum(umax, np.abs(u), out=umax)
        sd[flexible] = umax
        sv[flexible] = omega * umax
        sa[flexible] = omega * omega * umax
    return ElasticSpectrum(periods=t, sd=sd, sv=sv, sa=sa, damping=float(damping))
