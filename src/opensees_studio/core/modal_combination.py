"""Modal combination rules for response spectrum analysis (numpy only).

Peak modal responses ``u_i`` (any response quantity, one value per mode)
are combined into a single peak estimate:

- SRSS: ``u = sqrt(sum_i u_i^2)``. It assumes the modal responses are
  uncorrelated, which fails for closely spaced modes. Inside a degenerate
  pair (repeated or near-repeated eigenvalue) the eigen solver returns an
  arbitrary basis of the two-dimensional eigenspace, and the SRSS value
  changes with that basis.
- CQC: ``u = sqrt(sum_i sum_j rho_ij u_i u_j)`` with the correlation of
  Der Kiureghian (1981). For a degenerate pair ``rho = 1`` and the sum
  reduces to ``(u_i + u_j)^2``, which is invariant under any rotation of
  the pair. CQC is therefore the rule that does not depend on the basis
  the solver happened to pick.

The correlation coefficient for modes ``i`` and ``j`` with circular
frequencies ``w_i``, ``w_j`` and damping ratios ``z_i``, ``z_j``,
``r = w_j / w_i``::

    rho_ij = 8 sqrt(z_i z_j) (z_i + r z_j) r^1.5
             / ((1 - r^2)^2 + 4 z_i z_j r (1 + r^2) + 4 (z_i^2 + z_j^2) r^2)

For equal damping ``z`` this is the familiar
``8 z^2 (1 + r) r^1.5 / ((1 - r^2)^2 + 4 z^2 r (1 + r)^2)``.

This module is part of ``core``: no Qt, no openseespy.
"""

from __future__ import annotations

import numpy as np

DEFAULT_MODAL_DAMPING = 0.05
"""Damping the CQC correlation falls back to when case and spectrum would give zero."""

CLOSELY_SPACED_RATIO = 0.9
"""Two modes count as closely spaced when the lower over the higher frequency is at least this."""


def cqc_correlation(
    angular_frequencies: np.ndarray | list[float],
    damping: float | np.ndarray | list[float],
) -> np.ndarray:
    """Der Kiureghian correlation matrix ``rho`` (n_modes x n_modes).

    ``damping`` is one ratio for every mode or one ratio per mode. Modes
    with a non-positive frequency get ``rho = 0`` off the diagonal (they
    carry no spectral response). The diagonal is exactly 1.
    """
    omega = np.asarray(angular_frequencies, dtype=float).ravel()
    n = omega.size
    zeta = np.broadcast_to(np.asarray(damping, dtype=float).ravel(), (n,)).astype(float)
    if np.any(zeta < 0.0):
        raise ValueError("Damping ratios must not be negative.")
    rho = np.eye(n)
    valid = omega > 0.0
    for i in range(n):
        for j in range(n):
            if i == j or not (valid[i] and valid[j]):
                continue
            r = omega[j] / omega[i]
            zi, zj = zeta[i], zeta[j]
            num = 8.0 * np.sqrt(zi * zj) * (zi + r * zj) * r**1.5
            den = (
                (1.0 - r * r) ** 2
                + 4.0 * zi * zj * r * (1.0 + r * r)
                + 4.0 * (zi * zi + zj * zj) * r * r
            )
            rho[i, j] = num / den if den > 0.0 else (1.0 if r == 1.0 else 0.0)
    return rho


def combine_srss(modal_peaks: np.ndarray) -> np.ndarray:
    """SRSS of ``modal_peaks`` (first axis is the mode); returns the remaining axes."""
    peaks = np.asarray(modal_peaks, dtype=float)
    return np.sqrt(np.sum(peaks * peaks, axis=0))


def combine_cqc(modal_peaks: np.ndarray, rho: np.ndarray) -> np.ndarray:
    """CQC of ``modal_peaks`` (first axis is the mode) with correlation ``rho``."""
    peaks = np.asarray(modal_peaks, dtype=float)
    rho = np.asarray(rho, dtype=float)
    n = peaks.shape[0]
    if rho.shape != (n, n):
        raise ValueError(f"rho must be {n} x {n}, got {rho.shape}.")
    flat = peaks.reshape(n, -1)
    total = np.einsum("ik,ij,jk->k", flat, rho, flat)
    return np.sqrt(np.maximum(total, 0.0)).reshape(peaks.shape[1:])


def closely_spaced_pairs(
    angular_frequencies: np.ndarray | list[float],
    *,
    ratio: float = CLOSELY_SPACED_RATIO,
) -> list[tuple[int, int, float]]:
    """``(i, j, lower / higher)`` for every pair of modes whose frequency ratio is at least ``ratio``.

    Indices are 0-based positions in ``angular_frequencies``; modes with a
    non-positive frequency are ignored.
    """
    omega = np.asarray(angular_frequencies, dtype=float).ravel()
    out: list[tuple[int, int, float]] = []
    for i in range(omega.size):
        for j in range(i + 1, omega.size):
            if omega[i] <= 0.0 or omega[j] <= 0.0:
                continue
            lower, higher = sorted((omega[i], omega[j]))
            value = lower / higher
            if value >= ratio:
                out.append((i, j, float(value)))
    return out
