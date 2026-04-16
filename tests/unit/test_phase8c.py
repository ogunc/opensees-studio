"""Unit tests for Phase 8c: response spectrum + mass participation."""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    Node,
    Project,
    ProjectMeta,
    ResponseSpectrum,
    ResponseSpectrumCase,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project
from opensees_studio.services.results import ModalResults
from opensees_studio.services.spectrum import (
    combine_modal_response,
    interp_sa,
    mass_participation,
)


# ── ResponseSpectrum schema ──────────────────────────────────────────
def test_response_spectrum_basic() -> None:
    s = ResponseSpectrum(
        id=1, name="EC8 type 1",
        periods=[0.0001, 0.1, 0.4, 1.0, 4.0],
        accelerations=[0.5, 1.0, 2.5, 1.0, 0.25],
        damping_ratio=0.05,
    )
    assert s.type == "ResponseSpectrum"
    assert s.damping_ratio == 0.05


def test_response_spectrum_rejects_unsorted_periods() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        ResponseSpectrum(
            id=1, periods=[0.1, 0.5, 0.4],     # 0.5 then 0.4 = not increasing
            accelerations=[1.0, 2.0, 1.5],
        )


def test_response_spectrum_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        ResponseSpectrum(
            id=1, periods=[0.1, 0.5, 1.0],
            accelerations=[1.0, 2.0],
        )


def test_response_spectrum_rejects_zero_period() -> None:
    with pytest.raises(ValueError):
        ResponseSpectrum(
            id=1, periods=[0.0, 0.5],
            accelerations=[1.0, 2.0],
        )


# ── interp_sa ────────────────────────────────────────────────────────
def test_interp_sa_clamps_outside_table() -> None:
    s = ResponseSpectrum(
        id=1, periods=[0.1, 1.0],
        accelerations=[0.5, 0.2],
    )
    assert interp_sa(s, 0.05) == 0.5    # below: clamp to first
    assert interp_sa(s, 5.0) == 0.2     # above: clamp to last


def test_interp_sa_linear_in_table() -> None:
    s = ResponseSpectrum(
        id=1, periods=[0.1, 1.1],
        accelerations=[1.0, 0.0],
    )
    # midpoint linearly = 0.5
    assert interp_sa(s, 0.6) == pytest.approx(0.5)


# ── mass_participation ───────────────────────────────────────────────
def _two_dof_modal(masses: list[float]) -> tuple[Project, ModalResults]:
    """Synthetic 2-mass shear-frame with given masses on direction 1.

    Mode shapes: pure translation in DOF 1 with simple φ = (1, 1) and
    φ = (1, -1). Eigenvalues set to ω² = 100 and 400 (T = 0.628 s, 0.314 s).
    """
    p = Project(
        meta=ProjectMeta(name="2dof", units=UnitSystem.SI_M_N),
        ndm=3, ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=(0, 0, 1.0),
                 mass=(masses[0], 0, 0, 0, 0, 0)),
            Node(id=3, coords=(0, 0, 2.0),
                 mass=(masses[1], 0, 0, 0, 0, 0)),
        ],
        sections=[ElasticSection(id=1, E=2e11, A=0.01,
                                 Iz=1e-5, Iy=1e-5, G=8e10, J=1e-6)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
        ],
    )
    modal = ModalResults(
        case_id=1, case_name="Modal",
        eigenvalues=np.array([100.0, 400.0]),
        mode_shapes={
            1: {2: np.array([1.0, 0, 0, 0, 0, 0]),
                3: np.array([1.0, 0, 0, 0, 0, 0])},
            2: {2: np.array([1.0, 0, 0, 0, 0, 0]),
                3: np.array([-1.0, 0, 0, 0, 0, 0])},
        },
    )
    return p, modal


def test_mass_participation_two_dof_equal_mass() -> None:
    p, modal = _two_dof_modal([1.0, 1.0])
    modes = mass_participation(p, modal, direction=1)
    assert len(modes) == 2

    # Mode 1 (φ = (1, 1)): Γ = (1·1 + 1·1) / (1·1 + 1·1) = 1; M_eff = 1²·2 = 2
    assert modes[0].participation_factor == pytest.approx(1.0)
    assert modes[0].effective_mass == pytest.approx(2.0)
    assert modes[0].mass_ratio == pytest.approx(1.0)   # 100% of total mass

    # Mode 2 (φ = (1, -1)): Γ = (1·1 + 1·-1) / (1 + 1) = 0; M_eff = 0
    assert modes[1].participation_factor == pytest.approx(0.0)
    assert modes[1].effective_mass == pytest.approx(0.0)


def test_mass_participation_periods_match_eigenvalues() -> None:
    p, modal = _two_dof_modal([1.0, 1.0])
    modes = mass_participation(p, modal, direction=1)
    # ω₁² = 100 → ω₁ = 10 → T₁ = 2π/10 ≈ 0.628
    assert modes[0].period == pytest.approx(2.0 * np.pi / 10.0)
    assert modes[1].period == pytest.approx(2.0 * np.pi / 20.0)


# ── combine_modal_response ───────────────────────────────────────────
def test_srss_recovers_single_mode_when_only_one_active() -> None:
    p, modal = _two_dof_modal([1.0, 1.0])
    modes = mass_participation(p, modal, direction=1)
    # Spectrum: constant 1.0 m/s² so Sa(T) = 1 for any T.
    s = ResponseSpectrum(id=1, periods=[0.01, 100.0],
                         accelerations=[1.0, 1.0])
    combined, _ = combine_modal_response(modes, s, modal,
                                         direction=1, method="SRSS")
    # Mode 1 only contributes (Γ_2 = 0). u_2 = Γ_1·φ_1·Sa/ω_1² = 1·1·1/100 = 0.01
    assert combined[2][0] == pytest.approx(0.01)
    assert combined[3][0] == pytest.approx(0.01)


def test_cqc_equals_srss_for_well_separated_modes() -> None:
    """When modes are well-separated (ω₂/ω₁ = 2), CQC ≈ SRSS."""
    p, modal = _two_dof_modal([1.0, 1.0])
    modes = mass_participation(p, modal, direction=1)
    s = ResponseSpectrum(id=1, periods=[0.01, 100.0],
                         accelerations=[1.0, 1.0])
    srss, _ = combine_modal_response(modes, s, modal, direction=1,
                                     method="SRSS")
    cqc, _ = combine_modal_response(modes, s, modal, direction=1,
                                    method="CQC")
    # Mode 2 is silent (Γ=0) so both should give identical answers.
    np.testing.assert_array_almost_equal(srss[2], cqc[2], decimal=10)


# ── ResponseSpectrumCase persistence ─────────────────────────────────
def test_response_spectrum_case_round_trip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = Project(
        meta=ProjectMeta(name="rs", units=UnitSystem.SI_M_N),
        ndm=3, ndf=6,
        nodes=[Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
               Node(id=2, coords=(0, 0, 3))],
        sections=[ElasticSection(id=1, E=2e11, A=0.01, Iz=1e-5,
                                 Iy=1e-5, G=8e10, J=1e-6)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        spectra=[ResponseSpectrum(
            id=1, name="Demo",
            periods=[0.1, 0.5, 2.0],
            accelerations=[2.5, 2.5, 0.5],
        )],
        analyses=[ResponseSpectrumCase(
            id=1, modal_case_id=2, spectrum_id=1,
            direction=1, combination="CQC", damping_ratio=0.03,
        )],
    )
    path = tmp_path / "rs.osmodel"
    save_project(p, path)
    restored = load_project(path)
    assert len(restored.spectra) == 1
    assert restored.spectra[0].periods[1] == 0.5
    case = restored.analyses[0]
    assert case.combination == "CQC"
    assert case.damping_ratio == 0.03
