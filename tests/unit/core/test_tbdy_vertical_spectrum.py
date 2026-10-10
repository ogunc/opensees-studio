"""TBDY 2018 vertical design spectrum SaeD (Md. 2.3.5), ported from cfs-egitim-app.

Validation points are the owner's ``test_saed_sap2000_validation`` (SAP2000
TSC-2018 DD2 vertical function for Ss 0.45, S1 0.117, ZC: SDS 0.585,
SD1 0.1755, TAD 0.02 s, TBD 0.10 s, TLD 3.0 s) plus the owner's branch
tests ``test_saed_at_zero``, ``test_saed_plateau``, ``test_saed_descending``
and ``test_saed_continuity``.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    Project,
    TargetSpectrum,
    tbdy2018_corner_periods,
    tbdy2018_saed,
    tbdy2018_vertical_corner_periods,
)

SDS, SD1 = 0.585, 0.1755


def test_vertical_corner_periods_reference() -> None:
    tad, tbd, tld = tbdy2018_vertical_corner_periods(SDS, SD1)
    ta, tb = tbdy2018_corner_periods(SDS, SD1)
    assert tad == pytest.approx(ta / 3.0) and tad == pytest.approx(0.02)
    assert tbd == pytest.approx(tb / 3.0) and tbd == pytest.approx(0.10)
    assert tld == 3.0


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        (0.00, 0.1872),
        (0.02, 0.468),
        (0.10, 0.468),
        (0.20, 0.234),
        (0.40, 0.117),
        (0.60, 0.078),
        (0.80, 0.0585),
        (1.00, 0.0468),
    ],
)
def test_saed_sap2000_validation(period: float, expected: float) -> None:
    assert tbdy2018_saed(period, SDS, SD1)[0] == pytest.approx(expected, abs=0.001)


def test_saed_at_zero() -> None:
    assert tbdy2018_saed(0.0, SDS, SD1)[0] == pytest.approx(0.32 * SDS)


def test_saed_plateau() -> None:
    tad, tbd, _ = tbdy2018_vertical_corner_periods(SDS, SD1)
    assert tbdy2018_saed([tad, 0.5 * (tad + tbd), tbd], SDS, SD1) == pytest.approx([0.8 * SDS] * 3)


def test_saed_descending_up_to_tld_and_nan_beyond() -> None:
    """The vertical spectrum is defined only for T <= TLD (Md. 2.3.5)."""
    _, tbd, tld = tbdy2018_vertical_corner_periods(SDS, SD1)
    for t in (0.5, tld):
        assert tbdy2018_saed(t, SDS, SD1)[0] == pytest.approx(0.8 * SDS * tbd / t)
    beyond = tbdy2018_saed([tld * (1 + 1e-9), 2.0 * tld, 10.0], SDS, SD1)
    assert np.all(np.isnan(beyond))
    ts = TargetSpectrum(id=1, kind="tbdy2018_vertical", sds=SDS, sd1=SD1)
    assert ts.max_period == pytest.approx(tld)
    assert TargetSpectrum(id=2, kind="tbdy2018", sds=SDS, sd1=SD1).max_period is None
    assert np.isnan(ts.sa_at(4.0)[0]) and np.isfinite(ts.sa_at(3.0)[0])


def test_saed_continuity_at_tad_and_tbd() -> None:
    tad, tbd, _ = tbdy2018_vertical_corner_periods(SDS, SD1)
    for corner in (tad, tbd):
        left, right = tbdy2018_saed([corner * (1 - 1e-9), corner * (1 + 1e-9)], SDS, SD1)
        assert left == pytest.approx(right, rel=1e-6)


def test_saed_vectorised_rejects_negative_periods() -> None:
    t = np.geomspace(0.01, 10.0, 50)
    sa = tbdy2018_saed(t, SDS, SD1)
    assert sa.shape == t.shape and np.all(np.isfinite(sa[t <= 3.0]))
    with pytest.raises(ValueError, match=">= 0"):
        tbdy2018_saed([-0.1], SDS, SD1)


def test_vertical_target_spectrum_model() -> None:
    ts = TargetSpectrum(id=1, kind="tbdy2018_vertical", sds=SDS, sd1=SD1)
    assert ts.sa_at([0.0, 0.05, 1.0]) == pytest.approx([0.1872, 0.468, 0.0468], abs=1e-4)
    assert ts.corner_periods() == pytest.approx((0.02, 0.10, 3.0))
    assert "vertical" in ts.describe() and "TAD=0.020" in ts.describe()
    from_site = TargetSpectrum(id=2, kind="tbdy2018_vertical", ss=0.45, s1=0.117, site_class="ZC")
    assert from_site.sa_at(0.05)[0] == pytest.approx(0.468)
    horizontal = TargetSpectrum(id=3, kind="tbdy2018", sds=SDS, sd1=SD1)
    assert horizontal.corner_periods() == pytest.approx((0.06, 0.30, 6.0))
    assert (
        TargetSpectrum(id=4, kind="user", periods=[0.1, 1.0], sa=[1.0, 0.5]).corner_periods() == ()
    )
    with pytest.raises(ValidationError, match="sds and sd1"):
        TargetSpectrum(id=5, kind="tbdy2018_vertical", sds=SDS)
    p = Project(target_spectra=[ts])
    assert Project.model_validate(p.model_dump()).target_spectrum(1) == ts
