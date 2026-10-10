"""core.modal_combination: Der Kiureghian correlation, SRSS, CQC, rotation invariance."""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core.modal_combination import (
    CLOSELY_SPACED_RATIO,
    closely_spaced_pairs,
    combine_cqc,
    combine_srss,
    cqc_correlation,
)


# ─────────────────────── correlation ───────────────────────
def test_rho_is_one_for_equal_frequencies_and_equal_damping() -> None:
    rho = cqc_correlation([10.0, 10.0, 10.0], 0.05)
    assert np.allclose(rho, 1.0)
    assert np.array_equal(np.diag(cqc_correlation([1.0, 2.0, 3.0], 0.05)), np.ones(3))


def test_rho_tends_to_zero_for_widely_separated_frequencies() -> None:
    rho = cqc_correlation([1.0, 10.0], 0.05)
    assert rho[0, 1] == pytest.approx(0.000708951386653599, rel=1e-12)
    ratios = [2.0, 5.0, 10.0, 50.0, 1000.0]
    values = [cqc_correlation([1.0, r], 0.05)[0, 1] for r in ratios]
    assert values == sorted(values, reverse=True)
    # Asymptotically rho ~ 8 zeta^2 / r^1.5, so 1000 gives about 6.3e-7.
    assert values[-1] < 1e-6
    assert values[-1] == pytest.approx(8.0 * 0.05**2 / 1000.0**1.5, rel=2e-3)


def test_rho_closed_form_at_chosen_ratio_and_damping() -> None:
    # r = 0.9, zeta = 0.05: 8 z^2 (1 + r) r^1.5 / ((1 - r^2)^2 + 4 z^2 r (1 + r)^2)
    rho = cqc_correlation([1.0, 0.9], 0.05)
    assert rho[0, 1] == pytest.approx(0.473027683238483335, rel=1e-12)
    assert rho[1, 0] == pytest.approx(0.473027683238483335, rel=1e-12)
    assert cqc_correlation([2.0, 1.0], 0.02)[0, 1] == pytest.approx(
        0.00300736536389812876, rel=1e-12
    )


def test_rho_unequal_damping_form_is_symmetric_and_reduces_to_equal_form() -> None:
    rho = cqc_correlation([1.0, 0.8], [0.02, 0.10])
    assert rho[0, 1] == pytest.approx(0.153550863723608445, rel=1e-12)
    assert rho[1, 0] == pytest.approx(rho[0, 1], rel=1e-12)
    # Per-mode damping equal to a scalar gives the equal-damping matrix.
    omega = [3.0, 2.9, 7.0, 7.1]
    assert np.allclose(cqc_correlation(omega, [0.05] * 4), cqc_correlation(omega, 0.05))
    with pytest.raises(ValueError, match="negative"):
        cqc_correlation(omega, [-0.01, 0.05, 0.05, 0.05])


def test_rho_ignores_modes_without_frequency() -> None:
    rho = cqc_correlation([0.0, 5.0, 5.0], 0.05)
    assert rho[0, 1] == rho[0, 2] == 0.0
    assert rho[1, 2] == 1.0
    assert rho[0, 0] == 1.0


# ─────────────────────── combination ───────────────────────
def test_srss_and_cqc_agree_for_uncorrelated_modes() -> None:
    peaks = np.array([[3.0, 0.0], [4.0, 1.0]])
    assert np.allclose(combine_srss(peaks), [5.0, 1.0])
    assert np.allclose(combine_cqc(peaks, np.eye(2)), [5.0, 1.0])
    assert np.allclose(combine_cqc(peaks, np.ones((2, 2))), [7.0, 1.0])
    with pytest.raises(ValueError, match="rho must be"):
        combine_cqc(peaks, np.eye(3))


def _degenerate_pair() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Lumped masses, two mass-orthonormal shapes sharing one frequency, one distinct mode."""
    rng = np.random.default_rng(7)
    mass = rng.uniform(1.0, 3.0, size=8)
    a = rng.normal(size=8)
    b = rng.normal(size=8)
    # Gram-Schmidt in the mass inner product.
    a /= np.sqrt(a @ (mass * a))
    b -= (b @ (mass * a)) * a
    b /= np.sqrt(b @ (mass * b))
    c = rng.normal(size=8)
    c -= (c @ (mass * a)) * a + (c @ (mass * b)) * b
    c /= np.sqrt(c @ (mass * c))
    return mass, a, b, c


def _peaks(mass: np.ndarray, shapes: list[np.ndarray], omega: np.ndarray) -> np.ndarray:
    """u_i = Gamma_i phi_i Sa / omega_i^2 with Sa = 1 and Gamma_i = phi_i^T M 1."""
    influence = np.ones(mass.size)
    return np.array(
        [(phi @ (mass * influence)) * phi / w**2 for phi, w in zip(shapes, omega, strict=True)]
    )


def test_cqc_is_invariant_under_rotation_of_a_degenerate_pair_and_srss_is_not() -> None:
    mass, a, b, c = _degenerate_pair()
    omega = np.array([12.0, 12.0, 30.0])
    rho = cqc_correlation(omega, 0.05)
    assert rho[0, 1] == 1.0

    reference_cqc = combine_cqc(_peaks(mass, [a, b, c], omega), rho)
    reference_srss = combine_srss(_peaks(mass, [a, b, c], omega))
    cqc_spread = 0.0
    srss_spread = 0.0
    for degrees in (15.0, 30.0, 45.0, 60.0, 90.0, 137.0, 200.0):
        t = np.radians(degrees)
        rotated = [np.cos(t) * a + np.sin(t) * b, -np.sin(t) * a + np.cos(t) * b, c]
        peaks = _peaks(mass, rotated, omega)
        cqc_spread = max(cqc_spread, float(np.max(np.abs(combine_cqc(peaks, rho) - reference_cqc))))
        srss_spread = max(srss_spread, float(np.max(np.abs(combine_srss(peaks) - reference_srss))))
    scale = float(np.max(np.abs(reference_cqc)))
    assert cqc_spread <= 1e-12 * scale, f"CQC moved by {cqc_spread:.3e} across rotations"
    assert srss_spread > 1e-2 * scale, f"SRSS only moved by {srss_spread:.3e}"


def test_combine_cqc_keeps_extra_axes() -> None:
    peaks = np.ones((2, 4, 3))
    out = combine_cqc(peaks, np.ones((2, 2)))
    assert out.shape == (4, 3)
    assert np.allclose(out, 2.0)


# ─────────────────────── closely spaced modes ───────────────────────
def test_closely_spaced_pairs_use_lower_over_higher_frequency() -> None:
    assert CLOSELY_SPACED_RATIO == 0.9
    pairs = closely_spaced_pairs([27.55, 27.55, 30.15, 73.2, 117.7, 117.7])
    assert [(i, j) for i, j, _ in pairs] == [(0, 1), (0, 2), (1, 2), (4, 5)]
    assert pairs[1][2] == pytest.approx(27.55 / 30.15)
    assert closely_spaced_pairs([10.0, 20.0]) == []
    assert closely_spaced_pairs([10.0, 11.0], ratio=0.95) == []
    assert closely_spaced_pairs([0.0, 10.0, 10.0]) == [(1, 2, 1.0)]
