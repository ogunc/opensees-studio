"""Record scaling tests: units, PGA, Sa(T1), period range (uniform, individual, pairs)."""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import (
    TBDY_MIN_RECORDS,
    TBDY_RANGE_PRESET,
    TargetSpectrum,
    UnitSystem,
    accel_in_g,
    gravity,
    period_range_scale_factors,
    pga_scale_factor,
    record_count_warning,
    response_spectrum,
    sa_t1_scale_factor,
    series_factor,
)

FLAT = TargetSpectrum(id=1, kind="user", periods=[0.01, 20.0], sa=[1.0, 1.0])  # 1.0 g everywhere
DT = 0.01


def _record(seed: int, peak: float = 0.3, seconds: float = 20.0) -> np.ndarray:
    t = np.arange(0.0, seconds, DT)
    rng = np.random.default_rng(seed)
    a = np.zeros_like(t)
    for f in np.linspace(0.4, 6.0, 20):
        a += rng.uniform(0.2, 1.0) * np.sin(2.0 * np.pi * f * t + rng.uniform(0, 2 * np.pi))
    a *= np.exp(-((t - 8.0) ** 2) / 20.0)
    return a * (peak / np.max(np.abs(a)))


# ---- units ---------------------------------------------------------------
def test_gravity_per_unit_system() -> None:
    assert gravity(UnitSystem.SI_M_N) == pytest.approx(9.80665)
    assert gravity(UnitSystem.SI_MM_N) == pytest.approx(9806.65)
    assert gravity(UnitSystem.US_IN_KIP) == pytest.approx(386.0886)
    assert gravity(UnitSystem.US_FT_KIP) == pytest.approx(32.17405)


def test_accel_in_g_converts_and_refuses_unknown() -> None:
    a = np.array([0.0, 9.80665, -19.6133])
    assert accel_in_g(a, "g", UnitSystem.SI_M_N) == pytest.approx(a)
    assert accel_in_g(a, "project", UnitSystem.SI_M_N) == pytest.approx([0.0, 1.0, -2.0])
    with pytest.raises(ValueError, match="Record 'ElCentro' has unknown acceleration units"):
        accel_in_g(a, "unknown", UnitSystem.SI_M_N, record_name="ElCentro")


def test_series_factor_carries_unit_conversion() -> None:
    assert series_factor(2.0, "g", UnitSystem.US_IN_KIP) == pytest.approx(2.0 * 386.0886)
    assert series_factor(2.0, "project", UnitSystem.US_IN_KIP) == 2.0
    with pytest.raises(ValueError, match="unknown acceleration units"):
        series_factor(2.0, "unknown", UnitSystem.SI_M_N)


# ---- (a) PGA ---------------------------------------------------------------
def test_pga_scale_factor() -> None:
    a = _record(1, peak=0.2)
    k = pga_scale_factor(a, 0.4)
    assert k == pytest.approx(2.0)
    assert float(np.max(np.abs(k * a))) == pytest.approx(0.4)
    with pytest.raises(ValueError, match="positive"):
        pga_scale_factor(a, 0.0)
    with pytest.raises(ValueError, match="all zeros"):
        pga_scale_factor(np.zeros(10), 0.4)


# ---- (b) Sa(T1) ------------------------------------------------------------
def test_sa_t1_scale_factor_matches_target_at_t1() -> None:
    a = _record(2)
    t1 = 0.8
    target = TargetSpectrum(id=2, kind="tbdy2018", sds=1.0, sd1=0.4)
    k = sa_t1_scale_factor(DT, a, target, t1)
    sa_scaled = response_spectrum(DT, k * a, periods=[t1]).sa[0]
    assert sa_scaled == pytest.approx(target.sa_at(t1)[0], rel=1e-9)
    with pytest.raises(ValueError, match="T1 must be positive"):
        sa_t1_scale_factor(DT, a, target, 0.0)


# ---- (c) period range ------------------------------------------------------
def _check_criterion(result, records, alpha: float, damping: float = 0.05) -> None:  # type: ignore[no-untyped-def]
    """Recompute the scaled mean from the factors: never below alpha * target,
    equal to it at the governing period."""
    spectra = [
        response_spectrum(dt, result.factors[rid] * acc, damping, periods=result.periods).sa
        for rid, (dt, acc) in records.items()
    ]
    mean = np.mean(spectra, axis=0)
    ratio = mean / result.target_sa
    assert np.all(ratio >= alpha * (1.0 - 1e-9))
    assert float(np.min(ratio)) == pytest.approx(alpha, rel=1e-9)
    assert result.min_ratio == pytest.approx(alpha, rel=1e-9)
    assert result.periods[int(np.argmin(ratio))] == result.governing_period
    assert mean == pytest.approx(result.scaled_mean_sa, rel=1e-9)


def test_period_range_uniform_factor() -> None:
    records = {1: (DT, _record(3)), 2: (DT, _record(4)), 3: (DT, _record(5))}
    res = period_range_scale_factors(records, FLAT, t1=1.0, alpha=1.0)
    assert len(set(res.factors.values())) == 1  # one uniform factor
    assert res.periods[0] == pytest.approx(0.2) and res.periods[-1] == pytest.approx(1.5)
    assert res.alpha == 1.0
    _check_criterion(res, records, alpha=1.0)


def test_period_range_individual_factors() -> None:
    records = {1: (DT, _record(3)), 2: (DT, _record(4, peak=0.6)), 3: (DT, _record(5, peak=0.1))}
    res = period_range_scale_factors(records, FLAT, t1=1.0, alpha=1.0, individual=True)
    assert len(set(res.factors.values())) == 3  # a factor per record
    _check_criterion(res, records, alpha=1.0)
    # the weak record gets the largest factor, the strong one the smallest
    assert res.factors[3] > res.factors[1] > res.factors[2]


def test_period_range_pairs_srss_with_tbdy_preset() -> None:
    records = {1: (DT, _record(6)), 2: (DT, _record(7)), 3: (DT, _record(8)), 4: (DT, _record(9))}
    pairs = [(1, 2), (3, 4)]
    preset = TBDY_RANGE_PRESET
    assert (preset.a, preset.b, preset.alpha) == (0.2, 1.5, 1.3)
    res = period_range_scale_factors(records, FLAT, t1=0.6, pairs=pairs)
    assert res.factors[1] == res.factors[2] and res.factors[3] == res.factors[4]
    srss = []
    for h1, h2 in pairs:
        s1 = response_spectrum(DT, res.factors[h1] * records[h1][1], periods=res.periods).sa
        s2 = response_spectrum(DT, res.factors[h2] * records[h2][1], periods=res.periods).sa
        srss.append(np.sqrt(s1**2 + s2**2))
    ratio = np.mean(srss, axis=0) / res.target_sa
    assert np.all(ratio >= 1.3 * (1.0 - 1e-9))
    assert float(np.min(ratio)) == pytest.approx(1.3, rel=1e-9)
    assert res.min_ratio == pytest.approx(1.3, rel=1e-9)
    assert res.periods[0] == pytest.approx(0.12) and res.periods[-1] == pytest.approx(0.9)


def test_period_range_rejects_bad_pairs_and_inputs() -> None:
    records = {1: (DT, _record(6)), 2: (DT, _record(7)), 3: (DT, _record(8))}
    with pytest.raises(ValueError, match="not part of any pair"):
        period_range_scale_factors(records, FLAT, t1=1.0, pairs=[(1, 2)])
    with pytest.raises(ValueError, match="distinct"):
        period_range_scale_factors(records, FLAT, t1=1.0, pairs=[(1, 1), (2, 3)])
    with pytest.raises(ValueError, match="not in the set"):
        period_range_scale_factors(records, FLAT, t1=1.0, pairs=[(1, 9), (2, 3)])
    with pytest.raises(ValueError, match="No records"):
        period_range_scale_factors({}, FLAT, t1=1.0)
    with pytest.raises(ValueError, match="T1 > 0"):
        period_range_scale_factors(records, FLAT, t1=1.0, a=0.5, b=0.2)


def test_scaling_is_linear_in_the_record() -> None:
    """Sanity of the whole chain: scaling the record by k scales Sa by k."""
    a = _record(10)
    rs1 = response_spectrum(DT, a, periods=[0.3, 1.0])
    rs2 = response_spectrum(DT, 2.5 * a, periods=[0.3, 1.0])
    assert rs2.sa == pytest.approx(2.5 * rs1.sa, rel=1e-12)


# ---- record-count warning ---------------------------------------------------
def test_record_count_warning_threshold() -> None:
    assert TBDY_MIN_RECORDS == 11
    assert record_count_warning(11, paired=False) is None
    assert record_count_warning(30, paired=True) is None
    single = record_count_warning(1, paired=False)
    assert single is not None and "Only 1 record in the set" in single and "11 records" in single
    three = record_count_warning(3, paired=False)
    assert three is not None and "Only 3 records" in three
    pairs = record_count_warning(10, paired=True)
    assert pairs is not None and "Only 10 pairs" in pairs and "11 pairs" in pairs


def test_period_range_warns_below_eleven_records_but_still_scales() -> None:
    few = {i: (DT, _record(20 + i, seconds=6.0)) for i in range(1, 4)}
    res = period_range_scale_factors(few, FLAT, t1=1.0, alpha=1.0)
    assert len(res.factors) == 3 and res.min_ratio == pytest.approx(1.0, rel=1e-9)
    assert len(res.warnings) == 1 and "Only 3 records" in res.warnings[0]

    enough = {i: (DT, _record(40 + i, seconds=6.0)) for i in range(1, 12)}
    assert period_range_scale_factors(enough, FLAT, t1=1.0, alpha=1.0).warnings == ()

    # pairs count as members: 4 records paired are 2 pairs
    four = {i: (DT, _record(60 + i, seconds=6.0)) for i in range(1, 5)}
    paired = period_range_scale_factors(four, FLAT, t1=1.0, pairs=[(1, 2), (3, 4)])
    assert "Only 2 pairs" in paired.warnings[0]
