"""Eigen solver routing and mode shape sign normalization (numpy only).

Two facts drive this module:

- ARPACK (``genBandArpack``) keeps its random start vector across
  ``eigen`` calls inside one process, so only the first eigen call of a
  process is reproducible. A dense LAPACK solve (``fullGenLapack``) is a
  direct method and gives bit-identical results however many times it
  runs. Dense costs about a second at 500 free DOF and grows with the
  cube of the size (657 s at 3402 free DOF), so it is the default only
  at or below :data:`DENSE_EIGEN_MAX_FREE_DOF`; above that the analysis
  CLI runs every ARPACK case as the first eigen call of a fresh process.
- Inside a repeated eigenvalue the solver returns an arbitrary basis of
  the eigenspace, and the dense solver's basis is not even mass-orthogonal
  (space_frame_3d: mass cosine 0.084 between the two sway modes, while
  ARPACK's pair is orthogonal to roundoff). Participation factors, effective
  masses and the CQC combination are basis-invariant only for a
  mass-orthogonal basis, so :func:`orthogonalize_degenerate_modes` applies
  Gram-Schmidt in the mass metric inside every degenerate group.
- The sign of an eigenvector is arbitrary. :func:`normalize_mode_sign`
  fixes it so that the largest absolute component is positive; components
  within a relative tolerance of the maximum count as tied and the lowest
  DOF index wins. Without the tolerance, a symmetric structure whose two
  mirror components differ only by roundoff picks either one depending on
  the solver's rounding and flips an antisymmetric mode entirely.

This module is part of ``core``: no Qt, no openseespy.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

DENSE_EIGEN_MAX_FREE_DOF = 500
"""Largest free DOF count that the automatic routing solves with the dense solver."""

DENSE_EIGEN_MAX_FREE_DOF_ENV = "OPENSEES_STUDIO_DENSE_EIGEN_MAX_DOF"
"""Environment variable overriding :data:`DENSE_EIGEN_MAX_FREE_DOF` (a non-negative integer)."""

SIGN_TIE_REL_TOL = 1e-9
"""Components within this relative distance of the largest absolute value count as tied."""

DEGENERATE_EIGENVALUE_REL_TOL = 1e-6
"""Consecutive eigenvalues closer than this (relative) form one degenerate group."""

SOLVER_AUTO = "auto"
SOLVER_ARPACK = "genBandArpack"
SOLVER_DENSE = "fullGenLapack"
SOLVER_SYMM_BAND = "symmBandLapack"

OFFERED_SOLVERS: tuple[str, ...] = (SOLVER_AUTO, SOLVER_ARPACK, SOLVER_DENSE)
"""Solver names a case may ask for: the two the build really runs, plus the routing."""

KNOWN_SOLVERS: tuple[str, ...] = (*OFFERED_SOLVERS, SOLVER_SYMM_BAND)
"""Names that load unchanged; ``symmBandLapack`` is refused at run time."""

SYMM_BAND_REFUSAL = (
    "symmBandLapack needs a positive definite mass matrix, but lumped nodal masses "
    "leave the rotational (and any massless) DOF without mass, so this build cannot "
    "run it. Choose Auto, genBandArpack or fullGenLapack."
)


def dof_indices(ndm: int, ndf: int) -> tuple[int, ...]:
    """Map (ndm, ndf) onto positions in the canonical 6-DOF storage.

    - (2, 2): 2D truss: (Ux, Uy) = (0, 1)
    - (2, 3): 2D frame: (Ux, Uy, Rz) = (0, 1, 5)
    - (3, 3): 3D truss or brick: (Ux, Uy, Uz) = (0, 1, 2)
    - (3, 6): 3D frame: (Ux, Uy, Uz, Rx, Ry, Rz) = (0..5)
    """
    table = {
        (2, 2): (0, 1),
        (2, 3): (0, 1, 5),
        (3, 3): (0, 1, 2),
        (3, 6): (0, 1, 2, 3, 4, 5),
    }
    if (ndm, ndf) not in table:
        raise ValueError(f"Unsupported (ndm, ndf): ({ndm}, {ndf}).")
    return table[(ndm, ndf)]


def free_dof_count(project: Project) -> int:
    """Number of unrestrained nodal DOF (total DOF minus restrained ones)."""
    idx = dof_indices(project.ndm, project.ndf)
    return sum(len(idx) - sum(int(node.restraint[i]) for i in idx) for node in project.nodes)


def dense_eigen_max_free_dof() -> int:
    """The routing threshold: the environment override when set, else the constant."""
    raw = os.environ.get(DENSE_EIGEN_MAX_FREE_DOF_ENV, "").strip()
    if not raw:
        return DENSE_EIGEN_MAX_FREE_DOF
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{DENSE_EIGEN_MAX_FREE_DOF_ENV}={raw!r} is not an integer free DOF count."
        ) from exc
    if value < 0:
        raise ValueError(f"{DENSE_EIGEN_MAX_FREE_DOF_ENV} must not be negative (got {value}).")
    return value


def resolve_modal_solver(requested: str, n_free: int, n_modes: int) -> tuple[str, str]:
    """Return ``(solver, reason)`` for a modal case.

    ``requested`` is the case's ``solver`` field. ``auto`` picks the dense
    solver at or below the threshold and ARPACK above it. An explicit
    ``genBandArpack`` or ``fullGenLapack`` is honoured, except that ARPACK
    falls back to dense when ``2 * n_modes >= n_free`` (it cannot allocate
    its Arnoldi workspace and aborts with ``_saupd info = -9999``).
    ``symmBandLapack`` raises :class:`ValueError` with :data:`SYMM_BAND_REFUSAL`.
    """
    if requested == SOLVER_SYMM_BAND:
        raise ValueError(SYMM_BAND_REFUSAL)
    if requested not in OFFERED_SOLVERS:
        raise ValueError(
            f"Unknown eigen solver {requested!r}; choose one of {', '.join(OFFERED_SOLVERS)}."
        )
    threshold = dense_eigen_max_free_dof()
    if requested == SOLVER_AUTO:
        if n_free <= threshold:
            return SOLVER_DENSE, f"auto: {n_free} free DOF, dense at or below {threshold}"
        requested = SOLVER_ARPACK
        reason = f"auto: {n_free} free DOF, above {threshold}"
    else:
        reason = f"requested: {n_free} free DOF"
    if requested == SOLVER_ARPACK and 2 * n_modes >= n_free:
        return SOLVER_DENSE, f"{reason}; ARPACK needs 2 * n_modes < free DOF, using dense"
    return requested, reason


def sign_factor(values: np.ndarray, *, rel_tol: float = SIGN_TIE_REL_TOL) -> float:
    """``+1.0`` or ``-1.0`` making the reference component of ``values`` positive.

    The reference is the largest absolute component; components within
    ``rel_tol`` (relative) of that maximum are tied and the lowest index
    among them decides. An all-zero vector returns ``+1.0``.
    """
    magnitudes = np.abs(np.asarray(values, dtype=float).ravel())
    if magnitudes.size == 0:
        return 1.0
    largest = float(magnitudes.max())
    if largest == 0.0 or not np.isfinite(largest):
        return 1.0
    tied = np.flatnonzero(magnitudes >= largest * (1.0 - rel_tol))
    reference = float(np.asarray(values, dtype=float).ravel()[tied[0]])
    return -1.0 if reference < 0.0 else 1.0


def normalize_mode_sign(
    shape: dict[int, np.ndarray], *, rel_tol: float = SIGN_TIE_REL_TOL
) -> dict[int, np.ndarray]:
    """Return ``shape`` (node id to DOF vector) with a deterministic sign.

    Components are ordered by node id, then DOF, and :func:`sign_factor`
    decides the sign for the whole mode. The input is not modified.
    """
    node_ids = sorted(shape)
    if not node_ids:
        return {}
    flat = np.concatenate([np.asarray(shape[nid], dtype=float).ravel() for nid in node_ids])
    factor = sign_factor(flat, rel_tol=rel_tol)
    return {nid: np.asarray(shape[nid], dtype=float) * factor for nid in node_ids}


def degenerate_groups(
    eigenvalues: np.ndarray | list[float], *, rel_tol: float = DEGENERATE_EIGENVALUE_REL_TOL
) -> list[list[int]]:
    """Groups of 0-based mode positions whose consecutive eigenvalues agree within ``rel_tol``."""
    values = np.asarray(eigenvalues, dtype=float).ravel()
    groups: list[list[int]] = []
    for i, value in enumerate(values):
        if groups:
            previous = values[groups[-1][-1]]
            scale = max(abs(previous), abs(value))
            if scale == 0.0 or abs(value - previous) <= rel_tol * scale:
                groups[-1].append(i)
                continue
        groups.append([i])
    return groups


def orthogonalize_degenerate_modes(
    eigenvalues: np.ndarray | list[float],
    mode_shapes: dict[int, dict[int, np.ndarray]],
    node_mass: dict[int, np.ndarray],
    *,
    rel_tol: float = DEGENERATE_EIGENVALUE_REL_TOL,
) -> dict[int, dict[int, np.ndarray]]:
    """Return ``mode_shapes`` with every degenerate group made mass-orthogonal.

    ``mode_shapes`` is 1-indexed (mode number to node id to DOF vector);
    ``node_mass`` maps node id to the lumped mass vector over the same DOF.
    Inside a group, Gram-Schmidt in the mass metric keeps the first vector
    and removes from every later one its mass projection on the vectors
    before it; scales are kept, so an outside caller sees the same
    magnitude. Modes outside a degenerate group, and vectors without mass
    (zero mass norm), are returned unchanged. The input is not modified.
    """
    node_ids = sorted(next(iter(mode_shapes.values()), {}))
    if not node_ids:
        return {m: dict(v) for m, v in mode_shapes.items()}
    mass = np.concatenate([np.asarray(node_mass[nid], dtype=float).ravel() for nid in node_ids])
    sizes = [np.asarray(mode_shapes[next(iter(mode_shapes))][nid]).size for nid in node_ids]
    bounds = np.cumsum([0, *sizes])

    def flatten(shape: dict[int, np.ndarray]) -> np.ndarray:
        return np.concatenate([np.asarray(shape[nid], dtype=float).ravel() for nid in node_ids])

    def unflatten(flat: np.ndarray) -> dict[int, np.ndarray]:
        return {nid: flat[bounds[k] : bounds[k + 1]].copy() for k, nid in enumerate(node_ids)}

    numbers = sorted(mode_shapes)
    out: dict[int, dict[int, np.ndarray]] = {
        m: {nid: np.asarray(v, dtype=float).copy() for nid, v in mode_shapes[m].items()}
        for m in numbers
    }
    for group in degenerate_groups(eigenvalues, rel_tol=rel_tol):
        if len(group) < 2:
            continue
        kept: list[np.ndarray] = []
        for position in group:
            mode = numbers[position]
            vector = flatten(out[mode])
            for basis in kept:
                vector = vector - ((basis * mass) @ vector) / ((basis * mass) @ basis) * basis
            norm = (vector * mass) @ vector
            if norm > 0.0:
                kept.append(vector)
                out[mode] = unflatten(vector)
    return out
