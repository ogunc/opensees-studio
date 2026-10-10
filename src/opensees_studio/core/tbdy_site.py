"""TBDY 2018 site coefficients and the design accelerations SDS, SD1.

Ported from the owner's cfs-egitim-app ``core/seismic/tbdy_spectrum.py``
(Tablo 2.1 and Tablo 2.2 of TBDY 2018, the Turkish Building Earthquake
Code), behaviour only: the tables, the clamped linear interpolation and
the ZF refusal are kept, the decimal rounding of the source is not.

    SDS = Ss Fs        Fs from Tablo 2.1 at Ss for the site class
    SD1 = S1 F1        F1 from Tablo 2.2 at S1 for the site class

Ss and S1 are the mapped short-period and 1 s spectral accelerations in
g for the site and earthquake level (DD-1 to DD-4) as read from the AFAD
TDTH map. Between two table breakpoints the coefficient is interpolated
linearly; below the first or above the last breakpoint the end value is
used. Site class ZF needs a site-specific investigation and is refused.

The DD-1 to DD-4 earthquake levels are carried as labels only: the
mapped values for a level come from the map, not from this module.

This module is part of ``core``: no Qt, no openseespy.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

import numpy as np

SiteClass = Literal["ZA", "ZB", "ZC", "ZD", "ZE", "ZF"]
EarthquakeLevel = Literal["DD-1", "DD-2", "DD-3", "DD-4"]

#: Site classes of TBDY 2018 Tablo 16.1; ZF is refused by the coefficient functions.
SITE_CLASSES: tuple[SiteClass, ...] = ("ZA", "ZB", "ZC", "ZD", "ZE", "ZF")

#: Earthquake ground motion levels of TBDY 2018 Md. 2.2 (labels only).
EARTHQUAKE_LEVELS: tuple[EarthquakeLevel, ...] = ("DD-1", "DD-2", "DD-3", "DD-4")

#: Display label per earthquake level: probability of exceedance in 50 years.
EARTHQUAKE_LEVEL_LABELS: dict[EarthquakeLevel, str] = {
    "DD-1": "DD-1 (2 % in 50 years)",
    "DD-2": "DD-2 (10 % in 50 years)",
    "DD-3": "DD-3 (50 % in 50 years)",
    "DD-4": "DD-4 (68 % in 50 years)",
}

#: TBDY 2018 Tablo 2.1, Fs: short-period site coefficient at these Ss breakpoints.
TBDY_SS_POINTS: tuple[float, ...] = (0.25, 0.50, 0.75, 1.00, 1.25, 1.50)
TBDY_FS_TABLE: dict[str, tuple[float, ...]] = {
    "ZA": (0.8, 0.8, 0.8, 0.8, 0.8, 0.8),
    "ZB": (0.9, 0.9, 0.9, 0.9, 0.9, 0.9),
    "ZC": (1.3, 1.3, 1.2, 1.2, 1.2, 1.2),
    "ZD": (1.6, 1.4, 1.2, 1.1, 1.0, 1.0),
    "ZE": (2.4, 1.7, 1.3, 1.1, 0.9, 0.8),
}

#: TBDY 2018 Tablo 2.2, F1: 1 s site coefficient at these S1 breakpoints.
TBDY_S1_POINTS: tuple[float, ...] = (0.10, 0.20, 0.30, 0.40, 0.50, 0.60)
TBDY_F1_TABLE: dict[str, tuple[float, ...]] = {
    "ZA": (0.8, 0.8, 0.8, 0.8, 0.8, 0.8),
    "ZB": (0.8, 0.8, 0.8, 0.8, 0.8, 0.8),
    "ZC": (1.5, 1.5, 1.5, 1.5, 1.5, 1.4),
    "ZD": (2.4, 2.2, 2.0, 1.9, 1.8, 1.7),
    "ZE": (4.2, 3.3, 2.8, 2.4, 2.2, 2.0),
}


def _check_site_class(site_class: str) -> None:
    if site_class == "ZF":
        raise ValueError(
            "Site class ZF needs a site-specific investigation (TBDY 2018); "
            "enter SDS and SD1 from that study instead."
        )
    if site_class not in TBDY_FS_TABLE:
        raise ValueError(f"Unknown site class '{site_class}'; expected one of ZA, ZB, ZC, ZD, ZE.")


def _interp_table(value: float, breaks: tuple[float, ...], coeffs: tuple[float, ...]) -> float:
    """Linear interpolation between table breakpoints, clamped outside the range."""
    if value < 0.0:
        raise ValueError(f"Mapped spectral accelerations must be >= 0, got {value}.")
    if value <= breaks[0]:
        return float(coeffs[0])
    if value >= breaks[-1]:
        return float(coeffs[-1])
    return float(np.interp(value, breaks, coeffs))


def tbdy2018_fs(ss: float, site_class: str) -> float:
    """Fs from TBDY 2018 Tablo 2.1 at ``ss`` for ``site_class`` (ZA to ZE)."""
    _check_site_class(site_class)
    return _interp_table(ss, TBDY_SS_POINTS, TBDY_FS_TABLE[site_class])


def tbdy2018_f1(s1: float, site_class: str) -> float:
    """F1 from TBDY 2018 Tablo 2.2 at ``s1`` for ``site_class`` (ZA to ZE)."""
    _check_site_class(site_class)
    return _interp_table(s1, TBDY_S1_POINTS, TBDY_F1_TABLE[site_class])


class SiteDesignAccelerations(NamedTuple):
    """Outcome of :func:`tbdy2018_design_accelerations`, all in g except the coefficients."""

    fs: float
    f1: float
    sds: float
    sd1: float


def tbdy2018_design_accelerations(ss: float, s1: float, site_class: str) -> SiteDesignAccelerations:
    """``(Fs, F1, SDS, SD1)`` for the mapped ``ss``, ``s1`` (g) and ``site_class``."""
    fs = tbdy2018_fs(ss, site_class)
    f1 = tbdy2018_f1(s1, site_class)
    return SiteDesignAccelerations(fs=fs, f1=f1, sds=ss * fs, sd1=s1 * f1)
