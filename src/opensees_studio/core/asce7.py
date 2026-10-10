"""The ASCE/SEI 7-16 design response spectrum.

Reference: ASCE/SEI 7-16, *Minimum Design Loads and Associated Criteria for
Buildings and Other Structures*, Chapter 11 — the copy in the owner's reference
library. Everything here is transcribed from it:

* §11.4.4 and Eqs. (11.4-1) to (11.4-4): ``SMS = Fa Ss``, ``SM1 = Fv S1``,
  ``SDS = 2/3 SMS``, ``SD1 = 2/3 SM1``;
* Tables 11.4-1 and 11.4-2 (page 83): the site coefficients ``Fa`` and ``Fv``,
  with the straight-line interpolation the tables' notes require;
* §11.4.6, Eqs. (11.4-5) to (11.4-7) and Fig. 11.4-1: the four branches, with
  ``T0 = 0.2 SD1/SDS``, ``Ts = SD1/SDS`` and ``TL`` the mapped long-period
  transition period (Figs. 22-14 to 22-19).

Two rules of the standard are enforced rather than assumed, because getting
either wrong produces a spectrum that looks plausible and is not the code's:

* **Site Class F is site-specific** (§11.4.8), and so is Site Class E beyond
  ``Ss = 0.75`` (Table 11.4-1) or ``S1 = 0.1`` (Table 11.4-2). The coefficient
  functions raise for those combinations instead of extrapolating a table that
  the standard leaves blank;
* **where Site Class D is taken as the default** because the soil is unknown,
  §11.4.3 does not permit ``Fa`` below 1.2. That is a choice about *why* D was
  chosen, so it is an explicit argument and never guessed from the values.

This module is part of ``core``: no Qt, no openseespy.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from opensees_studio.core.response_spectrum import four_branch_spectrum

#: Site classes of §11.4.3 / Table 20.3-1.
ASCE_SITE_CLASSES: tuple[str, ...] = ("A", "B", "C", "D", "E", "F")

#: Abscissas of Table 11.4-1 (mapped MCER, short period).
FA_SS_VALUES: tuple[float, ...] = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5)

#: Table 11.4-1, Short-Period Site Coefficient Fa. ``None`` is the standard's
#: "See Section 11.4.8": a site-specific study is required, not a number.
FA_TABLE: dict[str, tuple[float | None, ...]] = {
    "A": (0.8, 0.8, 0.8, 0.8, 0.8, 0.8),
    "B": (0.9, 0.9, 0.9, 0.9, 0.9, 0.9),
    "C": (1.3, 1.3, 1.2, 1.2, 1.2, 1.2),
    "D": (1.6, 1.4, 1.2, 1.1, 1.0, 1.0),
    "E": (2.4, 1.7, 1.3, None, None, None),
    "F": (None, None, None, None, None, None),
}

#: Abscissas of Table 11.4-2 (mapped MCER, 1 s period).
FV_S1_VALUES: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)

#: Table 11.4-2, Long-Period Site Coefficient Fv. Footnote a of the table also
#: points Site Class D at §11.4.8 for site-specific procedures.
FV_TABLE: dict[str, tuple[float | None, ...]] = {
    "A": (0.8, 0.8, 0.8, 0.8, 0.8, 0.8),
    "B": (0.8, 0.8, 0.8, 0.8, 0.8, 0.8),
    "C": (1.5, 1.5, 1.5, 1.5, 1.5, 1.4),
    "D": (2.4, 2.2, 2.0, 1.9, 1.8, 1.7),
    "E": (4.2, None, None, None, None, None),
    "F": (None, None, None, None, None, None),
}

#: §11.4.3: a default Site Class D is not permitted to use Fa below 1.2.
DEFAULT_SITE_CLASS_D_FA_FLOOR = 1.2

#: Long-period transition period, seconds. The standard takes TL from the maps
#: of Figs. 22-14 to 22-19 (4 s to 16 s across the United States); 8 s is the
#: value most of the conterminous US uses and the placeholder the dialog fills
#: in, to be replaced by the site's own map value.
TL_DEFAULT = 8.0


class ASCESpectrumError(ValueError):
    """The ASCE 7-16 parameters do not define a design spectrum."""


@dataclass(frozen=True)
class ASCEDesignValues:
    """The parameters of a design spectrum, and the values derived from them."""

    ss: float
    s1: float
    site_class: str
    fa: float
    fv: float
    sms: float
    sm1: float
    sds: float
    sd1: float
    site_specific: bool = False

    def summary(self) -> str:
        text = (
            f"ASCE 7-16 site class {self.site_class}: Ss={self.ss:g} g, S1={self.s1:g} g -> "
            f"Fa={self.fa:g}, Fv={self.fv:g} -> SDS={self.sds:.4g} g, SD1={self.sd1:.4g} g"
        )
        if self.site_specific:
            text += " (site-specific study required by §11.4.8)"
        return text


def _coefficient(
    table: dict[str, tuple[float | None, ...]],
    points: tuple[float, ...],
    site_class: str,
    value: float,
    *,
    symbol: str,
    mapped: str,
) -> float:
    """A table lookup with the straight-line interpolation its note requires."""
    if site_class not in ASCE_SITE_CLASSES:
        raise ASCESpectrumError(
            f"Unknown site class {site_class!r}; ASCE 7-16 uses {', '.join(ASCE_SITE_CLASSES)}."
        )
    if value <= 0.0:
        raise ASCESpectrumError(f"{mapped} must be positive, got {value}.")
    row = table[site_class]
    if value <= points[0]:
        first = row[0]
        if first is None:
            raise ASCESpectrumError(_site_specific_message(site_class, symbol, value, points[0]))
        return first
    if value >= points[-1]:
        last = row[-1]
        if last is None:
            raise ASCESpectrumError(_site_specific_message(site_class, symbol, value, points[-1]))
        return last
    for index in range(len(points) - 1):
        low, high = points[index], points[index + 1]
        if low <= value <= high:
            low_value, high_value = row[index], row[index + 1]
            if low_value is None or high_value is None:
                raise ASCESpectrumError(_site_specific_message(site_class, symbol, value, low))
            if high == low:
                return low_value
            weight = (value - low) / (high - low)
            return low_value + weight * (high_value - low_value)
    raise ASCESpectrumError(f"{mapped}={value} is outside Table {symbol}.")  # pragma: no cover


def _site_specific_message(site_class: str, symbol: str, value: float, from_value: float) -> str:
    return (
        f"ASCE 7-16 leaves {symbol} for site class {site_class} at {value:g} to a "
        f"site-specific study (§11.4.8) from {from_value:g} upwards. Use the site's own "
        "spectrum (a user table) instead of this table."
    )


def fa_coefficient(site_class: str, ss: float) -> float:
    """Short-period site coefficient Fa (Table 11.4-1), interpolated."""
    return _coefficient(FA_TABLE, FA_SS_VALUES, site_class, ss, symbol="Fa", mapped="Ss")


def fv_coefficient(site_class: str, s1: float) -> float:
    """Long-period site coefficient Fv (Table 11.4-2), interpolated."""
    return _coefficient(FV_TABLE, FV_S1_VALUES, site_class, s1, symbol="Fv", mapped="S1")


def asce7_design_values(
    ss: float,
    s1: float,
    site_class: str,
    *,
    site_class_d_is_default: bool = False,
) -> ASCEDesignValues:
    """The design parameters from the mapped MCER values and the site class.

    Args:
        ss: mapped MCER short-period spectral acceleration, in g.
        s1: mapped MCER 1 s spectral acceleration, in g.
        site_class: ``A`` to ``F`` (Table 20.3-1).
        site_class_d_is_default: True when D was *assumed* because the soil is
            unknown, which §11.4.3 forbids from using Fa below 1.2.

    Raises:
        ASCESpectrumError: for a combination the standard leaves to a
            site-specific study (class F, class E beyond the table).
    """
    fa = fa_coefficient(site_class, ss)
    if site_class == "D" and site_class_d_is_default and fa < DEFAULT_SITE_CLASS_D_FA_FLOOR:
        fa = DEFAULT_SITE_CLASS_D_FA_FLOOR
    fv = fv_coefficient(site_class, s1)
    sms, sm1 = fa * ss, fv * s1
    return ASCEDesignValues(
        ss=ss,
        s1=s1,
        site_class=site_class,
        fa=fa,
        fv=fv,
        sms=sms,
        sm1=sm1,
        sds=2.0 / 3.0 * sms,
        sd1=2.0 / 3.0 * sm1,
        site_specific=site_class == "F",
    )


def asce7_corner_periods(
    sds: float, sd1: float, tl: float = TL_DEFAULT
) -> tuple[float, float, float]:
    """``(T0, Ts, TL)`` of the design spectrum, seconds (Fig. 11.4-1)."""
    if sds <= 0.0 or sd1 <= 0.0:
        raise ASCESpectrumError(f"SDS and SD1 must be positive, got SDS={sds}, SD1={sd1}.")
    t0, ts = 0.2 * sd1 / sds, sd1 / sds
    if tl <= ts:
        raise ASCESpectrumError(f"TL={tl} must exceed Ts={ts:.4g} s.")
    return t0, ts, tl


def asce7_design_spectrum(
    periods: np.ndarray | list[float] | float,
    sds: float,
    sd1: float,
    tl: float = TL_DEFAULT,
) -> np.ndarray:
    """Design spectral acceleration Sa(T), in g (Eqs. 11.4-5 to 11.4-7)."""
    asce7_corner_periods(sds, sd1, tl)
    return four_branch_spectrum(periods, sds, sd1, tl)
