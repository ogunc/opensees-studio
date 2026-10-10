"""Ground-motion intensity measures: pure numpy functions on (dt, accel).

All functions take the sampling interval ``dt`` (s) and the acceleration
samples as a 1-D array. Units are whatever the record carries; the
returned measures are in consistent derived units (PGV in accel*s,
Arias in accel^2*s / (2g/pi), ...).

Baseline correction: velocity is obtained by trapezoidal integration of
the acceleration, then a least-squares straight line is subtracted from
the velocity (linear detrend). This removes the spurious drift caused by
an unknown initial velocity and any constant baseline offset in the
record, and is the standard minimum correction for computing PGV/PGD
from an uncorrected record. Displacement is the trapezoidal integral of
the detrended velocity. No filtering is applied - heavier processing is
the responsibility of the record provider.

D5-95 timestamps are snapped to the sample grid: t5 (t95) is the time of
the first sample whose cumulative Arias intensity reaches 5 % (95 %) of
the total, so each is accurate to one dt.

This module is part of ``core``: no Qt, no openseespy.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

#: Standard gravity in m/s^2, the default for Arias intensity when the
#: record is in SI project units.
G_SI = 9.80665


def _as_array(accel: np.ndarray | list[float]) -> np.ndarray:
    a = np.asarray(accel, dtype=float)
    if a.ndim != 1 or a.size < 2:
        raise ValueError(f"accel must be a 1-D array with at least 2 samples, got shape {a.shape}.")
    return a


def _cumtrapz(dt: float, y: np.ndarray) -> np.ndarray:
    """Cumulative trapezoidal integral of ``y``, starting at 0."""
    out = np.empty_like(y)
    out[0] = 0.0
    np.cumsum((y[1:] + y[:-1]) * (0.5 * dt), out=out[1:])
    return out


def pga(dt: float, accel: np.ndarray | list[float]) -> tuple[float, float]:
    """Peak ground acceleration and the time it occurs at.

    Returns ``(value, time)`` where ``value`` is the peak of ``|a(t)|``
    (always non-negative) and ``time`` is the time of its first occurrence.
    """
    a = _as_array(accel)
    idx = int(np.argmax(np.abs(a)))
    return float(np.abs(a[idx])), idx * dt


def velocity(dt: float, accel: np.ndarray | list[float]) -> np.ndarray:
    """Baseline-corrected velocity: trapezoidal integral, linearly detrended."""
    a = _as_array(accel)
    v = _cumtrapz(dt, a)
    t = np.arange(a.size) * dt
    slope, intercept = np.polyfit(t, v, 1)
    return v - (slope * t + intercept)


def displacement(dt: float, accel: np.ndarray | list[float]) -> np.ndarray:
    """Displacement: trapezoidal integral of the baseline-corrected velocity."""
    return _cumtrapz(dt, velocity(dt, accel))


def pgv(dt: float, accel: np.ndarray | list[float]) -> float:
    """Peak ground velocity, from the baseline-corrected velocity."""
    return float(np.max(np.abs(velocity(dt, accel))))


def pgd(dt: float, accel: np.ndarray | list[float]) -> float:
    """Peak ground displacement, from the doubly integrated record."""
    return float(np.max(np.abs(displacement(dt, accel))))


def arias_intensity(dt: float, accel: np.ndarray | list[float], g: float = G_SI) -> float:
    """Arias intensity ``Ia = pi / (2 g) * integral(a(t)^2 dt)``.

    ``g`` must be expressed in the same units as ``accel`` (e.g. 9.80665
    for a record in m/s^2, 1.0 for a record in g). The result then has
    units of accel * s (m/s for SI).
    """
    a = _as_array(accel)
    return float(np.pi / (2.0 * g) * _cumtrapz(dt, a * a)[-1])


def significant_duration_5_95(
    dt: float,
    accel: np.ndarray | list[float],
) -> tuple[float, float, float]:
    """D5-95 significant duration from the cumulative Arias intensity.

    Returns ``(t5, t95, d5_95)``: the times where the cumulative Arias
    intensity first reaches 5 % and 95 % of its total, and their
    difference. Each time is snapped to the sample grid (see module
    docstring).

    Raises:
        ValueError: the record has zero energy (all samples 0).
    """
    a = _as_array(accel)
    cum = _cumtrapz(dt, a * a)
    total = cum[-1]
    if total <= 0.0:
        raise ValueError("Record has zero energy; D5-95 is undefined.")
    t5 = float(np.argmax(cum >= 0.05 * total)) * dt
    t95 = float(np.argmax(cum >= 0.95 * total)) * dt
    return t5, t95, t95 - t5


def total_duration(dt: float, accel: np.ndarray | list[float]) -> float:
    """Record length ``(npts - 1) * dt``."""
    return (_as_array(accel).size - 1) * dt


class GroundMotionMetadata(NamedTuple):
    """All intensity measures of a record in one bundle."""

    pga: float
    pga_time: float
    pgv: float
    pgd: float
    arias: float
    t5: float
    t95: float
    d5_95: float
    duration: float


def compute_metadata(
    dt: float,
    accel: np.ndarray | list[float],
    g: float = G_SI,
) -> GroundMotionMetadata:
    """Convenience: every measure of this module in one call."""
    peak, peak_time = pga(dt, accel)
    t5, t95, d5_95 = significant_duration_5_95(dt, accel)
    return GroundMotionMetadata(
        pga=peak,
        pga_time=peak_time,
        pgv=pgv(dt, accel),
        pgd=pgd(dt, accel),
        arias=arias_intensity(dt, accel, g),
        t5=t5,
        t95=t95,
        d5_95=d5_95,
        duration=total_duration(dt, accel),
    )
