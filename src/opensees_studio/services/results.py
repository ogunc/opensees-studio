"""Analysis result containers.

Returned by ``OpenSeesRunner.run()``. These are plain dataclasses with
NumPy arrays — Pydantic is intentionally avoided here because results
are produced in bulk, never validated, and never persisted as JSON
(time-history series go to HDF5).

Three result kinds, one per analysis case kind. They share no base
class; consumers dispatch on ``isinstance`` (or on a separate ``kind``
attribute). Avoid premature abstraction — these are leaf data, not a
type hierarchy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class StaticResults:
    """Outputs of a static analysis.

    For multi-step (pushover) runs, the *_history arrays carry one row
    per step; for a single-step run, they have one row.
    """

    case_id: int
    case_name: str
    n_steps: int
    node_disp: dict[int, np.ndarray] = field(default_factory=dict)
    """node_id → array of shape (n_steps, ndf), values in project units."""
    node_reaction: dict[int, np.ndarray] = field(default_factory=dict)
    """node_id → array of shape (n_steps, ndf), reaction forces."""
    element_forces: dict[int, np.ndarray] = field(default_factory=dict)
    """element_id → array of shape (n_steps, n_force_components)."""

    def disp(self, node_id: int, dof: int, step: int = -1) -> float:
        """Convenience: scalar displacement at ``node_id``/``dof``/``step``."""
        return float(self.node_disp[node_id][step, dof - 1])


@dataclass
class ModalResults:
    """Outputs of an eigenvalue analysis."""

    case_id: int
    case_name: str
    eigenvalues: np.ndarray
    """Shape (n_modes,). Units: rad²/s² (OpenSees convention)."""
    mode_shapes: dict[int, dict[int, np.ndarray]] = field(default_factory=dict)
    """mode_number (1-indexed) → node_id → ndf-vector."""

    @property
    def angular_frequencies(self) -> np.ndarray:
        """Shape (n_modes,). Units: rad/s."""
        return np.sqrt(np.abs(self.eigenvalues))

    @property
    def frequencies(self) -> np.ndarray:
        """Shape (n_modes,). Units: Hz."""
        return self.angular_frequencies / (2.0 * np.pi)

    @property
    def periods(self) -> np.ndarray:
        """Shape (n_modes,). Units: s."""
        omega = self.angular_frequencies
        # Avoid divide-by-zero for rigid-body modes.
        return np.where(omega > 0, 2.0 * np.pi / omega, np.inf)


@dataclass
class TransientResults:
    """Outputs of a time-history analysis.

    Time-history series live in an HDF5 file, not in memory. Use the
    accessor methods to pull what you need into NumPy.
    """

    case_id: int
    case_name: str
    h5_path: Path
    n_steps: int
    dt: float

    def time(self) -> np.ndarray:
        """Time vector of shape (n_steps,)."""
        import h5py

        with h5py.File(self.h5_path, "r") as f:
            return f["time"][:]  # type: ignore[index]

    def node_disp_history(self, node_id: int) -> np.ndarray:
        """Return shape-(n_steps, ndf) displacement history for ``node_id``."""
        return self._node_history(node_id, "disp")

    def node_vel_history(self, node_id: int) -> np.ndarray:
        """Return shape-(n_steps, ndf) velocity history for ``node_id``."""
        return self._node_history(node_id, "vel")

    def node_accel_history(self, node_id: int) -> np.ndarray:
        """Return shape-(n_steps, ndf) acceleration history for ``node_id``."""
        return self._node_history(node_id, "accel")

    def _node_history(self, node_id: int, kind: str) -> np.ndarray:
        import h5py

        with h5py.File(self.h5_path, "r") as f:
            key = f"nodes/{node_id}/{kind}"
            if key not in f:
                raise KeyError(
                    f"No '{kind}' history recorded for node {node_id}. "
                    f"Re-run the analysis with the current OpenSeesRunner.",
                )
            return f[key][:]  # type: ignore[index]

    def element_force_history(self, element_id: int) -> np.ndarray:
        """Return shape-(n_steps, n_force_components) force history."""
        import h5py

        with h5py.File(self.h5_path, "r") as f:
            return f[f"elements/{element_id}/forces"][:]  # type: ignore[index]
