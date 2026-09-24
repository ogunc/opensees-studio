"""TBDY 2018 horizontal design spectrum and TargetSpectrum model tests."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    TBDY_TL,
    Project,
    TargetSpectrum,
    loglog_interp,
    tbdy2018_corner_periods,
    tbdy2018_sae,
)

SDS, SD1 = 1.2, 0.5  # TA = 0.0833 s, TB = 0.4167 s


def test_corner_periods() -> None:
    ta, tb = tbdy2018_corner_periods(SDS, SD1)
    assert ta == pytest.approx(0.2 * SD1 / SDS)
    assert tb == pytest.approx(SD1 / SDS)
    assert TBDY_TL == 6.0
    with pytest.raises(ValueError, match="positive"):
        tbdy2018_corner_periods(0.0, SD1)


def test_short_period_branch() -> None:
    ta, _tb = tbdy2018_corner_periods(SDS, SD1)
    assert tbdy2018_sae(0.0, SDS, SD1)[0] == pytest.approx(0.4 * SDS)
    assert tbdy2018_sae(0.5 * ta, SDS, SD1)[0] == pytest.approx(0.7 * SDS)


def test_plateau_branch_and_corners() -> None:
    ta, tb = tbdy2018_corner_periods(SDS, SD1)
    sae = tbdy2018_sae([ta, 0.5 * (ta + tb), tb], SDS, SD1)
    assert sae == pytest.approx([SDS, SDS, SDS])


def test_velocity_branch() -> None:
    _ta, tb = tbdy2018_corner_periods(SDS, SD1)
    for t in (1.01 * tb, 1.0, 3.0, TBDY_TL):
        assert tbdy2018_sae(t, SDS, SD1)[0] == pytest.approx(SD1 / t)


def test_displacement_branch() -> None:
    for t in (6.5, 8.0, 12.0):
        assert tbdy2018_sae(t, SDS, SD1)[0] == pytest.approx(SD1 * TBDY_TL / t**2)


def test_continuity_at_every_corner() -> None:
    ta, tb = tbdy2018_corner_periods(SDS, SD1)
    for corner in (ta, tb, TBDY_TL):
        left, right = tbdy2018_sae([corner * (1 - 1e-9), corner * (1 + 1e-9)], SDS, SD1)
        assert left == pytest.approx(right, rel=1e-6)


def test_vectorised_and_monotone_after_plateau() -> None:
    t = np.geomspace(0.01, 10.0, 200)
    sae = tbdy2018_sae(t, SDS, SD1)
    assert sae.shape == t.shape
    _ta, tb = tbdy2018_corner_periods(SDS, SD1)
    tail = sae[t > tb]
    assert np.all(np.diff(tail) < 0.0)
    with pytest.raises(ValueError, match=">= 0"):
        tbdy2018_sae([-0.1], SDS, SD1)


def test_loglog_interp_is_exact_for_power_law_and_clamps() -> None:
    tp = np.array([0.1, 0.3, 1.0, 3.0])
    sa = 0.8 * tp**-1.0
    q = loglog_interp([0.2, 0.5, 2.0], tp, sa)
    assert q == pytest.approx(0.8 / np.array([0.2, 0.5, 2.0]))
    ends = loglog_interp([0.0, 0.01, 50.0], tp, sa)
    assert ends == pytest.approx([sa[0], sa[0], sa[-1]])
    with pytest.raises(ValueError, match="strictly increasing"):
        loglog_interp([0.5], [0.1, 0.1], [1.0, 1.0])
    with pytest.raises(ValueError, match="positive"):
        loglog_interp([0.5], [0.1, 1.0], [1.0, 0.0])


def test_target_spectrum_tbdy_model() -> None:
    ts = TargetSpectrum(id=1, name="DD-2", kind="tbdy2018", sds=SDS, sd1=SD1)
    ta, _tb = tbdy2018_corner_periods(SDS, SD1)
    assert ts.sa_at([0.0, ta, 3.0]) == pytest.approx([0.4 * SDS, SDS, SD1 / 3.0])
    assert "TBDY 2018" in ts.describe()
    with pytest.raises(ValidationError, match="sds and sd1"):
        TargetSpectrum(id=2, kind="tbdy2018", sds=SDS)


def test_target_spectrum_user_model() -> None:
    ts = TargetSpectrum(id=1, kind="user", periods=[0.1, 1.0, 4.0], sa=[1.0, 0.5, 0.1])
    assert ts.sa_at(1.0)[0] == pytest.approx(0.5)
    assert ts.sa_at(10.0)[0] == pytest.approx(0.1)
    assert "User table" in ts.describe()
    with pytest.raises(ValidationError):
        TargetSpectrum(id=2, kind="user", periods=[0.1], sa=[1.0])
    with pytest.raises(ValidationError):
        TargetSpectrum(id=3, kind="user", periods=[0.1, 1.0], sa=[1.0, -0.5])


def test_project_stores_target_spectra_additively() -> None:
    p = Project()
    assert p.target_spectra == []
    assert p.next_target_spectrum_id() == 1
    p.target_spectra.append(TargetSpectrum(id=1, kind="tbdy2018", sds=SDS, sd1=SD1))
    assert p.target_spectrum(1).sds == SDS
    assert p.next_target_spectrum_id() == 2
    restored = Project.model_validate(p.model_dump())
    assert restored.model_dump() == p.model_dump()
    # a pre-GM-2 payload without the key still loads
    payload = p.model_dump()
    del payload["target_spectra"]
    assert Project.model_validate(payload).target_spectra == []
    with pytest.raises(ValidationError, match="Duplicate target spectrum ids"):
        Project(
            target_spectra=[
                TargetSpectrum(id=1, kind="tbdy2018", sds=SDS, sd1=SD1),
                TargetSpectrum(id=1, kind="tbdy2018", sds=SDS, sd1=SD1),
            ],
        )
