"""ASCE/SEI 7-16 site coefficients (Tables 11.4-1, 11.4-2) and design spectrum.

The tables are pinned value by value as they appear in the standard (Chapter 11,
page 83 of the copy in the reference library), including the cells the standard
leaves to a site-specific study. The worked case is Ss = 1.0, S1 = 0.4, Site
Class C, TL = 8 s: Fa = 1.2, Fv = 1.5, SDS = 0.8 g, SD1 = 0.4 g, T0 = 0.1 s,
Ts = 0.5 s.
"""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core.asce7 import (
    ASCE_SITE_CLASSES,
    DEFAULT_SITE_CLASS_D_FA_FLOOR,
    FA_SS_VALUES,
    FA_TABLE,
    FV_S1_VALUES,
    FV_TABLE,
    TL_DEFAULT,
    ASCESpectrumError,
    asce7_corner_periods,
    asce7_design_spectrum,
    asce7_design_values,
    fa_coefficient,
    fv_coefficient,
)
from opensees_studio.core.target_spectrum import tbdy2018_sae

SS, S1 = 1.0, 0.4


# ──────────────────────────── the tables ────────────────────────────
def test_table_11_4_1_is_the_one_in_the_standard() -> None:
    """Short-Period Site Coefficient Fa, transcribed."""
    assert FA_SS_VALUES == (0.25, 0.5, 0.75, 1.0, 1.25, 1.5)
    assert FA_TABLE == {
        "A": (0.8, 0.8, 0.8, 0.8, 0.8, 0.8),
        "B": (0.9, 0.9, 0.9, 0.9, 0.9, 0.9),
        "C": (1.3, 1.3, 1.2, 1.2, 1.2, 1.2),
        "D": (1.6, 1.4, 1.2, 1.1, 1.0, 1.0),
        "E": (2.4, 1.7, 1.3, None, None, None),
        "F": (None, None, None, None, None, None),
    }


def test_table_11_4_2_is_the_one_in_the_standard() -> None:
    """Long-Period Site Coefficient Fv, transcribed."""
    assert FV_S1_VALUES == (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
    assert FV_TABLE == {
        "A": (0.8, 0.8, 0.8, 0.8, 0.8, 0.8),
        "B": (0.8, 0.8, 0.8, 0.8, 0.8, 0.8),
        "C": (1.5, 1.5, 1.5, 1.5, 1.5, 1.4),
        "D": (2.4, 2.2, 2.0, 1.9, 1.8, 1.7),
        "E": (4.2, None, None, None, None, None),
        "F": (None, None, None, None, None, None),
    }


def test_the_tables_only_cover_the_six_site_classes() -> None:
    assert ASCE_SITE_CLASSES == ("A", "B", "C", "D", "E", "F")
    assert set(FA_TABLE) == set(FV_TABLE) == set(ASCE_SITE_CLASSES)


@pytest.mark.parametrize("site_class", ["A", "B", "C", "D"])
def test_a_tabulated_value_is_returned_exactly(site_class: str) -> None:
    for index, ss in enumerate(FA_SS_VALUES):
        assert fa_coefficient(site_class, ss) == FA_TABLE[site_class][index]
    for index, s1 in enumerate(FV_S1_VALUES):
        assert fv_coefficient(site_class, s1) == FV_TABLE[site_class][index]


def test_the_table_is_clamped_at_both_ends() -> None:
    """``Ss <= 0.25`` and ``Ss >= 1.5`` are the table's own outward values."""
    assert fa_coefficient("D", 0.05) == 1.6
    assert fa_coefficient("D", 3.0) == 1.0
    assert fv_coefficient("D", 0.02) == 2.4
    assert fv_coefficient("D", 2.0) == 1.7


def test_intermediate_values_are_interpolated_in_a_straight_line() -> None:
    """The notes of both tables require straight-line interpolation."""
    assert fa_coefficient("D", 0.375) == pytest.approx((1.6 + 1.4) / 2)  # halfway 0.25-0.5
    assert fa_coefficient("D", 0.625) == pytest.approx((1.4 + 1.2) / 2)
    assert fv_coefficient("D", 0.15) == pytest.approx((2.4 + 2.2) / 2)  # halfway 0.1-0.2
    assert fv_coefficient("D", 0.25) == pytest.approx((2.2 + 2.0) / 2)  # and 0.2-0.3
    # ... and it really is linear, not stepped.
    assert fa_coefficient("C", 0.6) == pytest.approx(1.3 + (1.2 - 1.3) * (0.6 - 0.5) / 0.25)


# ──────────────────────────── what is refused ────────────────────────────
def test_site_class_f_is_site_specific() -> None:
    for symbol, call in (("Fa", fa_coefficient), ("Fv", fv_coefficient)):
        with pytest.raises(ASCESpectrumError, match="site-specific study"):
            call("F", 0.5)
        del symbol


def test_site_class_e_is_site_specific_beyond_the_table() -> None:
    assert fa_coefficient("E", 0.75) == 1.3
    with pytest.raises(ASCESpectrumError, match=r"11\.4\.8"):
        fa_coefficient("E", 1.0)  # the standard's cell says "See Section 11.4.8"
    with pytest.raises(ASCESpectrumError, match=r"11\.4\.8"):
        fa_coefficient("E", 0.9)  # interpolation towards a blank cell is not defined either

    assert fv_coefficient("E", 0.1) == 4.2
    with pytest.raises(ASCESpectrumError, match=r"11\.4\.8"):
        fv_coefficient("E", 0.2)


def test_a_bad_site_class_or_value_is_refused() -> None:
    with pytest.raises(ASCESpectrumError, match="Unknown site class"):
        fa_coefficient("Z", 0.5)
    with pytest.raises(ASCESpectrumError, match="must be positive"):
        fa_coefficient("D", 0.0)


# ──────────────────────────── the design values ────────────────────────────
def test_design_values_follow_equations_11_4_1_to_11_4_4() -> None:
    values = asce7_design_values(SS, S1, "C")

    assert (values.fa, values.fv) == (1.2, 1.5)
    assert values.sms == pytest.approx(1.2)  # Fa * Ss
    assert values.sm1 == pytest.approx(0.6)  # Fv * S1
    assert values.sds == pytest.approx(0.8)  # 2/3 SMS
    assert values.sd1 == pytest.approx(0.4)  # 2/3 SM1
    assert "SDS=0.8 g" in values.summary()


def test_a_default_site_class_d_may_not_use_fa_below_1_2() -> None:
    """§11.4.3: D assumed because the soil is unknown, not D determined."""
    assumed = asce7_design_values(1.5, 0.5, "D", site_class_d_is_default=True)
    determined = asce7_design_values(1.5, 0.5, "D")

    assert fa_coefficient("D", 1.5) == 1.0  # the table's own value at Ss = 1.5
    assert assumed.fa == DEFAULT_SITE_CLASS_D_FA_FLOOR
    assert determined.fa == 1.0
    assert assumed.sds > determined.sds


def test_the_floor_only_applies_to_site_class_d() -> None:
    assert asce7_design_values(1.5, 0.5, "C", site_class_d_is_default=True).fa == 1.2
    assert asce7_design_values(1.5, 0.5, "B", site_class_d_is_default=True).fa == 0.9


# ──────────────────────────── the spectrum ────────────────────────────
def test_corner_periods_come_from_sds_and_sd1() -> None:
    t0, ts, tl = asce7_corner_periods(0.8, 0.4)

    assert (t0, ts, tl) == (pytest.approx(0.1), pytest.approx(0.5), TL_DEFAULT)


def test_the_four_branches_are_equations_11_4_5_to_11_4_7() -> None:
    sds, sd1, tl = 0.8, 0.4, 8.0

    # Eq. (11.4-5), and at T = 0 it gives 0.4 SDS.
    assert asce7_design_spectrum(0.0, sds, sd1, tl)[0] == pytest.approx(0.4 * sds)
    assert asce7_design_spectrum(0.05, sds, sd1, tl)[0] == pytest.approx(0.8 * 0.7)
    # The plateau.
    assert asce7_design_spectrum(np.array([0.1, 0.3, 0.5]), sds, sd1, tl) == pytest.approx(
        [sds, sds, sds]
    )
    # Eq. (11.4-6) and Eq. (11.4-7).
    assert asce7_design_spectrum(1.0, sds, sd1, tl)[0] == pytest.approx(sd1 / 1.0)
    assert asce7_design_spectrum(8.0, sds, sd1, tl)[0] == pytest.approx(sd1 / 8.0)
    assert asce7_design_spectrum(16.0, sds, sd1, tl)[0] == pytest.approx(sd1 * tl / 16.0**2)


def test_the_spectrum_is_continuous_at_every_corner() -> None:
    sds, sd1, tl = 1.2, 0.35, 6.0
    t0, ts, _ = asce7_corner_periods(sds, sd1, tl)

    for corner in (t0, ts, tl):
        before = asce7_design_spectrum(corner - 1e-9, sds, sd1, tl)[0]
        after = asce7_design_spectrum(corner + 1e-9, sds, sd1, tl)[0]
        assert before == pytest.approx(after, rel=1e-6)


def test_the_decay_branches_never_grow_with_period() -> None:
    periods = np.linspace(0.01, 10.0, 200)
    sa = asce7_design_spectrum(periods, 0.8, 0.4, 8.0)

    rising = sa[: np.searchsorted(periods, 0.1) + 1]
    assert np.all(np.diff(rising) > 0)  # the first branch climbs
    assert np.all(np.diff(sa[np.searchsorted(periods, 0.5) :]) <= 1e-12)  # then it does not


def test_the_shape_is_the_one_tbdy_uses_with_its_own_tl() -> None:
    """Both codes describe the same four branches; only TL and the source differ."""
    periods = np.linspace(0.01, 6.0, 50)
    assert asce7_design_spectrum(periods, 0.8, 0.4, 6.0) == pytest.approx(
        tbdy2018_sae(periods, 0.8, 0.4)
    )


def test_an_impossible_tl_is_refused() -> None:
    with pytest.raises(ASCESpectrumError, match="must exceed Ts"):
        asce7_design_spectrum(1.0, 0.8, 0.4, 0.4)
    with pytest.raises(ASCESpectrumError, match="must be positive"):
        asce7_corner_periods(0.0, 0.4)


def test_the_worked_case_from_the_reference_values() -> None:
    """Ss = 1.0, S1 = 0.4, Site Class C, TL = 8 s, end to end."""
    values = asce7_design_values(SS, S1, "C")
    sa = asce7_design_spectrum(np.array([0.0, 0.05, 0.3, 1.0, 16.0]), values.sds, values.sd1)

    assert sa == pytest.approx([0.32, 0.56, 0.8, 0.4, 0.0125])
