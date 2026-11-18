"""Analysis result containers.

Returned by ``OpenSeesRunner.run()``. These are plain dataclasses with
NumPy arrays — Pydantic is intentionally avoided here because results
are produced in bulk, never validated, and never persisted as JSON
(time-history series go to HDF5).

One result kind per analysis case kind. They share no base
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
    element_stresses: dict[int, np.ndarray] = field(default_factory=dict)
    """element_id → shape (n_steps, 8) section stress resultants of a shell.

    In the order OpenSees reports them, averaged over the element's gauss
    points: ``N11, N22, N12`` (membrane, force per unit length), ``M11, M22,
    M12`` (bending, moment per unit length) and ``V13, V23`` (transverse shear,
    force per unit length), in the element's local frame. Empty for element
    types that do not report them (bars, trusses, zero-length).

    A model that reports no resultants at all (bars, or a case whose element
    types have no section response) leaves this empty; an element that does
    report them always does, whatever the solution algorithm — the runner reads
    the response after ``ops.reactions()``, which is what makes OpenSees
    materialise the section state of a `Linear` solve.
    """
    storey_shear: dict[int, np.ndarray] = field(default_factory=dict)
    """storey_id → shape (n_steps, ndm) storey shear: the global force the members
    cut just above the level below the storey carry (see
    :mod:`core.storey_results`). Empty when the project defines no storeys."""
    section_cut_forces: dict[int, np.ndarray] = field(default_factory=dict)
    """section_cut_id → shape (n_steps, 6) global resultant (Fx, Fy, Fz, Mx, My, Mz)
    of the cut (:mod:`core.section_cuts`). Empty when the project defines none."""

    def disp(self, node_id: int, dof: int, step: int = -1) -> float:
        """Convenience: scalar displacement at ``node_id``/``dof``/``step``."""
        return float(self.node_disp[node_id][step, dof - 1])


@dataclass
class PushoverResults:
    """Outputs of a monotonic displacement-controlled pushover.

    ``control_disp`` and ``base_shear`` arrays are paired step-by-step
    and ready to plot as an X-Y curve. Per-node displacement history is
    also stored so users can sanity-check drifts at other floors.
    """

    case_id: int
    case_name: str
    n_steps: int
    control_node: int
    control_dof: int
    control_disp: np.ndarray  # shape (n_steps + 1,), includes t=0
    base_shear: np.ndarray  # shape (n_steps + 1,), signed
    node_disp: dict[int, np.ndarray] = field(default_factory=dict)
    """node_id → shape (n_steps + 1, ndf) displacement history."""
    element_forces: dict[int, np.ndarray] = field(default_factory=dict)
    """element_id → shape (n_steps + 1, n_components) local-force history."""
    element_stresses: dict[int, np.ndarray] = field(default_factory=dict)
    """element_id → shape (n_steps + 1, 8) shell stress resultants, as in
    :attr:`StaticResults.element_stresses`."""


@dataclass
class ModalResults:
    """Outputs of an eigenvalue analysis."""

    case_id: int
    case_name: str
    eigenvalues: np.ndarray
    """Shape (n_modes,). Units: rad²/s² (OpenSees convention)."""
    mode_shapes: dict[int, dict[int, np.ndarray]] = field(default_factory=dict)
    """mode_number (1-indexed) → node_id → ndf-vector, sign-normalized (largest absolute
    component positive, ties within 1e-9 broken by the lowest DOF index)."""
    solver: str = ""
    """Eigen solver actually used (``fullGenLapack`` or ``genBandArpack``)."""
    n_free_dof: int = 0
    """Unrestrained nodal DOF count that drove the solver routing."""

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
    """Steps actually completed; every history array has this many rows."""
    dt: float
    n_steps_requested: int
    """Steps the case asked for (``TransientCase.n_steps``)."""

    @property
    def early_stop(self) -> bool:
        """True when the run stopped before the requested number of steps."""
        return self.n_steps < self.n_steps_requested

    def steps_summary(self) -> str:
        """Step count for titles and labels; names an early stop when there is one."""
        if self.early_stop:
            return f"{self.n_steps} of {self.n_steps_requested} steps, stopped early"
        return f"{self.n_steps} steps"

    def time(self) -> np.ndarray:
        """Time vector of shape (n_steps,)."""
        import h5py

        with h5py.File(self.h5_path, "r") as f:
            return f["time"][:]

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
            return f[key][:]

    def element_force_history(self, element_id: int) -> np.ndarray:
        """Return shape-(n_steps, n_force_components) force history."""
        import h5py

        with h5py.File(self.h5_path, "r") as f:
            return f[f"elements/{element_id}/forces"][:]


@dataclass
class ResponseSpectrumResults:
    """Outputs of a response-spectrum analysis (modal combination).

    All values are PEAK responses (positive by definition — SRSS/CQC
    sign is lost in the combination). Per-mode metadata is preserved
    so users can inspect modal participation. Reactions, element forces and
    shell stress resultants are the modal combination of the response to each
    mode's equivalent static load; a result stored before they existed has
    them empty.
    """

    case_id: int
    case_name: str
    direction: int
    combination: str  # "SRSS" or "CQC"
    combined_disp: dict[int, np.ndarray] = field(default_factory=dict)
    """node_id → 3-vector of peak combined translational displacements."""
    modes: list = field(default_factory=list)
    """List of ModeContribution; per-mode period, Γ, M_eff, Sa(T), …"""
    solver: str = ""
    """Eigen solver the underlying modal analysis actually used."""
    node_reaction: dict[int, np.ndarray] = field(default_factory=dict)
    """node_id → peak combined reaction (one value per DOF)."""
    element_forces: dict[int, np.ndarray] = field(default_factory=dict)
    """element_id → peak combined ``localForce`` (a positive magnitude per component)."""
    element_stresses: dict[int, np.ndarray] = field(default_factory=dict)
    """element_id → peak combined shell stress resultants."""
    damping_ratio: float | None = None
    """Damping the CQC correlation used (None for SRSS)."""
    warnings: list[str] = field(default_factory=list)
    """Closely spaced modes under SRSS, damping substitutions."""


@dataclass
class InfluenceLineResults:
    """Every response of a unit load walked along a path (one row per stop).

    ``node_disp``, ``node_reaction`` and ``element_forces`` have the layout of
    :class:`StaticResults` with the step axis replaced by the stop: row ``k`` is
    the response with the load at stop ``k``. ``distances`` is each stop's
    distance along the path, ``element_ids`` / ``fractions`` where it is.
    A column of any of them is an influence line.
    """

    case_id: int
    case_name: str
    distances: np.ndarray
    element_ids: np.ndarray
    fractions: np.ndarray
    load: float = -1.0
    direction: str = "Z"
    node_disp: dict[int, np.ndarray] = field(default_factory=dict)
    node_reaction: dict[int, np.ndarray] = field(default_factory=dict)
    element_forces: dict[int, np.ndarray] = field(default_factory=dict)

    @property
    def n_steps(self) -> int:
        return int(self.distances.size)


@dataclass
class CombinationResults:
    """A load combination evaluated from stored case results (no solver run).

    ``max`` and ``min`` are ordinary one-step :class:`StaticResults`, so every
    static view (deformed shape, force diagram, shell contours, tables) can show
    either bound. A single-valued combination (Linear Add of static cases) has
    the same numbers in both.

    Element forces are bounded as *internal* forces, the sign a force diagram
    draws (OpenSees ``localForce`` with the end-j half reversed): the diagram of
    ``max`` is the upper envelope, that of ``min`` the lower one. The tables
    turn them back into per-component ``localForce`` bounds.
    """

    combination_id: int
    combination_name: str
    combination_type: str
    """One of ``core.combinations.COMBINATION_TYPES``."""
    max: StaticResults
    min: StaticResults
    single_valued: bool
    case_ids: list[int] = field(default_factory=list)
    """Analysis cases whose results went in, nested combinations included."""
    missing_fields: list[str] = field(default_factory=list)
    """Result fields left out because some included case does not provide them."""
    warnings: list[str] = field(default_factory=list)

    @property
    def case_id(self) -> int:
        """The combination id (a result title reads ``#id`` like a case's)."""
        return self.combination_id

    @property
    def case_name(self) -> str:
        return self.combination_name

    def bound(self, which: str) -> StaticResults:
        """``"max"`` or ``"min"``."""
        if which not in ("max", "min"):
            raise ValueError(f"Unknown bound {which!r}: use 'max' or 'min'.")
        return self.max if which == "max" else self.min


def eigen_solver_note(results: object) -> str | None:
    """Run log line naming the eigen solver a modal or spectrum result used, else ``None``."""
    from opensees_studio.core.modal import dense_eigen_max_free_dof

    if isinstance(results, ModalResults) and results.solver:
        return (
            f"Eigen solver: {results.solver} ({results.n_free_dof} free DOF, "
            f"dense at or below {dense_eigen_max_free_dof()})."
        )
    if isinstance(results, ResponseSpectrumResults) and results.solver:
        return f"Eigen solver: {results.solver}."
    return None
