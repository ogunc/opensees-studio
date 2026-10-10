"""Hardening in the live build against closed-form linear kinematic hardening."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import Hardening
from opensees_studio.services.material_tester import (
    CyclicSegment,
    LoadProtocol,
    test_uniaxial_material,
)

E, SIGMA_Y = 29000.0, 36.0
H_KIN = 0.05 / (1 - 0.05) * E  # the Nonlinear Truss example
E_T = E * H_KIN / (E + H_KIN)
EPS_Y = SIGMA_Y / E


def _kinematic(strains: list[float]) -> np.ndarray:
    """Return-mapping reference for linear kinematic hardening (H_iso 0)."""
    stress = back = eps_old = 0.0
    out = []
    for eps in strains:
        trial = stress + E * (eps - eps_old)
        overshoot = abs(trial - back) - SIGMA_Y
        if overshoot > 0.0:
            gamma = overshoot / (E + H_KIN)
            sign = np.sign(trial - back)
            trial -= E * gamma * sign
            back += H_KIN * gamma * sign
        stress, eps_old = trial, eps
        out.append(stress)
    return np.array(out)


def test_monotonic_follows_e_then_the_hardening_tangent() -> None:
    assert abs(E_T - 1450.0) < 1e-9
    material = Hardening(id=1, E=E, sigmaY=SIGMA_Y, H_iso=0.0, H_kin=H_KIN)
    result = test_uniaxial_material(
        material, LoadProtocol(kind="monotonic", max_compressive=-0.004, n_steps_per_branch=40)
    )
    eps = -np.array(result.strain)
    sig = -np.array(result.stress)
    expected = np.where(eps <= EPS_Y, E * eps, SIGMA_Y + E_T * (eps - EPS_Y))
    assert np.allclose(sig, expected, rtol=1e-9, atol=1e-9)
    plastic = eps > EPS_Y * 1.01
    tangent = np.diff(sig[plastic]) / np.diff(eps[plastic])
    assert np.allclose(tangent, E_T, rtol=1e-8)


def test_cyclic_loop_shows_kinematic_translation() -> None:
    material = Hardening(id=1, E=E, sigmaY=SIGMA_Y, H_iso=0.0, H_kin=H_KIN)
    protocol = LoadProtocol(
        kind="cyclic",
        max_compressive=-0.004,
        n_steps_per_branch=80,
        cycles=[CyclicSegment(compressive_peak=-0.004, tensile_peak=0.004, n_cycles=2)],
    )
    result = test_uniaxial_material(material, protocol)
    strain, stress = np.array(result.strain), np.array(result.stress)
    assert np.allclose(stress, _kinematic(list(strain)), rtol=0, atol=1e-9 * SIGMA_Y)

    # Reverse yield after the compressive peak happens 2 sigmaY above the peak stress:
    # the elastic range keeps its width and moves with the back stress.
    peak = int(np.argmin(strain))
    reloading = slice(peak + 1, peak + 81)
    slope = np.diff(stress[reloading]) / np.diff(strain[reloading])
    first_plastic = peak + 1 + int(np.argmax(slope < 0.5 * E))
    assert stress[peak] == pytest.approx(-(SIGMA_Y + E_T * (0.004 - EPS_Y)), rel=1e-9)
    assert stress[first_plastic] == pytest.approx(stress[peak] + 2 * SIGMA_Y, rel=2e-2)
    assert abs(stress[peak] + 2 * SIGMA_Y) < SIGMA_Y  # yields in tension below sigmaY
