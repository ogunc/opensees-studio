"""Ground-motion record scaling: PGA, Sa(T1) and period-range methods.

Every function here returns factors and diagnostics without mutating a
record, a series or the project. The caller (the Ground Motions dialog
through one undoable command) writes the factor to the
``PathTimeSeries.factor`` of the series backed by the record; that is
the one place a scale lives, the catalog entry never changes.

Units. All comparisons happen in g: the target spectrum is in g and a
record's samples are brought to g with :func:`accel_in_g` from the
catalog entry's ``accel_units`` and the project unit system. A record
whose units are ``"unknown"`` is refused with a clear message. The
dimensionless amplitude factor ``k`` returned by the methods multiplies
the record *in g*; :func:`series_factor` turns it into the value to
write on the series, which also carries the g to project-unit
conversion (``k * g`` for a record in g, ``k`` for one already in
project units).

Period-range method (c). On a log-spaced grid over ``[a T1, b T1]`` the
mean spectrum of the scaled set must not fall below ``alpha`` times the
target. With ``individual=False`` one factor scales every member so
that the minimum of ``mean / (alpha target)`` over the range is exactly
1, reached at the governing period. With ``individual=True`` each
member is first normalised to the target over the range (its factor is
the log-space least-squares fit ``exp(mean(log(target / Sa)))``, so
every member's shape is centred on the target) and the same uniform
step is then applied to the normalised set, so the criterion is met the
same way and the reported minimum ratio is again ``alpha`` at the
governing period. When horizontal ``pairs`` are given, a pair is one
member with the SRSS of its two component spectra and both components
share the factor. The preset ``TBDY_RANGE_PRESET`` (a = 0.2, b = 1.5,
alpha = 1.3 for SRSS pairs) is marked "engineer to confirm": check it
against the current text of the standard before relying on it.

This module is part of ``core``: no Qt, no openseespy.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

import numpy as np

from opensees_studio.core.ground_motion import GroundMotionAccelUnits
from opensees_studio.core.response_spectrum import DEFAULT_DAMPING, response_spectrum
from opensees_studio.core.target_spectrum import TargetSpectrum
from opensees_studio.core.units import UnitSystem, gravity

ScalingMethod = Literal["pga", "sa_t1", "period_range"]


class RangePreset(NamedTuple):
    """Period-range bounds ``[a T1, b T1]`` and the mean-spectrum floor ``alpha``."""

    a: float
    b: float
    alpha: float
    label: str


#: TBDY 2018 style preset for the period-range method. alpha = 1.3 is
#: the SRSS-of-two-components floor; for single-component sets alpha is
#: the caller's choice. Engineer to confirm against the standard text.
TBDY_RANGE_PRESET = RangePreset(a=0.2, b=1.5, alpha=1.3, label="TBDY 2018 (engineer to confirm)")

#: Points on the log-spaced period grid used by the period-range method.
RANGE_GRID_POINTS = 60


def unknown_units_message(record_name: str) -> str:
    return (
        f"Record '{record_name}' has unknown acceleration units. Set them to g or "
        "to project units in Define > Ground Motions before scaling it."
    )


def accel_in_g(
    accel: np.ndarray | list[float],
    accel_units: GroundMotionAccelUnits,
    unit_system: UnitSystem,
    record_name: str = "",
) -> np.ndarray:
    """The record's samples expressed in g.

    Raises:
        ValueError: ``accel_units == "unknown"``.
    """
    a = np.asarray(accel, dtype=float)
    if accel_units == "g":
        return a
    if accel_units == "project":
        return a / gravity(unit_system)
    raise ValueError(unknown_units_message(record_name))


def series_factor(k: float, accel_units: GroundMotionAccelUnits, unit_system: UnitSystem) -> float:
    """The ``PathTimeSeries.factor`` that applies amplitude ``k`` to a record.

    A record in g also needs the g to project-unit conversion; one in
    project units does not.
    """
    if accel_units == "g":
        return k * gravity(unit_system)
    if accel_units == "project":
        return k
    raise ValueError(unknown_units_message(""))


# ---------------------------------------------------------------- (a) PGA
def pga_scale_factor(accel_g: np.ndarray | list[float], target_pga_g: float) -> float:
    """Amplitude ``k`` such that ``k * PGA`` equals ``target_pga_g``."""
    if target_pga_g <= 0.0:
        raise ValueError(f"target PGA must be positive, got {target_pga_g}.")
    pga = float(np.max(np.abs(np.asarray(accel_g, dtype=float))))
    if pga <= 0.0:
        raise ValueError("The record is all zeros; it cannot be scaled to a PGA.")
    return target_pga_g / pga


# ------------------------------------------------------------- (b) Sa(T1)
def sa_t1_scale_factor(
    dt: float,
    accel_g: np.ndarray | list[float],
    target: TargetSpectrum,
    t1: float,
    damping: float = DEFAULT_DAMPING,
) -> float:
    """Amplitude ``k`` such that the record's Sa(T1) equals the target's."""
    if t1 <= 0.0:
        raise ValueError(f"T1 must be positive, got {t1}.")
    sa_record = float(response_spectrum(dt, accel_g, damping, periods=[t1]).sa[0])
    if sa_record <= 0.0:
        raise ValueError("The record's Sa(T1) is zero; it cannot be scaled at T1.")
    return float(target.sa_at(t1)[0]) / sa_record


# ------------------------------------------------------- (c) period range
class RangeScalingResult(NamedTuple):
    """Outcome of :func:`period_range_scale_factors`."""

    factors: dict[int, float]
    """Amplitude factor per record id (components of a pair share one)."""
    periods: np.ndarray
    """The log-spaced grid over ``[a T1, b T1]``."""
    target_sa: np.ndarray
    """Target Sa (g) on the grid."""
    mean_sa: np.ndarray
    """Mean spectrum (g) of the unscaled set on the grid."""
    scaled_mean_sa: np.ndarray
    """Mean spectrum (g) of the scaled set on the grid."""
    governing_period: float
    """Period where ``scaled_mean / target`` is smallest."""
    min_ratio: float
    """``scaled_mean / target`` at the governing period (equals alpha)."""
    alpha: float


def _member_spectra(
    records: dict[int, tuple[float, np.ndarray]],
    pairs: list[tuple[int, int]] | None,
    periods: np.ndarray,
    damping: float,
) -> list[tuple[tuple[int, ...], np.ndarray]]:
    """(member record ids, member Sa on the grid) with SRSS for pairs."""
    spectra = {
        rid: response_spectrum(dt, accel, damping, periods=periods).sa
        for rid, (dt, accel) in records.items()
    }
    members: list[tuple[tuple[int, ...], np.ndarray]] = []
    if pairs:
        used: set[int] = set()
        for h1, h2 in pairs:
            if h1 not in spectra or h2 not in spectra:
                raise ValueError(f"pair ({h1}, {h2}) names a record that is not in the set.")
            if h1 in used or h2 in used or h1 == h2:
                raise ValueError(f"record ids in pairs must be distinct, got pair ({h1}, {h2}).")
            used.update((h1, h2))
            members.append(((h1, h2), np.sqrt(spectra[h1] ** 2 + spectra[h2] ** 2)))
        for rid in spectra:
            if rid not in used:
                raise ValueError(f"record {rid} is not part of any pair.")
    else:
        members = [((rid,), sa) for rid, sa in spectra.items()]
    return members


def period_range_scale_factors(
    records: dict[int, tuple[float, np.ndarray | list[float]]],
    target: TargetSpectrum,
    t1: float,
    a: float = TBDY_RANGE_PRESET.a,
    b: float = TBDY_RANGE_PRESET.b,
    alpha: float = TBDY_RANGE_PRESET.alpha,
    individual: bool = False,
    pairs: list[tuple[int, int]] | None = None,
    damping: float = DEFAULT_DAMPING,
    n_periods: int = RANGE_GRID_POINTS,
) -> RangeScalingResult:
    """Factors so the mean scaled spectrum is not below ``alpha`` times the target.

    ``records`` maps record id to ``(dt, accel_in_g)``. See the module
    doc for the uniform / individual choice and for pairs.
    """
    if not records:
        raise ValueError("No records to scale.")
    if t1 <= 0.0 or a <= 0.0 or b <= a or alpha <= 0.0:
        raise ValueError("Need T1 > 0, 0 < a < b and alpha > 0.")
    if n_periods < 2:
        raise ValueError("n_periods must be at least 2.")
    periods = np.geomspace(a * t1, b * t1, n_periods)
    target_sa = target.sa_at(periods)
    if np.any(target_sa <= 0.0):
        raise ValueError("The target spectrum is zero somewhere in the range.")
    prepared = {rid: (dt, np.asarray(acc, dtype=float)) for rid, (dt, acc) in records.items()}
    members = _member_spectra(prepared, pairs, periods, damping)
    for ids, sa in members:
        if np.any(sa <= 0.0):
            raise ValueError(f"record(s) {ids} have a zero spectral ordinate in the range.")

    mean_sa = np.mean([sa for _ids, sa in members], axis=0)
    if individual:
        normalise = [float(np.exp(np.mean(np.log(target_sa / sa)))) for _ids, sa in members]
    else:
        normalise = [1.0] * len(members)
    normalised_mean = np.mean(
        [k * sa for k, (_ids, sa) in zip(normalise, members, strict=True)], axis=0
    )
    ratio = normalised_mean / (alpha * target_sa)
    i_gov = int(np.argmin(ratio))
    uniform = 1.0 / float(ratio[i_gov])

    factors: dict[int, float] = {}
    for k, (ids, _sa) in zip(normalise, members, strict=True):
        for rid in ids:
            factors[rid] = k * uniform
    scaled_mean = uniform * normalised_mean
    return RangeScalingResult(
        factors=factors,
        periods=periods,
        target_sa=target_sa,
        mean_sa=mean_sa,
        scaled_mean_sa=scaled_mean,
        governing_period=float(periods[i_gov]),
        min_ratio=float(scaled_mean[i_gov] / target_sa[i_gov]),
        alpha=alpha,
    )
