"""Repeated modes turned to the excitation: one basis whatever the solver returned."""

from __future__ import annotations

import numpy as np
import pytest


def test_aligning_a_repeated_pair_makes_participation_basis_independent() -> None:
    """Any rotation of a repeated pair gives the same aligned modes."""
    from opensees_studio.core.modal import align_degenerate_modes

    nodes = [1, 2, 3]
    mass = {n: np.array([2.0, 2.0, 0.0]) for n in nodes}
    flat_mass = np.concatenate([mass[n] for n in nodes])
    v1 = np.array([1.0, 0.2, 0.0, 0.5, -0.3, 0.0, 0.1, 0.9, 0.0])
    v1 /= np.sqrt((v1 * flat_mass) @ v1)
    v2 = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0])
    v2 -= ((v1 * flat_mass) @ v2) * v1
    v2 /= np.sqrt((v2 * flat_mass) @ v2)

    def shapes(theta: float) -> dict[int, dict[int, np.ndarray]]:
        c, s = np.cos(theta), np.sin(theta)
        a, b = c * v1 + s * v2, -s * v1 + c * v2
        return {
            1: {n: a[3 * k : 3 * k + 3] for k, n in enumerate(nodes)},
            2: {n: b[3 * k : 3 * k + 3] for k, n in enumerate(nodes)},
        }

    influence = np.tile([1.0, 0.0, 0.0], 3)
    results = []
    for theta in (0.0, 0.4, 1.3, 2.9):
        out = align_degenerate_modes([5.0, 5.0], shapes(theta), mass, 1)
        flat = [np.concatenate([out[m][n] for n in nodes]) for m in (1, 2)]
        gammas = [(f * flat_mass) @ influence for f in flat]
        assert abs(gammas[1]) < 1e-12  # the second mode takes no part in X
        results.append(np.abs(flat[0]))
    for other in results[1:]:
        assert other == pytest.approx(results[0], abs=1e-12)
