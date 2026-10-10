"""TBDY 2018 site coefficients (Tablo 2.1, 2.2) and site-derived target spectra.

The reference case and the interpolation, clamping and ZF tests are ported
from the owner's cfs-egitim-app ``tests/test_seismic.py`` (AFAD DD-2 report
for lat 36.547781, lon 31.995295, ZC: Ss 0.450, S1 0.117 gives Fs 1.3,
F1 1.5, SDS 0.585, SD1 0.1755, TA 0.060, TB 0.300, TL 6.0).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    EARTHQUAKE_LEVEL_LABELS,
    EARTHQUAKE_LEVELS,
    SITE_CLASSES,
    TBDY_F1_TABLE,
    TBDY_FS_TABLE,
    TBDY_S1_POINTS,
    TBDY_SS_POINTS,
    TBDY_TL,
    Project,
    TargetSpectrum,
    tbdy2018_corner_periods,
    tbdy2018_design_accelerations,
    tbdy2018_f1,
    tbdy2018_fs,
    tbdy2018_sae,
)

SS, S1 = 0.450, 0.117


@pytest.fixture
def dd2_zc():  # type: ignore[no-untyped-def]
    """AFAD DD-2 report reference: Ss 0.450, S1 0.117, ZC."""
    return tbdy2018_design_accelerations(SS, S1, "ZC")


# --- ported from the owner's tests/test_seismic.py -------------------------
def test_fs_zc_reference(dd2_zc) -> None:  # type: ignore[no-untyped-def]
    assert dd2_zc.fs == pytest.approx(1.3, abs=1e-12)


def test_f1_zc_reference(dd2_zc) -> None:  # type: ignore[no-untyped-def]
    assert dd2_zc.f1 == pytest.approx(1.5, abs=1e-12)


def test_fs_interpolation_zd() -> None:
    assert tbdy2018_fs(0.375, "ZD") == pytest.approx(1.5)  # midway between 1.6 and 1.4


def test_f1_interpolation_ze() -> None:
    assert tbdy2018_f1(0.15, "ZE") == pytest.approx(3.75)  # 4.2 + (3.3 - 4.2) * 0.5


def test_fs_clamp_below() -> None:
    assert tbdy2018_fs(0.10, "ZE") == pytest.approx(2.4)
    assert tbdy2018_fs(0.0, "ZE") == pytest.approx(2.4)


def test_fs_clamp_above() -> None:
    assert tbdy2018_fs(2.0, "ZE") == pytest.approx(0.8)


def test_zf_raises() -> None:
    with pytest.raises(ValueError, match="ZF"):
        tbdy2018_fs(0.5, "ZF")
    with pytest.raises(ValueError, match="ZF"):
        tbdy2018_f1(0.3, "ZF")
    with pytest.raises(ValueError, match="Unknown site class"):
        tbdy2018_fs(0.5, "ZX")


def test_sds_sd1_reference(dd2_zc) -> None:  # type: ignore[no-untyped-def]
    assert dd2_zc.sds == pytest.approx(0.585, abs=1e-12)
    assert dd2_zc.sd1 == pytest.approx(0.1755, abs=1e-12)


def test_corner_periods_reference(dd2_zc) -> None:  # type: ignore[no-untyped-def]
    ta, tb = tbdy2018_corner_periods(dd2_zc.sds, dd2_zc.sd1)
    assert ta == pytest.approx(0.060, abs=1e-12)
    assert tb == pytest.approx(0.300, abs=1e-12)
    assert TBDY_TL == 6.0


# --- table breakpoints, clamping, constants -------------------------------
def test_every_breakpoint_returns_the_table_value() -> None:
    for site in ("ZA", "ZB", "ZC", "ZD", "ZE"):
        for ss, fs in zip(TBDY_SS_POINTS, TBDY_FS_TABLE[site], strict=True):
            assert tbdy2018_fs(ss, site) == fs
        for s1, f1 in zip(TBDY_S1_POINTS, TBDY_F1_TABLE[site], strict=True):
            assert tbdy2018_f1(s1, site) == f1


def test_interpolation_midpoints_between_every_pair_of_breakpoints() -> None:
    for site in ("ZC", "ZD", "ZE"):
        for i in range(len(TBDY_SS_POINTS) - 1):
            mid = 0.5 * (TBDY_SS_POINTS[i] + TBDY_SS_POINTS[i + 1])
            fs = TBDY_FS_TABLE[site]
            assert tbdy2018_fs(mid, site) == pytest.approx(0.5 * (fs[i] + fs[i + 1]))
        for i in range(len(TBDY_S1_POINTS) - 1):
            mid = 0.5 * (TBDY_S1_POINTS[i] + TBDY_S1_POINTS[i + 1])
            f1 = TBDY_F1_TABLE[site]
            assert tbdy2018_f1(mid, site) == pytest.approx(0.5 * (f1[i] + f1[i + 1]))


def test_f1_clamps_below_and_above_and_refuses_negative() -> None:
    assert tbdy2018_f1(0.05, "ZD") == pytest.approx(2.4)
    assert tbdy2018_f1(0.9, "ZD") == pytest.approx(1.7)
    with pytest.raises(ValueError, match=">= 0"):
        tbdy2018_fs(-0.1, "ZC")


def test_unrounded_corner_periods_are_exact() -> None:
    # SDS 0.6, SD1 0.25 (ZB: Fs 0.9, F1 0.8 from Ss 2/3, S1 0.3125): TB = 5/12 exactly, not 0.4167
    d = tbdy2018_design_accelerations(0.6 / 0.9, 0.25 / 0.8, "ZB")
    ta, tb = tbdy2018_corner_periods(d.sds, d.sd1)
    assert tb == pytest.approx(5.0 / 12.0, abs=1e-15)
    assert ta == pytest.approx(1.0 / 12.0, abs=1e-15)


def test_site_classes_and_levels_are_labels() -> None:
    assert SITE_CLASSES == ("ZA", "ZB", "ZC", "ZD", "ZE", "ZF")
    assert EARTHQUAKE_LEVELS == ("DD-1", "DD-2", "DD-3", "DD-4")
    assert set(EARTHQUAKE_LEVEL_LABELS) == set(EARTHQUAKE_LEVELS)
    assert EARTHQUAKE_LEVEL_LABELS["DD-2"].startswith("DD-2")


# --- TargetSpectrum from Ss, S1 and site class ----------------------------
def test_target_from_site_derives_and_stores_both_forms() -> None:
    ts = TargetSpectrum(
        id=1, kind="tbdy2018", ss=SS, s1=S1, site_class="ZC", earthquake_level="DD-2"
    )
    assert ts.from_site
    assert (ts.fs, ts.f1) == (1.3, 1.5)
    assert ts.sds == pytest.approx(0.585) and ts.sd1 == pytest.approx(0.1755)
    assert ts.sa_at([0.06, 0.30, 1.0]) == pytest.approx(
        tbdy2018_sae([0.06, 0.30, 1.0], 0.585, 0.1755)
    )
    text = ts.describe()
    assert "DD-2" in text and "ZC" in text and "Fs=1.3" in text
    direct = TargetSpectrum(id=2, kind="tbdy2018", sds=0.585, sd1=0.1755)
    assert not direct.from_site and direct.fs is None
    assert "Ss=" not in direct.describe()


def test_target_from_site_round_trips_and_rejects_partial_or_inconsistent_input() -> None:
    ts = TargetSpectrum(id=1, kind="tbdy2018", ss=SS, s1=S1, site_class="ZD")
    assert TargetSpectrum.model_validate(ts.model_dump()) == ts
    p = Project(target_spectra=[ts])
    assert Project.model_validate(p.model_dump()).target_spectrum(1) == ts
    assert p.schema_version == 2  # additive fields, schema unchanged
    with pytest.raises(ValidationError, match="together"):
        TargetSpectrum(id=2, kind="tbdy2018", ss=SS, s1=S1)
    with pytest.raises(ValidationError, match="ZF"):
        TargetSpectrum(id=3, kind="tbdy2018", ss=SS, s1=S1, site_class="ZF")
    with pytest.raises(ValidationError, match="does not match"):
        TargetSpectrum(id=4, kind="tbdy2018", ss=SS, s1=S1, site_class="ZC", sds=0.7, sd1=0.1755)
    # a matching explicit pair is accepted (what a saved file carries)
    ok = TargetSpectrum(id=5, kind="tbdy2018", ss=SS, s1=S1, site_class="ZC", sds=0.585, sd1=0.1755)
    assert ok.fs == 1.3
