"""Target spectra: the TBDY 2018 horizontal design spectrum and user tables.

TBDY 2018 (Turkish Building Earthquake Code), horizontal elastic design
spectrum Sae(T) from the mapped short-period and 1 s design spectral
accelerations SDS and SD1. They are either given directly (site-class
amplification already inside them) or derived from the mapped Ss and S1
of the AFAD TDTH map for the site and earthquake level DD-1 to DD-4 and
the site class through the TBDY 2018 site coefficients of
:mod:`opensees_studio.core.tbdy_site` (SDS = Ss Fs, SD1 = S1 F1):

    TA = 0.2 SD1 / SDS,  TB = SD1 / SDS,  TL = 6 s

    T <  TA        Sae = (0.4 + 0.6 T / TA) SDS
    TA <= T <= TB  Sae = SDS
    TB <  T <= TL  Sae = SD1 / T
    T >  TL        Sae = SD1 TL / T^2

The vertical elastic design spectrum SaeD(T) of TBDY 2018 Md. 2.3.5 is
built from the same SDS and SD1, ported from the owner's cfs-egitim-app
``core/seismic/tbdy_spectrum.py`` (``saed``) without its corner rounding:

    TAD = TA / 3,  TBD = TB / 3,  TLD = TL / 2

    T <= TAD        SaeD = (0.32 + 0.48 T / TAD) SDS
    TAD < T <= TBD  SaeD = 0.8 SDS
    T >  TBD        SaeD = 0.8 SDS TBD / T   (the same hyperbola past TLD)

All ordinates are in units of g. A :class:`TargetSpectrum` of kind
``"user"`` is a period versus Sa table (also in g) interpolated log-log
between its points and clamped to the end values outside them.

This module is part of ``core``: no Qt, no openseespy.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from pydantic import Field, PositiveFloat, model_validator

from opensees_studio.core._base import Entity
from opensees_studio.core.asce7 import (
    ASCE_SITE_CLASSES,
    TL_DEFAULT,
    asce7_corner_periods,
    asce7_design_spectrum,
    asce7_design_values,
)
from opensees_studio.core.loads import ResponseSpectrum
from opensees_studio.core.response_spectrum import four_branch_spectrum
from opensees_studio.core.tbdy_site import (
    EarthquakeLevel,
    SiteClass,
    tbdy2018_design_accelerations,
)
from opensees_studio.core.units import UnitSystem

#: TBDY 2018 long-period transition, seconds.
TBDY_TL = 6.0

TargetSpectrumKind = Literal["tbdy2018", "tbdy2018_vertical", "asce7_16", "user"]

#: Kinds built from SDS and SD1.
TBDY_KINDS: frozenset[str] = frozenset({"tbdy2018", "tbdy2018_vertical"})

#: The ASCE/SEI 7-16 design spectrum.
ASCE_KINDS: frozenset[str] = frozenset({"asce7_16"})

#: Kinds defined by a code (a shape from SDS and SD1) rather than by a table.
CODE_KINDS: frozenset[str] = TBDY_KINDS | ASCE_KINDS


def tbdy2018_corner_periods(sds: float, sd1: float) -> tuple[float, float]:
    """``(TA, TB)`` of the TBDY 2018 horizontal spectrum, seconds."""
    if sds <= 0.0 or sd1 <= 0.0:
        raise ValueError(f"SDS and SD1 must be positive, got SDS={sds}, SD1={sd1}.")
    return 0.2 * sd1 / sds, sd1 / sds


def tbdy2018_sae(
    periods: np.ndarray | list[float] | float,
    sds: float,
    sd1: float,
    tl: float = TBDY_TL,
) -> np.ndarray:
    """Horizontal elastic design spectral acceleration Sae(T), in g.

    The four branches are the ones in :func:`core.response_spectrum.four_branch_spectrum`
    (ASCE/SEI 7-16 describes the same shape); TBDY 2018 fixes TL = 6 s.
    """
    return four_branch_spectrum(periods, sds, sd1, tl)


def tbdy2018_vertical_corner_periods(
    sds: float, sd1: float, tl: float = TBDY_TL
) -> tuple[float, float, float]:
    """``(TAD, TBD, TLD)`` of the TBDY 2018 vertical spectrum, seconds (Md. 2.3.5)."""
    ta, tb = tbdy2018_corner_periods(sds, sd1)
    return ta / 3.0, tb / 3.0, tl / 2.0


def tbdy2018_saed(
    periods: np.ndarray | list[float] | float,
    sds: float,
    sd1: float,
    tl: float = TBDY_TL,
) -> np.ndarray:
    """Vertical elastic design spectral acceleration SaeD(T), in g.

    TBDY 2018 defines the vertical spectrum only for ``T <= TLD`` (TLD =
    TL / 2, Md. 2.3.5). Ordinates beyond TLD are returned as ``NaN`` so a
    caller cannot silently use the ``0.8 SDS TBD / T`` branch outside its
    domain: plots stop at TLD and scaling refuses ranges beyond it.
    """
    tad, tbd, tld = tbdy2018_vertical_corner_periods(sds, sd1, tl)
    t = np.atleast_1d(np.asarray(periods, dtype=float))
    if np.any(t < 0.0):
        raise ValueError("periods must be >= 0.")
    plateau = 0.8 * sds
    with np.errstate(divide="ignore"):
        saed = np.where(
            t <= tad,
            (0.32 + 0.48 * t / tad) * sds,
            np.where(t <= tbd, plateau, plateau * tbd / np.maximum(t, 1e-300)),
        )
    return np.where(t <= tld, saed, np.nan)


#: How many points a code spectrum is sampled at when it becomes a case
#: spectrum. The case reads Sa(T) by linear interpolation, so the corners have to
#: be in the table and the branches need enough points to keep the error small:
#: 200 points over the 0 s to TL range keep the linear interpolation within
#: 0.06 % of the exact curve everywhere (measured, the worst case being the 1/T
#: branch of a large-SD1 spectrum).
CASE_SPECTRUM_POINTS = 200


def _case_periods(sds: float, sd1: float, tl: float) -> list[float]:
    """The period grid a code spectrum is tabulated at: corners plus a ramp.

    A log-ish ramp, because the interesting part of a design spectrum is the
    short-period end: the corner periods themselves are inserted exactly, so the
    plateau and both decay branches are reproduced where they change.

    The grid starts just above zero rather than at it: a
    ``ResponseSpectrum`` requires strictly positive periods and no mode has
    T = 0. The case clamps at both ends of the table, so the first entry covers
    the rigid end.
    """
    low, high = 1e-3, tl
    ramp = [
        low * (high / low) ** (index / (CASE_SPECTRUM_POINTS - 1))
        for index in range(CASE_SPECTRUM_POINTS)
    ]
    corners = [0.2 * sd1 / sds, sd1 / sds, tl]
    return sorted({round(value, 9) for value in [*ramp, *corners] if low <= value <= tl})


def target_to_case_spectrum(
    target: TargetSpectrum,
    spectrum_id: int,
    *,
    units: UnitSystem,
    name: str = "",
    damping_ratio: float | None = None,
) -> ResponseSpectrum:
    """The target spectrum as a tabulated :class:`ResponseSpectrum` for a case.

    A :class:`TargetSpectrum` is a *design* spectrum in units of g (the dialog
    plots it and the scaling reads it); a :class:`ResponseSpectrumCase` reads a
    :class:`ResponseSpectrum`, which is tabulated in the project's acceleration
    unit. This is the conversion between the two, and it is explicit about both
    halves of that: the same curve, sampled at its own corner periods, with g
    turned into the project's unit by the standard gravity of that system.

    A user-table target is copied point for point — resampling a table the user
    typed would change the numbers they meant.
    """
    from opensees_studio.core.loads import ResponseSpectrum
    from opensees_studio.core.units import gravity

    factor = gravity(units)
    if target.kind == "user":
        periods = [float(value) for value in target.periods]
        values = [float(value) * factor for value in target.sa]
    else:
        assert target.sds is not None and target.sd1 is not None
        periods = _case_periods(target.sds, target.sd1, target.long_period_transition)
        sa = target.sa_at(periods)
        values = [float(value) * factor for value in np.atleast_1d(sa)]
    return ResponseSpectrum(
        id=spectrum_id,
        name=name or target.name or target.describe()[:60],
        periods=periods,
        accelerations=values,
        damping_ratio=target.damping_ratio if damping_ratio is None else damping_ratio,
    )


def loglog_interp(
    periods: np.ndarray | list[float] | float,
    table_periods: np.ndarray | list[float],
    table_sa: np.ndarray | list[float],
) -> np.ndarray:
    """Log-log interpolation of a (T, Sa) table, clamped at both ends.

    Periods must be strictly increasing and positive, Sa positive (a
    zero would have no logarithm). Below the first or above the last
    table period the end value is returned, never an extrapolation.
    """
    tp = np.asarray(table_periods, dtype=float)
    sa = np.asarray(table_sa, dtype=float)
    if tp.ndim != 1 or tp.size < 2 or sa.shape != tp.shape:
        raise ValueError("table needs at least 2 (period, Sa) pairs of equal length.")
    if np.any(tp <= 0.0) or np.any(np.diff(tp) <= 0.0):
        raise ValueError("table periods must be positive and strictly increasing.")
    if np.any(sa <= 0.0):
        raise ValueError("table Sa values must be positive for log-log interpolation.")
    t = np.atleast_1d(np.asarray(periods, dtype=float))
    if np.any(t < 0.0):
        raise ValueError("periods must be >= 0.")
    tc = np.clip(t, tp[0], tp[-1])
    return np.exp(np.interp(np.log(tc), np.log(tp), np.log(sa)))


class TargetSpectrum(Entity):
    """A target (design) spectrum in units of g.

    ``kind="tbdy2018"``: defined by ``sds`` and ``sd1``, given directly or
    derived from ``ss``, ``s1`` and ``site_class`` (then ``fs``, ``f1``,
    ``sds`` and ``sd1`` are filled in and stored next to the inputs;
    ``earthquake_level`` is a label only).
    ``kind="tbdy2018_vertical"``: the vertical spectrum SaeD from the same
    SDS and SD1 (given or site-derived).
    ``kind="user"``: defined by the ``periods`` / ``sa`` table.
    ``damping_ratio`` is informational (the damping the spectrum was
    built for; TBDY 2018 spectra are 5 %).
    """

    kind: TargetSpectrumKind = "tbdy2018"
    sds: PositiveFloat | None = Field(default=None, description="TBDY 2018 SDS, in g.")
    sd1: PositiveFloat | None = Field(default=None, description="TBDY 2018 SD1, in g.")
    ss: PositiveFloat | None = Field(
        default=None, description="Mapped short-period spectral acceleration Ss, in g."
    )
    s1: PositiveFloat | None = Field(
        default=None, description="Mapped 1 s spectral acceleration S1, in g."
    )
    site_class: SiteClass | None = Field(
        default=None, description="TBDY 2018 site class used to derive SDS and SD1."
    )
    earthquake_level: EarthquakeLevel | None = Field(
        default=None, description="TBDY 2018 earthquake level the mapped values belong to (label)."
    )
    fs: float | None = Field(default=None, description="Derived site coefficient Fs (Tablo 2.1).")
    f1: float | None = Field(default=None, description="Derived site coefficient F1 (Tablo 2.2).")
    asce_site_class: Literal["A", "B", "C", "D", "E", "F"] | None = Field(
        default=None, description="ASCE 7-16 site class used to derive SDS and SD1."
    )
    asce_site_class_is_default: bool = Field(
        default=False,
        description="ASCE 7-16: D assumed because the soil is unknown (§11.4.3), "
        "which forbids Fa below 1.2.",
    )
    fa: float | None = Field(default=None, description="Derived ASCE 7-16 Fa (Table 11.4-1).")
    fv: float | None = Field(default=None, description="Derived ASCE 7-16 Fv (Table 11.4-2).")
    tl: PositiveFloat | None = Field(
        default=None,
        description="ASCE 7-16 long-period transition period TL (Figs. 22-14 to 22-19).",
    )
    periods: list[float] = Field(
        default_factory=list,
        description="User table periods (s), strictly increasing and positive.",
    )
    sa: list[float] = Field(
        default_factory=list,
        description="User table spectral accelerations in g, positive.",
    )
    damping_ratio: float = Field(default=0.05, ge=0.0, lt=1.0)

    @model_validator(mode="before")
    @classmethod
    def _derive_from_site(cls, data: Any) -> Any:
        """Fill the derived values from the mapped Ss, S1 and the site class.

        TBDY 2018 derives Fs and F1 (and SDS, SD1); ASCE 7-16 derives Fa and Fv
        from its own site classes. The two are separate paths because the site
        classes are not the same thing.
        """
        if not isinstance(data, dict):
            return data
        if data.get("asce_site_class") is not None:
            return cls._derive_from_asce_site(data)
        site = [data.get(k) for k in ("ss", "s1", "site_class")]
        if all(v is None for v in site):
            return data
        if any(v is None for v in site):
            raise ValueError("A site-derived target spectrum needs ss, s1 and site_class together.")
        ss, s1, site_class = site
        derived = tbdy2018_design_accelerations(float(ss), float(s1), str(site_class))
        for key, value in (("sds", derived.sds), ("sd1", derived.sd1)):
            given = data.get(key)
            if given is not None and abs(float(given) - value) > 1e-9 * max(1.0, value):
                raise ValueError(
                    f"{key}={given} does not match the value {value:.6g} derived from "
                    f"ss, s1 and site class {site_class}."
                )
        return {**data, "fs": derived.fs, "f1": derived.f1, "sds": derived.sds, "sd1": derived.sd1}

    @classmethod
    def _derive_from_asce_site(cls, data: dict[str, Any]) -> dict[str, Any]:
        """ASCE 7-16: Fa, Fv, SMS, SM1, SDS and SD1 from Ss, S1 and the site class."""
        site_class = str(data["asce_site_class"])
        if site_class not in ASCE_SITE_CLASSES:
            raise ValueError(
                f"Unknown ASCE 7-16 site class {site_class!r}; "
                f"use one of {', '.join(ASCE_SITE_CLASSES)}."
            )
        missing = [key for key in ("ss", "s1") if data.get(key) is None]
        if missing:
            raise ValueError(
                "An ASCE 7-16 spectrum from the site needs ss and s1 together with asce_site_class."
            )
        derived = asce7_design_values(
            float(data["ss"]),
            float(data["s1"]),
            site_class,
            site_class_d_is_default=bool(data.get("asce_site_class_is_default", False)),
        )
        for key, value in (("sds", derived.sds), ("sd1", derived.sd1)):
            given = data.get(key)
            if given is not None and abs(float(given) - value) > 1e-9 * max(1.0, value):
                raise ValueError(
                    f"{key}={given} does not match the value {value:.6g} derived from "
                    f"Ss, S1 and ASCE 7-16 site class {site_class}."
                )
        return {
            **data,
            "fa": derived.fa,
            "fv": derived.fv,
            "sds": derived.sds,
            "sd1": derived.sd1,
        }

    @model_validator(mode="after")
    def _check_definition(self) -> TargetSpectrum:
        if self.kind in TBDY_KINDS:
            if self.sds is None or self.sd1 is None:
                raise ValueError(f"A {self.kind} target spectrum needs both sds and sd1.")
            tbdy2018_corner_periods(self.sds, self.sd1)
        elif self.kind in ASCE_KINDS:
            if self.sds is None or self.sd1 is None:
                raise ValueError(
                    "An ASCE 7-16 target spectrum needs SDS and SD1, either given "
                    "directly or from Ss, S1 and the site class."
                )
            asce7_corner_periods(self.sds, self.sd1, self.tl or TL_DEFAULT)
        else:
            loglog_interp([1.0], self.periods, self.sa)
        return self

    @property
    def from_site(self) -> bool:
        """True when SDS and SD1 were derived from Ss, S1 and the site class."""
        return self.site_class is not None or self.asce_site_class is not None

    @property
    def long_period_transition(self) -> float:
        """TL in seconds: the map value for ASCE 7-16, the code's 6 s for TBDY."""
        if self.kind in ASCE_KINDS:
            return float(self.tl or TL_DEFAULT)
        return TBDY_TL

    def sa_at(self, periods: np.ndarray | list[float] | float) -> np.ndarray:
        """Target Sa (g) at ``periods``."""
        if self.kind in TBDY_KINDS:
            assert self.sds is not None and self.sd1 is not None
            if self.kind == "tbdy2018_vertical":
                return tbdy2018_saed(periods, self.sds, self.sd1)
            return tbdy2018_sae(periods, self.sds, self.sd1)
        if self.kind in ASCE_KINDS:
            assert self.sds is not None and self.sd1 is not None
            return asce7_design_spectrum(periods, self.sds, self.sd1, self.long_period_transition)
        return loglog_interp(periods, self.periods, self.sa)

    @property
    def max_period(self) -> float | None:
        """Largest period the target is defined for: TLD for the vertical spectrum.

        ``None`` means unlimited (horizontal TBDY spectrum, user tables).
        """
        if self.kind == "tbdy2018_vertical":
            return self.corner_periods()[2]
        return None

    def corner_periods(self) -> tuple[float, ...]:
        """``(TA, TB, TL)``, ``(TAD, TBD, TLD)`` or ``(T0, Ts, TL)``; empty for a user table."""
        assert not (self.kind in ASCE_KINDS and (self.sds is None or self.sd1 is None))
        if self.kind in ASCE_KINDS:
            assert self.sds is not None and self.sd1 is not None
            return asce7_corner_periods(self.sds, self.sd1, self.long_period_transition)
        if self.kind not in TBDY_KINDS:
            return ()
        assert self.sds is not None and self.sd1 is not None
        if self.kind == "tbdy2018_vertical":
            return tbdy2018_vertical_corner_periods(self.sds, self.sd1)
        return (*tbdy2018_corner_periods(self.sds, self.sd1), TBDY_TL)

    def describe(self) -> str:
        if self.kind in TBDY_KINDS:
            ta, tb = tbdy2018_corner_periods(self.sds or 1.0, self.sd1 or 1.0)
            if self.kind == "tbdy2018_vertical":
                text = (
                    f"TBDY 2018 vertical: SDS={self.sds:g} g, SD1={self.sd1:g} g "
                    f"(TAD={ta / 3.0:.3f} s, TBD={tb / 3.0:.3f} s)"
                )
            else:
                text = (
                    f"TBDY 2018: SDS={self.sds:g} g, SD1={self.sd1:g} g "
                    f"(TA={ta:.3f} s, TB={tb:.3f} s)"
                )
            if self.from_site:
                level = f"{self.earthquake_level}, " if self.earthquake_level else ""
                text += (
                    f" from {level}Ss={self.ss:g} g, S1={self.s1:g} g, {self.site_class}"
                    f" (Fs={self.fs:g}, F1={self.f1:g})"
                )
            return text
        if self.kind in ASCE_KINDS:
            t0, ts, tl = self.corner_periods()
            text = (
                f"ASCE 7-16: SDS={self.sds:g} g, SD1={self.sd1:g} g "
                f"(T0={t0:.3f} s, Ts={ts:.3f} s, TL={tl:g} s)"
            )
            if self.from_site:
                default = " assumed" if self.asce_site_class_is_default else ""
                text += (
                    f" from Ss={self.ss:g} g, S1={self.s1:g} g, site class "
                    f"{self.asce_site_class}{default} (Fa={self.fa:g}, Fv={self.fv:g})"
                )
            return text
        return (
            f"User table: {len(self.periods)} points, {self.periods[0]:g} to {self.periods[-1]:g} s"
        )
