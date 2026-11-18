"""Static stability check: is the model's stiffness matrix singular, and where?

The model is built exactly as an analysis would build it (:class:`OpenSeesRunner`
``build``). The initial-state tangent stiffness ``K`` is captured as a sparse
CSR matrix through OpenSees' ``PythonSparse`` system when the engine exposes it;
the dense ``FullGeneral``/``printA`` route remains a small-model fallback. The
dense route is never used for a large model.

A zero eigenvalue of ``K`` is a **mechanism**, a motion of the free DOFs that
costs no strain energy. A negative eigenvalue is negative stiffness; a very
small positive eigenvalue is reported as ill-conditioning, not as a mechanism.
The report keeps the physical state, the numerical method and what was actually
proved separate: a search that stops after a lower bound does not claim an exact
mechanism count.

The check is for the **initial state** of the model, not a buckling analysis and
not a guarantee for a nonlinear history. The eigenvalue vectors are expressed in
the physical free-DOF space; the report names the node and global DOF of their
largest components.

This module calls OpenSees: run it in the analysis child process
(``python -m opensees_studio.run --check-stability``), never in the GUI.
"""

from __future__ import annotations

import contextlib
import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np

from opensees_studio.core import Project
from opensees_studio.core.combinations import model_fingerprint
from opensees_studio.core.diaphragms import IN_PLANE_SLOTS, constrained_node_ids
from opensees_studio.core.plane import dof_labels, dof_signs, to_solver_coords

Completion = Literal["complete", "partial", "cancelled", "unsupported", "error"]
Classification = Literal[
    "no_mechanisms",
    "mechanism",
    "negative_stiffness",
    "ill_conditioned",
    "indeterminate",
    "no_free_equations",
]

#: Up to this many equations the matrix is small enough for the dense reference
#: (`n × n` float64, about 12 MB at 1 200 equations). Large models never take
#: this route.
DENSE_MAX_EQUATIONS = 1_200

MAX_MECHANISMS = 6
"""Mechanisms reported in full; a model with more says how many were found."""

MAX_MOVERS = 8
"""Node DOFs listed per mechanism (the largest components)."""

SHOWN_FRACTION = 0.2
"""A DOF is listed when it moves at least this fraction of the largest motion."""

RELATIVE_TOLERANCE = 1e-10
"""An eigenvalue below this fraction of the largest one counts as zero."""

NEGATIVE_TOLERANCE = 1e-10
"""An eigenvalue below minus this fraction of the largest one is negative stiffness."""

ILL_CONDITIONED_RATIO = 1e-10
"""A positive eigenvalue below this fraction of the largest is ill-conditioned."""

RESIDUAL_TOLERANCE = 1e-8
"""Largest accepted normalized residual ``||A v - lambda v||``."""

SPARSE_SEARCH_MODES = MAX_MECHANISMS + 2
"""Eigenpairs requested from ARPACK in the sparse route."""

SPARSE_MAX_ITERATIONS = 5_000


@dataclass
class Mover:
    """One node DOF taking part in a mechanism."""

    node: int
    dof: str
    amplitude: float
    """Signed share of the mechanism's largest component (-1 .. 1)."""


@dataclass
class Mechanism:
    """A zero-energy motion of the structure."""

    movers: list[Mover]
    singular_value: float = 0.0
    """Relative singular value, kept for reports written by the dense SVD route."""
    eigenvalue: float | None = None
    """Signed eigenvalue of the scaled matrix, when the method computed one."""
    residual: float | None = None
    """Normalized residual of the accepted eigenpair."""
    kind: str = "mechanism"

    def describe(self) -> str:
        parts = [f"N{m.node} {m.dof} ({m.amplitude:+.2f})" for m in self.movers]
        return ", ".join(parts)


@dataclass
class StabilityReport:
    """What the check found; ``stable`` only when the check is complete."""

    n_equations: int
    rank: int | None = None
    mechanisms: list[Mechanism] = field(default_factory=list)
    n_mechanisms: int = 0
    uncovered: list[str] = field(default_factory=list)
    """Free DOFs no element stiffens (the runner's own pre-run check)."""
    condition: float | None = 0.0
    """Largest over smallest nonzero absolute eigenvalue; absent for sparse searches."""
    completion: Completion = "complete"
    classification: Classification = "no_mechanisms"
    analysis_state: str = "initial"
    nnz: int = 0
    method: str = "dense_eigh"
    backend: str = "numpy"
    versions: dict[str, str] = field(default_factory=dict)
    scaling: dict[str, Any] = field(default_factory=dict)
    tolerances: dict[str, float] = field(default_factory=dict)
    count_kind: str = "exact"
    warnings: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    timings: dict[str, float] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    model_fingerprint: str = ""

    @property
    def stable(self) -> bool:
        """True only for a complete, conclusive check with no mechanism.

        A fully restrained model (no free equations) is stable. Partial,
        unsupported, cancelled and error reports are never stable, even when
        no mechanism has been found so far.
        """
        if self.completion != "complete":
            return False
        if self.classification not in {"no_mechanisms", "no_free_equations"}:
            return False
        if self.n_mechanisms or self.uncovered:
            return False
        return not (self.rank is not None and self.n_equations and self.rank != self.n_equations)

    @property
    def nodes(self) -> list[int]:
        """Every node a mechanism moves, for selecting them in the view."""
        out: list[int] = []
        for mech in self.mechanisms:
            for mover in mech.movers:
                if mover.node not in out:
                    out.append(mover.node)
        return out

    def summary(self) -> str:
        """A few lines for the log and the result dialog."""
        if self.completion != "complete":
            incomplete_lines = [
                f"The stability check is {self.completion}: "
                f"{self.failure_reason or self.classification.replace('_', ' ')}."
            ]
            if self.n_mechanisms:
                incomplete_lines.append(
                    f"It found at least {self.n_mechanisms} mechanism(s) before stopping."
                )
                for k, mech in enumerate(self.mechanisms, start=1):
                    incomplete_lines.append(f"  {k}. moves {mech.describe()}")
            return "\n".join(incomplete_lines)
        if self.classification == "no_free_equations":
            text = "The model is fully restrained: there are no free DOFs to check."
            if self.warnings:
                text += "\n" + "\n".join(f"  - {warning}" for warning in self.warnings)
            return text
        if self.classification == "no_mechanisms" and self.stable:
            text = (
                f"The model is statically stable: the stiffness matrix of its "
                f"{self.n_equations} free DOF(s) has full rank."
            )
            if self.warnings:
                text += "\n" + "\n".join(f"  - {warning}" for warning in self.warnings)
            return text

        lines: list[str] = []
        if self.uncovered:
            lines.append("Free DOFs that no element stiffens:")
            lines += [f"  - {text}" for text in self.uncovered]
        if self.classification == "negative_stiffness":
            lines.append(
                "The stiffness matrix has negative eigenvalues: the initial state has "
                "negative stiffness (this is not a mechanism count)."
            )
        if self.classification == "ill_conditioned":
            lines.append(
                "No mechanism was found, but the stiffness matrix is ill-conditioned; "
                "interpret the result with care."
            )
        if self.n_mechanisms:
            rank = (
                f"rank {self.rank}"
                if self.rank is not None
                else "a rank that is only known as a lower bound"
            )
            lines.append(
                f"The structure has {self.n_mechanisms} mechanism(s): the stiffness matrix "
                f"of its {self.n_equations} free DOF(s) has {rank}."
            )
            for k, mech in enumerate(self.mechanisms, start=1):
                lines.append(f"  {k}. moves {mech.describe()}")
            if self.n_mechanisms > len(self.mechanisms):
                lines.append(f"  … and {self.n_mechanisms - len(self.mechanisms)} more.")
            lines.append(
                "Add supports, bracing or members that stop these motions, or restrain "
                "the DOFs that nothing can carry."
            )
        if self.warnings:
            lines += [f"  - {text}" for text in self.warnings]
        return "\n".join(lines) if lines else "The stability check found no mechanism."

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StabilityReport:
        mechanisms = [
            Mechanism(
                movers=[Mover(**m) for m in mech.get("movers", [])],
                singular_value=float(mech.get("singular_value", 0.0) or 0.0),
                eigenvalue=(None if mech.get("eigenvalue") is None else float(mech["eigenvalue"])),
                residual=None if mech.get("residual") is None else float(mech["residual"]),
                kind=str(mech.get("kind", "mechanism")),
            )
            for mech in data.get("mechanisms", [])
        ]
        n_mechanisms = int(data.get("n_mechanisms", len(mechanisms)))
        classification = str(
            data.get(
                "classification",
                "mechanism" if n_mechanisms else "no_mechanisms",
            )
        )
        rank_value = data.get("rank")
        return cls(
            n_equations=int(data.get("n_equations", 0)),
            rank=None if rank_value is None else int(rank_value),
            mechanisms=mechanisms,
            n_mechanisms=n_mechanisms,
            uncovered=[str(t) for t in data.get("uncovered", [])],
            condition=(
                None
                if data.get("condition") is None and data.get("condition_estimate") is None
                else float(data.get("condition", data.get("condition_estimate", 0.0)))
            ),
            completion=str(data.get("completion", "complete")),  # type: ignore[arg-type]
            classification=classification,  # type: ignore[arg-type]
            analysis_state=str(data.get("analysis_state", "initial")),
            nnz=int(data.get("nnz", 0)),
            method=str(data.get("method", "dense_svd")),
            backend=str(data.get("backend", "numpy")),
            versions={str(k): str(v) for k, v in dict(data.get("versions", {})).items()},
            scaling=dict(data.get("scaling", {})),
            tolerances={str(k): float(v) for k, v in dict(data.get("tolerances", {})).items()},
            count_kind=str(data.get("count_kind", "exact")),
            warnings=[str(t) for t in data.get("warnings", [])],
            failure_reason=(
                None if data.get("failure_reason") is None else str(data["failure_reason"])
            ),
            timings={str(k): float(v) for k, v in dict(data.get("timings", {})).items()},
            memory=dict(data.get("memory", {})),
            model_fingerprint=str(data.get("model_fingerprint", "")),
        )


def _free_dof_upper_bound(project: Project) -> int:
    """A conservative upper bound on the independent equations, before numbering."""
    return max(0, len(project.nodes) * project.ndf)


def _connectivity_components(project: Project) -> list[tuple[list[int], bool]]:
    """Connected node groups and whether each has a restraint or grounded spring."""
    node_ids = {node.id for node in project.nodes}
    if not node_ids:
        return []
    parent = {nid: nid for nid in node_ids}

    def find(nid: int) -> int:
        while parent[nid] != nid:
            parent[nid] = parent[parent[nid]]
            nid = parent[nid]
        return nid

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for element in project.elements:
        ids = [nid for nid in element.nodes if nid in node_ids]
        for nid in ids[1:]:
            union(ids[0], nid)
    for mp in project.mp_constraints:
        if mp.retained_node in node_ids and mp.constrained_node in node_ids:
            union(mp.retained_node, mp.constrained_node)
    for link in project.rigid_links:
        if link.retained_node in node_ids and link.constrained_node in node_ids:
            union(link.retained_node, link.constrained_node)
    for diaphragm in project.diaphragms:
        if diaphragm.retained_node not in node_ids:
            continue
        for nid in constrained_node_ids(project, diaphragm):
            if nid in node_ids:
                union(diaphragm.retained_node, nid)

    grounded = {
        node.id
        for node in project.nodes
        if any(node.restraint) or any(value > 0.0 for value in node.spring)
    }
    components: dict[int, list[int]] = {}
    for nid in node_ids:
        components.setdefault(find(nid), []).append(nid)
    return [(sorted(nodes), any(nid in grounded for nid in nodes)) for nodes in components.values()]


def _connectivity_warnings(project: Project) -> list[str]:
    """Warn about components with no support/grounded spring, without judging stability.

    The graph is only a precheck: two disconnected structures can each be stable,
    and a coincident-node isolator is a deliberate connection (not a merged node).
    """
    warnings: list[str] = []
    for nodes, has_ground in _connectivity_components(project):
        if has_ground:
            continue
        shown = ", ".join(f"N{nid}" for nid in nodes[:6])
        if len(nodes) > 6:
            shown += f", … ({len(nodes)} nodes)"
        warnings.append(
            f"Component {shown} has no restraint or grounded spring; verify it is not a "
            "rigid-body mechanism."
        )
    return warnings


def _equation_map(ops: Any, runner: Any, project: Project) -> dict[int, tuple[int, str]]:
    """Map each independent equation to its physical node and global DOF."""
    labels = dof_labels(project.ndm, project.ndf)
    frame_plan = getattr(runner, "_frame_plan", None)
    joint_of = {extra.tag: extra.joint for extra in getattr(frame_plan, "nodes", [])}
    equation: dict[int, tuple[int, str]] = {}
    for tag in [*(node.id for node in project.nodes), *joint_of]:
        try:
            dofs = ops.nodeDOFs(tag)
        except Exception:
            continue
        for k, eq in enumerate(dofs):
            eq = int(eq)
            if eq >= 0 and k < len(labels) and eq not in equation:
                equation[eq] = (joint_of.get(tag, tag), labels[k])
    return equation


def _csr_index_buffer(buffer: Any, count: int, label: str) -> np.ndarray:
    """Copy an OpenSees CSR integer buffer, accepting int32 or int64 storage."""
    raw = np.frombuffer(buffer, dtype=np.uint8)
    if raw.size == count * 4:
        return np.frombuffer(buffer, dtype=np.int32, count=count).copy()
    if raw.size == count * 8:
        return np.frombuffer(buffer, dtype=np.int64, count=count).copy()
    raise ValueError(
        f"{label} buffer has {raw.size} bytes for {count} entries; "
        "expected 32-bit or 64-bit integers"
    )


class _Capture:
    """PythonSparse solver callback: copy CSR buffers, then refuse the solve."""

    def __init__(self) -> None:
        self.called = False
        self.error: str | None = None
        self.num_eqn = 0
        self.nnz = 0
        self.reported_nnz = 0
        self.values: np.ndarray | None = None
        self.index_ptr: np.ndarray | None = None
        self.indices: np.ndarray | None = None
        self.matrix_status = ""
        self.storage_scheme = ""

    def solve(self, **kwargs: Any) -> int:
        if self.called:
            return -1
        self.called = True
        try:
            self.num_eqn = int(kwargs["num_eqn"])
            self.reported_nnz = int(kwargs["nnz"])
            self.matrix_status = str(kwargs.get("matrix_status", ""))
            self.storage_scheme = str(kwargs.get("storage_scheme", ""))
            if self.storage_scheme != "CSR":
                raise ValueError(f"unexpected storage scheme {self.storage_scheme!r}")
            if self.num_eqn < 0 or self.reported_nnz < 0:
                raise ValueError("negative equation/nonzero count")
            self.values = np.frombuffer(
                kwargs["values"], dtype=np.float64, count=self.reported_nnz
            ).copy()
            self.index_ptr = _csr_index_buffer(
                kwargs["index_ptr"], self.num_eqn + 1, "CSR index pointer"
            )
            self.indices = _csr_index_buffer(
                kwargs["indices"], self.reported_nnz, "CSR column indices"
            )
            if self.index_ptr[0] != 0:
                raise ValueError("CSR index pointer does not start at zero")
            if self.index_ptr[-1] < 0 or self.index_ptr[-1] > self.reported_nnz:
                raise ValueError(
                    "CSR index pointer ends outside the nnz buffer "
                    f"({self.index_ptr[-1]} vs {self.reported_nnz})"
                )
            if np.any(np.diff(self.index_ptr) < 0):
                raise ValueError("CSR index pointer is not monotone")
            # Some OpenSees builds report the allocated nnz while the pointer
            # ends at the stored entries. The pointer is authoritative; use
            # only the corresponding prefix of indices/values.
            self.nnz = int(self.index_ptr[-1])
            if self.nnz:
                active_indices = self.indices[: self.nnz]
                if int(active_indices.min()) < 0 or int(active_indices.max()) >= self.num_eqn:
                    raise ValueError("CSR column index outside the matrix")
                if not np.all(np.isfinite(self.values[: self.nnz])):
                    raise ValueError("non-finite stiffness coefficient")
        except Exception as exc:  # buffer/shape/format problem: no matrix
            self.error = f"PythonSparse callback rejected the matrix: {exc}"
        # Refuse the solve deliberately. The matrix has already been copied.
        return -1


def _configure_analysis(ops: Any) -> None:
    ops.timeSeries("Constant", 999_999)
    ops.pattern("Plain", 999_999, 999_999)
    # Transformation eliminates every MP constraint (equalDOF, rigid links,
    # diaphragms), so K is over the independent DOFs only.
    ops.constraints("Transformation")
    ops.numberer("Plain")
    ops.test("NormDispIncr", 1e-8, 1)
    ops.algorithm("Linear")
    ops.integrator("LoadControl", 0.0)
    ops.analysis("Static")


def _capture_sparse(
    ops: Any, runner: Any, project: Project
) -> tuple[Any | None, dict[int, tuple[int, str]], int, int, str | None, list[str]]:
    """Capture K through PythonSparse; returns ``(matrix, map, n, nnz, error, warnings)``."""
    capture = _Capture()
    try:
        ops.system("PythonSparse", {"solver": capture, "scheme": "CSR"})
    except Exception as exc:
        return None, {}, 0, 0, f"PythonSparse is not available: {exc}", []
    _configure_analysis(ops)
    with contextlib.suppress(Exception):
        ops.analyze(1)  # the callback refuses the solve; K was assembled first
    equation = _equation_map(ops, runner, project)
    if capture.error:
        return None, equation, 0, 0, capture.error, []
    if capture.values is None:
        if not equation:
            return None, equation, 0, 0, None, []
        return (
            None,
            equation,
            0,
            0,
            "PythonSparse did not receive the stiffness matrix.",
            [],
        )
    try:
        import scipy.sparse as sp  # type: ignore[import-untyped]

        matrix = sp.csr_matrix(
            (capture.values, capture.indices, capture.index_ptr),
            shape=(capture.num_eqn, capture.num_eqn),
        )
        matrix.sum_duplicates()
        matrix.sort_indices()
    except Exception as exc:
        return None, equation, capture.num_eqn, capture.nnz, f"scipy CSR failed: {exc}", []
    warnings = []
    if capture.reported_nnz != capture.nnz:
        warnings.append(
            f"PythonSparse reported nnz={capture.reported_nnz}, but the CSR pointer ends at "
            f"{capture.nnz}; the stored entries were used."
        )
    if capture.matrix_status not in {"STRUCTURE_CHANGED", "COEFFICIENTS_CHANGED", "UNCHANGED"}:
        warnings.append(f"PythonSparse reported matrix_status={capture.matrix_status!r}.")
    return matrix, equation, capture.num_eqn, int(matrix.nnz), None, warnings


def _capture_dense(
    ops: Any, runner: Any, project: Project
) -> tuple[np.ndarray | None, dict[int, tuple[int, str]], int, int, str | None]:
    """Small-model fallback: FullGeneral + printA."""
    try:
        ops.system("FullGeneral")
        _configure_analysis(ops)
        with contextlib.suppress(Exception):
            ops.analyze(1)
        values = np.asarray(ops.printA("-ret"), dtype=float)
        n = math.isqrt(values.size)
        matrix = values.reshape(n, n) if n else np.zeros((0, 0))
        equation = _equation_map(ops, runner, project)
        return matrix, equation, n, int(np.count_nonzero(matrix)), None
    except Exception as exc:
        return None, {}, 0, 0, f"dense stiffness extraction failed: {exc}"


def _scale_dense(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Diagonal similarity scaling when every diagonal entry is positive."""
    diagonal = np.diag(matrix)
    if diagonal.size and np.all(np.isfinite(diagonal)) and np.all(diagonal > 0.0):
        scale = 1.0 / np.sqrt(diagonal)
        return (
            matrix * scale[:, None] * scale[None, :],
            scale,
            {
                "kind": "diagonal",
                "applied": True,
                "min": float(scale.min()),
                "max": float(scale.max()),
            },
        )
    return (
        matrix,
        np.ones(matrix.shape[0], dtype=float),
        {
            "kind": "none",
            "applied": False,
            "reason": "the diagonal is not strictly positive",
        },
    )


def _scale_sparse(matrix: Any) -> tuple[Any, np.ndarray, dict[str, Any]]:
    """Diagonal similarity scaling for a CSR matrix."""
    diagonal = np.asarray(matrix.diagonal(), dtype=float)
    if diagonal.size and np.all(np.isfinite(diagonal)) and np.all(diagonal > 0.0):
        import scipy.sparse as sp

        scale = 1.0 / np.sqrt(diagonal)
        return (
            sp.diags(scale) @ matrix @ sp.diags(scale),
            scale,
            {
                "kind": "diagonal",
                "applied": True,
                "min": float(scale.min()),
                "max": float(scale.max()),
            },
        )
    return (
        matrix,
        np.ones(matrix.shape[0], dtype=float),
        {
            "kind": "none",
            "applied": False,
            "reason": "the diagonal is not strictly positive",
        },
    )


class _MotionExpander:
    """Expand an independent-DOF mechanism to the physical node DOFs.

    OpenSees' Transformation handler removes constrained DOFs from the matrix,
    so the eigenvector only contains retained variables. The common constraint
    types are reconstructed here for display and selection: equalDOF copies the
    retained value, a rigid link adds the lever-arm term, and a diaphragm adds
    the in-plane rotation term. The expansion runs after the matrix is captured
    and before ``ops.wipe()``; it never changes the model or the diagnosis.
    """

    def __init__(self, project: Project, ops: Any) -> None:
        self.ndm = project.ndm
        self.ndf = project.ndf
        self.labels = dof_labels(project.ndm, project.ndf)
        self.signs = dof_signs(project.ndm, project.ndf)
        self.coords = {
            node.id: np.asarray(to_solver_coords(node.coords, project.ndm), dtype=float)
            for node in project.nodes
        }
        self.node_dofs: dict[int, tuple[int, ...]] = {}
        for node in project.nodes:
            try:
                self.node_dofs[node.id] = tuple(int(eq) for eq in ops.nodeDOFs(node.id))
            except Exception:
                self.node_dofs[node.id] = (-1,) * project.ndf
        self.equal_dofs = list(project.mp_constraints)
        self.rigid_links = list(project.rigid_links)
        self.diaphragms = [
            (diaphragm, constrained_node_ids(project, diaphragm))
            for diaphragm in project.diaphragms
        ]
        self.unresolved: list[int] = []

    def _base(self, vector: np.ndarray) -> tuple[dict[int, np.ndarray], set[int]]:
        motion = {nid: np.zeros(self.ndf, dtype=float) for nid in self.coords}
        known: set[int] = set()
        for nid, dofs in self.node_dofs.items():
            any_independent = False
            for k, eq in enumerate(dofs):
                if 0 <= eq < vector.size and k < self.ndf:
                    motion[nid][k] = float(vector[eq])
                    any_independent = True
            if any_independent:
                known.add(nid)
        return motion, known

    def _apply_constraints(self, motion: dict[int, np.ndarray], known: set[int]) -> None:
        targets: set[int] = set()
        for mp in self.equal_dofs:
            targets.add(mp.constrained_node)
        for link in self.rigid_links:
            targets.add(link.constrained_node)
        for _diaphragm, nodes in self.diaphragms:
            targets.update(nodes)

        for _ in range(6):
            changed = False
            for mp in self.equal_dofs:
                retained, constrained = mp.retained_node, mp.constrained_node
                if retained not in known or constrained not in motion:
                    continue
                for dof in mp.dofs:
                    slot = dof - 1
                    if 0 <= slot < self.ndf:
                        motion[constrained][slot] = motion[retained][slot]
                if constrained not in known:
                    known.add(constrained)
                    changed = True
            for link in self.rigid_links:
                retained, constrained = link.retained_node, link.constrained_node
                if retained not in known or constrained not in motion:
                    continue
                delta = self.coords[constrained] - self.coords[retained]
                if self.ndm == 2:
                    rotation = float(motion[retained][2]) if self.ndf >= 3 else 0.0
                    motion[constrained][0] = motion[retained][0] - rotation * delta[1]
                    motion[constrained][1] = motion[retained][1] + rotation * delta[0]
                    if link.kind == "beam" and self.ndf >= 3:
                        motion[constrained][2] = rotation
                else:
                    theta = motion[retained][3:6]
                    motion[constrained][0:3] = motion[retained][0:3] + np.cross(theta, delta)
                    if link.kind == "beam":
                        motion[constrained][3:6] = theta
                if constrained not in known:
                    known.add(constrained)
                    changed = True
            for diaphragm, nodes in self.diaphragms:
                retained = diaphragm.retained_node
                if retained not in known or self.ndm != 3 or self.ndf != 6:
                    continue
                slots = IN_PLANE_SLOTS.get(diaphragm.perp_dirn)
                if slots is None:
                    continue
                rotation_slot = slots[2]
                omega = np.zeros(3, dtype=float)
                omega[rotation_slot - 3] = motion[retained][rotation_slot]
                for constrained in nodes:
                    if constrained not in motion:
                        continue
                    delta = self.coords[constrained] - self.coords[retained]
                    displacement = np.cross(omega, delta)
                    for slot in slots[:2]:
                        motion[constrained][slot] = displacement[slot]
                    motion[constrained][rotation_slot] = motion[retained][rotation_slot]
                    if constrained not in known:
                        known.add(constrained)
                        changed = True
            if not changed:
                break
        self.unresolved = sorted(targets - known)

    def movers(self, vector: np.ndarray) -> list[Mover]:
        """The largest physical node-DOF components of ``vector`` (independent DOFs)."""
        motion, known = self._base(np.asarray(vector, dtype=float))
        self._apply_constraints(motion, known)
        values: list[tuple[float, int, str, float]] = []
        for nid, components in motion.items():
            for slot, value in enumerate(components):
                if slot >= len(self.labels):
                    continue
                global_value = float(value) * self.signs[slot]
                if global_value != 0.0:
                    values.append((abs(global_value), nid, self.labels[slot], global_value))
        if not values:
            return []
        peak = max(item[0] for item in values)
        values.sort(reverse=True)
        movers: list[Mover] = []
        for magnitude, nid, label, value in values:
            if magnitude / peak < SHOWN_FRACTION or len(movers) >= MAX_MOVERS:
                break
            movers.append(Mover(node=nid, dof=label, amplitude=round(value / peak, 4)))
        return movers

    def warning(self) -> str | None:
        if not self.unresolved:
            return None
        shown = ", ".join(f"N{nid}" for nid in self.unresolved[:8])
        if len(self.unresolved) > 8:
            shown += f", … ({len(self.unresolved)} nodes)"
        return (
            "Constrained DOFs could not be expanded for "
            f"{shown}; the mechanism selection may omit those nodes."
        )


def _free_body_mechanisms(
    project: Project,
    matrix: Any,
    equation: dict[int, tuple[int, str]],
    expander: _MotionExpander | None,
) -> tuple[list[Mechanism], int]:
    """Numerically verify free-body translations of ungrounded components.

    A graph component with no restraint or grounded spring has at least a
    rigid-body translation. This is a precheck, but each candidate is accepted
    only after ``K v`` has a small relative residual; it is not a claim about
    the rest of the model.
    """
    if expander is None:
        return [], 0
    if hasattr(matrix, "nnz"):
        data_scale = float(np.max(np.abs(matrix.data))) if matrix.nnz else 0.0
    else:
        data_scale = float(np.max(np.abs(matrix))) if getattr(matrix, "size", 0) else 0.0
    if data_scale <= 0.0:
        return [], 0
    mechanisms: list[Mechanism] = []
    count = 0
    for nodes, has_ground in _connectivity_components(project):
        if has_ground:
            continue
        vector = np.zeros(int(matrix.shape[0]), dtype=float)
        chosen: int | None = None
        for slot in (0, 1, 2):
            if slot >= project.ndf:
                continue
            found = False
            for node_id in nodes:
                dofs = expander.node_dofs.get(node_id, ())
                if slot < len(dofs):
                    eq = dofs[slot]
                    if 0 <= eq < vector.size:
                        vector[eq] = 1.0
                        found = True
            if found:
                chosen = slot
                break
        if chosen is None:
            continue
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            continue
        residual = float(np.linalg.norm(matrix @ vector)) / (data_scale * norm)
        if residual > 1e-7:
            continue
        movers = expander.movers(vector)
        if not movers:
            movers = _movers(vector, np.ones(vector.size), equation)
        count += 1
        if len(mechanisms) < MAX_MECHANISMS:
            mechanisms.append(
                Mechanism(
                    movers=movers,
                    singular_value=0.0,
                    eigenvalue=0.0,
                    residual=residual,
                    kind="free_body",
                )
            )
    return mechanisms, count


def _movers(
    vector: np.ndarray,
    scale: np.ndarray,
    equation: dict[int, tuple[int, str]],
    *,
    expander: _MotionExpander | None = None,
) -> list[Mover]:
    physical = np.asarray(vector, dtype=float) * scale
    if expander is not None:
        expanded = expander.movers(physical)
        if expanded:
            return expanded
    peak = float(np.max(np.abs(physical))) if physical.size else 0.0
    if peak == 0.0:
        return []
    order = np.argsort(-np.abs(physical))
    movers: list[Mover] = []
    for eq in order:
        share = float(physical[int(eq)]) / peak
        if abs(share) < SHOWN_FRACTION or len(movers) >= MAX_MOVERS:
            break
        node, dof = equation.get(int(eq), (0, f"eq {int(eq)}"))
        movers.append(Mover(node=node, dof=dof, amplitude=round(share, 4)))
    return movers


def _residual_dense(matrix: np.ndarray, vector: np.ndarray, eigenvalue: float) -> float:
    applied = matrix @ vector
    numerator = float(np.linalg.norm(applied - eigenvalue * vector))
    denominator = (float(np.linalg.norm(matrix, ord=np.inf)) + abs(eigenvalue)) * float(
        np.linalg.norm(vector)
    )
    return numerator / denominator if denominator > 0.0 else numerator


def _residual_sparse(matrix: Any, vector: np.ndarray, eigenvalue: float) -> float:
    applied = matrix @ vector
    numerator = float(np.linalg.norm(applied - eigenvalue * vector))
    scale = float(np.max(np.abs(matrix.data))) if matrix.nnz else 0.0
    denominator = (scale + abs(eigenvalue)) * float(np.linalg.norm(vector))
    return numerator / denominator if denominator > 0.0 else numerator


def _diagnose_dense(
    matrix: np.ndarray,
    equation: dict[int, tuple[int, str]],
    *,
    warnings: list[str],
    expander: _MotionExpander | None = None,
) -> dict[str, Any]:
    n = int(matrix.shape[0])
    if not np.all(np.isfinite(matrix)):
        return {
            "n_equations": n,
            "rank": None,
            "mechanisms": [],
            "n_mechanisms": 0,
            "condition": None,
            "completion": "error",
            "classification": "indeterminate",
            "method": "dense_finite_check",
            "backend": "numpy",
            "count_kind": "estimate",
            "scaling": {"kind": "none", "applied": False},
            "tolerances": {},
            "warnings": [*warnings, "The stiffness matrix contains NaN or Inf."],
            "failure_reason": "non-finite stiffness matrix",
            "memory": {"dense_equivalent_bytes": int(8 * n * n), "estimated": True},
        }
    difference = matrix - matrix.T
    matrix_scale = float(np.max(np.abs(matrix))) if matrix.size else 0.0
    difference_scale = float(np.max(np.abs(difference))) if difference.size else 0.0
    if matrix_scale > 0.0 and difference_scale / matrix_scale > 1e-8:
        return {
            "n_equations": n,
            "rank": None,
            "mechanisms": [],
            "n_mechanisms": 0,
            "condition": None,
            "completion": "unsupported",
            "classification": "indeterminate",
            "method": "dense_symmetry_check",
            "backend": "numpy",
            "count_kind": "estimate",
            "scaling": {"kind": "none", "applied": False},
            "tolerances": {},
            "warnings": [
                *warnings,
                "The assembled stiffness matrix is not symmetric; the symmetric "
                "eigenvalue route does not apply.",
            ],
            "failure_reason": "non-symmetric stiffness matrix",
            "memory": {"dense_equivalent_bytes": int(8 * n * n), "estimated": True},
        }
    scaled, scale, scaling = _scale_dense(matrix)
    eigenvalues, eigenvectors = np.linalg.eigh(scaled)
    n = int(matrix.shape[0])
    matrix_scale = float(np.max(np.abs(scaled))) if scaled.size else 0.0
    largest = max(
        matrix_scale,
        float(np.max(np.abs(eigenvalues))) if eigenvalues.size else 0.0,
    )
    zero_tolerance = RELATIVE_TOLERANCE * largest
    negative_tolerance = NEGATIVE_TOLERANCE * largest
    zero_indices = [i for i, value in enumerate(eigenvalues) if abs(float(value)) <= zero_tolerance]
    negative = [float(value) for value in eigenvalues if float(value) < -negative_tolerance]
    nonzero = [abs(float(value)) for i, value in enumerate(eigenvalues) if i not in zero_indices]
    condition = (max(nonzero) / min(nonzero)) if nonzero else 0.0
    mechanisms: list[Mechanism] = []
    for i in zero_indices[:MAX_MECHANISMS]:
        mechanisms.append(
            Mechanism(
                movers=_movers(eigenvectors[:, i], scale, equation, expander=expander),
                singular_value=0.0,
                eigenvalue=float(eigenvalues[i]),
                residual=_residual_dense(scaled, eigenvectors[:, i], float(eigenvalues[i])),
                kind="mechanism",
            )
        )
    if negative:
        warnings.append(
            f"The scaled stiffness matrix has {len(negative)} negative eigenvalue(s); "
            "the initial state has negative stiffness."
        )
    if negative:
        classification: Classification = "negative_stiffness"
    elif zero_indices:
        classification = "mechanism"
    elif nonzero and min(nonzero) <= ILL_CONDITIONED_RATIO * max(nonzero):
        classification = "ill_conditioned"
    else:
        classification = "no_mechanisms"
    return {
        "n_equations": n,
        "rank": n - len(zero_indices),
        "mechanisms": mechanisms,
        "n_mechanisms": len(zero_indices),
        "condition": condition,
        "completion": "complete",
        "classification": classification,
        "method": "dense_eigh",
        "backend": "numpy",
        "count_kind": "exact",
        "scaling": scaling,
        "tolerances": {
            "relative": RELATIVE_TOLERANCE,
            "negative": NEGATIVE_TOLERANCE,
            "residual": RESIDUAL_TOLERANCE,
        },
        "warnings": warnings,
        "memory": {"dense_equivalent_bytes": int(8 * n * n), "estimated": True},
    }


def _sparse_eigenpairs(
    matrix: Any,
    k: int,
    *,
    which: str,
    sigma: float | None = None,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """``eigsh`` wrapper that returns the converged part, if any, plus a flag."""
    import scipy.sparse.linalg as spla  # type: ignore[import-untyped]
    from scipy.sparse.linalg import ArpackNoConvergence

    kwargs: dict[str, Any] = {
        "k": k,
        "which": which,
        "tol": 1e-10,
        "maxiter": SPARSE_MAX_ITERATIONS,
    }
    if sigma is not None:
        kwargs["sigma"] = sigma
    try:
        eigenvalues, eigenvectors = spla.eigsh(matrix, **kwargs)
        return np.asarray(eigenvalues), np.asarray(eigenvectors), False
    except ArpackNoConvergence as exc:
        if exc.eigenvalues is not None and exc.eigenvectors is not None:
            return np.asarray(exc.eigenvalues), np.asarray(exc.eigenvectors), True
        raise


def _diagnose_sparse(
    matrix: Any,
    equation: dict[int, tuple[int, str]],
    *,
    warnings: list[str],
    expander: _MotionExpander | None = None,
) -> dict[str, Any]:
    n = int(matrix.shape[0])
    if matrix.nnz and not np.all(np.isfinite(matrix.data)):
        return {
            "n_equations": n,
            "rank": None,
            "mechanisms": [],
            "n_mechanisms": 0,
            "condition": None,
            "completion": "error",
            "classification": "indeterminate",
            "method": "sparse_finite_check",
            "backend": "scipy",
            "count_kind": "estimate",
            "scaling": {"kind": "none", "applied": False},
            "tolerances": {},
            "warnings": [*warnings, "The stiffness matrix contains NaN or Inf."],
            "failure_reason": "non-finite stiffness matrix",
            "memory": {
                "csr_bytes": int(12 * matrix.nnz + 4 * (n + 1)),
                "estimated": True,
            },
        }
    # Never silently symmetrize: a non-symmetric K invalidates the symmetric
    # eigenvalue interpretation. Compare the scaled/assembled matrix as given.
    difference = matrix - matrix.T
    matrix_scale = float(np.max(np.abs(matrix.data))) if matrix.nnz else 0.0
    difference_scale = float(np.max(np.abs(difference.data))) if difference.nnz else 0.0
    if matrix_scale > 0.0 and difference_scale / matrix_scale > 1e-8:
        return {
            "n_equations": n,
            "rank": None,
            "mechanisms": [],
            "n_mechanisms": 0,
            "condition": None,
            "completion": "unsupported",
            "classification": "indeterminate",
            "method": "sparse_symmetry_check",
            "backend": "scipy",
            "count_kind": "estimate",
            "scaling": {"kind": "none", "applied": False},
            "tolerances": {},
            "warnings": [
                *warnings,
                "The assembled stiffness matrix is not symmetric; the symmetric "
                "eigenvalue route does not apply.",
            ],
            "failure_reason": "non-symmetric stiffness matrix",
            "memory": {
                "csr_bytes": int(12 * matrix.nnz + 4 * (n + 1)),
                "estimated": True,
            },
        }
    scaled, scale, scaling = _scale_sparse(matrix)
    n_near = min(SPARSE_SEARCH_MODES, max(1, n - 1))
    data_scale = float(np.max(np.abs(matrix.data))) if matrix.nnz else 1.0
    shift = -1e-8 * max(data_scale, 1.0)
    search_warnings: list[str] = []
    near_partial = False
    near_approximate = False
    try:
        near_values, near_vectors, near_partial = _sparse_eigenpairs(
            scaled, n_near, which="LM", sigma=shift
        )
    except Exception:
        # A shift can accidentally coincide with an eigenvalue. Retry farther
        # away, then fall back to the unshifted smallest-magnitude search.
        try:
            near_values, near_vectors, near_partial = _sparse_eigenpairs(
                scaled, n_near, which="LM", sigma=-1e-5 * max(data_scale, 1.0)
            )
            near_approximate = True
            search_warnings.append(
                "The near-zero shift had to be moved; the result is approximate."
            )
        except Exception:
            try:
                near_values, near_vectors, near_partial = _sparse_eigenpairs(
                    scaled, n_near, which="SM"
                )
                near_approximate = True
                search_warnings.append(
                    "The near-zero shift failed; used the unshifted smallest-magnitude search."
                )
            except Exception as exc:
                return {
                    "n_equations": n,
                    "rank": None,
                    "mechanisms": [],
                    "n_mechanisms": 0,
                    "condition": None,
                    "completion": "partial",
                    "classification": "indeterminate",
                    "method": "sparse_eigsh_shift_invert",
                    "backend": "scipy",
                    "count_kind": "estimate",
                    "scaling": scaling,
                    "tolerances": {
                        "relative": RELATIVE_TOLERANCE,
                        "residual": RESIDUAL_TOLERANCE,
                    },
                    "warnings": [
                        *warnings,
                        *search_warnings,
                        f"The sparse eigenvalue search did not converge: {type(exc).__name__}: {exc}",
                    ],
                    "failure_reason": "sparse eigenvalue search did not converge",
                    "memory": {
                        "csr_bytes": int(12 * matrix.nnz + 4 * (n + 1)),
                        "estimated": True,
                    },
                }
    negative_values: list[float] = []
    negative_search_ok = True
    try:
        k_negative = min(MAX_MECHANISMS, max(1, n - 1))
        sa_values, _sa_vectors, sa_partial = _sparse_eigenpairs(scaled, k_negative, which="SA")
        negative_values = [float(value) for value in np.asarray(sa_values) if float(value) < 0.0]
        if sa_partial:
            negative_search_ok = False
            search_warnings.append("The negative-eigenvalue search converged only partially.")
    except Exception as exc:
        negative_search_ok = False
        search_warnings.append(
            f"The negative-eigenvalue search did not converge: {type(exc).__name__}: {exc}"
        )
    order = np.argsort(near_values)
    eigenvalues = np.asarray(near_values)[order]
    eigenvectors = np.asarray(near_vectors)[:, order]
    matrix_scale = float(np.max(np.abs(scaled.data))) if scaled.nnz else 0.0
    largest = max(
        matrix_scale,
        float(np.max(np.abs(eigenvalues))) if eigenvalues.size else 0.0,
    )
    if negative_values:
        largest = max(largest, max(abs(value) for value in negative_values))
    zero_tolerance = RELATIVE_TOLERANCE * largest
    negative_tolerance = NEGATIVE_TOLERANCE * largest
    zero_indices = [i for i, value in enumerate(eigenvalues) if abs(float(value)) <= zero_tolerance]
    negative = [float(value) for value in eigenvalues if float(value) < -negative_tolerance]
    negative += negative_values
    mechanisms: list[Mechanism] = []
    accepted: list[int] = []
    rejected_zero = False
    for i in zero_indices:
        residual = _residual_sparse(scaled, eigenvectors[:, i], float(eigenvalues[i]))
        if residual <= RESIDUAL_TOLERANCE:
            accepted.append(i)
            if len(mechanisms) < MAX_MECHANISMS:
                mechanisms.append(
                    Mechanism(
                        movers=_movers(eigenvectors[:, i], scale, equation, expander=expander),
                        singular_value=0.0,
                        eigenvalue=float(eigenvalues[i]),
                        residual=residual,
                        kind="mechanism",
                    )
                )
    if len(accepted) != len(zero_indices):
        rejected_zero = True
        warnings.append(
            f"{len(zero_indices) - len(accepted)} zero-like eigenpair(s) were rejected "
            f"because their normalized residual exceeded {RESIDUAL_TOLERANCE:g}."
        )
        zero_indices = accepted
    lower_bound = len(zero_indices) == n_near
    if lower_bound:
        search_warnings.append(
            f"Only the {n_near} smallest eigenvalues were searched; the mechanism count is a "
            "lower bound, not an exact count."
        )
    if rejected_zero:
        search_warnings.append(
            "One or more zero-like eigenpairs failed the residual check; the check is partial."
        )
    if near_partial:
        search_warnings.append(
            "The near-zero eigenvalue search converged only partially; use its valid pairs "
            "as a partial result."
        )
    if not negative_search_ok:
        search_warnings.append(
            "The negative-eigenvalue search is incomplete; the classification is partial."
        )
    if negative:
        search_warnings.append(
            f"The scaled stiffness matrix has {len(negative)} negative eigenvalue(s); "
            "the initial state has negative stiffness."
        )
    if negative:
        classification: Classification = "negative_stiffness"
    elif zero_indices:
        classification = "mechanism"
    elif not negative_search_ok or rejected_zero:
        classification = "indeterminate"
    elif (
        zero_tolerance < largest
        and min(abs(float(value)) for value in eigenvalues if abs(float(value)) > zero_tolerance)
        <= ILL_CONDITIONED_RATIO * largest
    ):
        classification = "ill_conditioned"
    else:
        classification = "no_mechanisms"
    completion = (
        "partial"
        if (
            lower_bound
            or rejected_zero
            or near_partial
            or near_approximate
            or not negative_search_ok
        )
        else "complete"
    )
    return {
        "n_equations": n,
        "rank": None if (lower_bound or rejected_zero) else n - len(zero_indices),
        "mechanisms": mechanisms,
        "n_mechanisms": len(zero_indices),
        "condition": None,
        "completion": completion,
        "classification": classification,
        "method": "sparse_eigsh_shift_invert",
        "backend": "scipy",
        "count_kind": "lower_bound" if lower_bound else "estimate",
        "scaling": scaling,
        "tolerances": {
            "relative": RELATIVE_TOLERANCE,
            "negative": NEGATIVE_TOLERANCE,
            "residual": RESIDUAL_TOLERANCE,
        },
        "warnings": [*warnings, *search_warnings],
        "memory": {
            "csr_bytes": int(12 * matrix.nnz + 4 * (n + 1)),
            "dense_equivalent_bytes": int(8 * n * n),
            "estimated": True,
        },
    }


def _notify(progress: Callable[[str, str], None] | None, phase: str, message: str) -> None:
    if progress is None:
        return
    with contextlib.suppress(Exception):
        progress(phase, message)


def _cancelled_report(
    *,
    reason: str,
    n_equations: int,
    nnz: int,
    timestamp: float,
    started: float,
    method: str = "cancelled",
    backend: str = "opensees",
    fingerprint: str = "",
) -> StabilityReport:
    return StabilityReport(
        n_equations=n_equations,
        rank=None,
        completion="cancelled",
        classification="indeterminate",
        nnz=nnz,
        method=method,
        backend=backend,
        count_kind="estimate",
        warnings=[],
        failure_reason=reason,
        timings={"elapsed_ms": (timestamp - started) * 1000.0},
        model_fingerprint=fingerprint,
    )


def check_stability(
    project: Project,
    ops_module: Any | None = None,
    *,
    timeout_s: float | None = None,
    progress: Callable[[str, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> StabilityReport:
    """Build ``project`` in OpenSees and look for mechanisms in its stiffness.

    ``timeout_s`` and ``should_cancel`` are checked between phases; a native
    eigenvalue call cannot be interrupted cooperatively, so the GUI also kills
    its child process at its own hard deadline. The return report then has
    ``completion='cancelled'`` when the service observes it.
    """
    from opensees_studio.services.opensees_runner import OpenSeesRunner

    if ops_module is None:
        import openseespy.opensees as default_ops

        ops_module = default_ops
    started = time.perf_counter()
    deadline = None if timeout_s is None or timeout_s <= 0 else started + timeout_s
    fingerprint = model_fingerprint(project)
    ops = ops_module
    warnings = _connectivity_warnings(project)
    n = 0
    nnz = 0
    extraction_method = "none"
    backend = "opensees"

    def stop_reason() -> str | None:
        if should_cancel is not None:
            with contextlib.suppress(Exception):
                if should_cancel():
                    return "cancelled by user"
        if deadline is not None and time.perf_counter() >= deadline:
            return f"stability time limit of {timeout_s:g} s exceeded"
        return None

    def cancelled() -> StabilityReport:
        return _cancelled_report(
            reason=stop_reason() or "cancelled",
            n_equations=n,
            nnz=nnz,
            timestamp=time.perf_counter(),
            started=started,
            method=extraction_method,
            backend=backend,
            fingerprint=fingerprint,
        )

    try:
        reason = stop_reason()
        if reason:
            return cancelled()
        _notify(progress, "precheck", "Checking connectivity and constrained DOFs.")
        _notify(progress, "build", "Building the OpenSees model.")
        runner = OpenSeesRunner(project, ops_module=ops_module)
        runner.build()
        build_done = time.perf_counter()
        reason = stop_reason()
        if reason:
            return cancelled()
        _notify(progress, "capture", "Capturing the initial stiffness matrix.")
        uncovered = _uncovered_dofs(runner)
        extraction_started = time.perf_counter()
        matrix, equation, n, nnz, extraction_error, capture_warnings = _capture_sparse(
            ops, runner, project
        )
        warnings += capture_warnings
        backend = "PythonSparse"
        extraction_method = "python_sparse_csr"
        reason = stop_reason()
        if reason:
            return cancelled()
        if matrix is None and extraction_error is None and n == 0 and not equation:
            report = StabilityReport(
                n_equations=0,
                rank=0,
                completion="complete",
                classification="no_free_equations",
                uncovered=uncovered,
                warnings=warnings,
                method="none",
                backend="opensees",
                count_kind="exact",
                model_fingerprint=model_fingerprint(project),
                timings={"build_ms": (build_done - started) * 1000.0},
            )
            return report
        if matrix is None:
            upper = _free_dof_upper_bound(project)
            if upper <= DENSE_MAX_EQUATIONS:
                warnings.append(
                    "PythonSparse extraction was unavailable; used the small dense "
                    "fallback (bounded by DENSE_MAX_EQUATIONS)."
                )
                matrix, equation, n, nnz, dense_error = _capture_dense(ops, runner, project)
                backend = "FullGeneral+printA"
                extraction_method = "dense_fullgeneral"
                if dense_error:
                    return StabilityReport(
                        n_equations=upper,
                        rank=None,
                        completion="error",
                        classification="indeterminate",
                        uncovered=uncovered,
                        warnings=warnings,
                        failure_reason=dense_error,
                        method=extraction_method,
                        backend=backend,
                        count_kind="estimate",
                        model_fingerprint=model_fingerprint(project),
                        timings={"build_ms": (build_done - started) * 1000.0},
                    )
            else:
                return StabilityReport(
                    n_equations=upper,
                    rank=None,
                    completion="unsupported",
                    classification="indeterminate",
                    uncovered=uncovered,
                    warnings=warnings,
                    failure_reason=(
                        extraction_error
                        or "PythonSparse is unavailable and the model is too large "
                        f"for the dense fallback ({upper} > {DENSE_MAX_EQUATIONS})."
                    ),
                    method="python_sparse_required",
                    backend="opensees",
                    count_kind="estimate",
                    model_fingerprint=model_fingerprint(project),
                    timings={"build_ms": (build_done - started) * 1000.0},
                )
        if matrix is None:
            raise RuntimeError("No stiffness matrix was captured.")
        extraction_done = time.perf_counter()
        reason = stop_reason()
        if reason:
            return cancelled()
        if n == 0:
            return StabilityReport(
                n_equations=0,
                rank=0,
                completion="complete",
                classification="no_free_equations",
                uncovered=uncovered,
                warnings=warnings,
                method=extraction_method,
                backend=backend,
                count_kind="exact",
                model_fingerprint=model_fingerprint(project),
                timings={
                    "build_ms": (build_done - started) * 1000.0,
                    "extract_ms": (extraction_done - extraction_started) * 1000.0,
                },
            )
        try:
            _notify(progress, "reconstruct", "Expanding constrained DOFs for the report.")
            expander = _MotionExpander(project, ops)
        except Exception as exc:
            expander = None
            warnings.append(f"Constrained-DOF expansion was unavailable: {exc}")
        reason = stop_reason()
        if reason:
            return cancelled()
        _notify(
            progress,
            "diagnose",
            "Searching for mechanisms, negative stiffness and ill-conditioning.",
        )
        free_mechanisms, free_count = _free_body_mechanisms(project, matrix, equation, expander)
        if free_count:
            free_done = time.perf_counter()
            warnings.append(
                "Ungrounded connected components were verified by their rigid-body "
                "translation; the remaining stiffness was not searched in this run."
            )
            return StabilityReport(
                n_equations=n,
                rank=None,
                mechanisms=free_mechanisms,
                n_mechanisms=free_count,
                uncovered=uncovered,
                condition=None,
                completion="partial",
                classification="mechanism",
                analysis_state="initial",
                nnz=nnz,
                method=f"{extraction_method}+free_body_precheck",
                backend=backend,
                versions=_versions(),
                scaling={"kind": "none", "applied": False},
                tolerances={"relative": 1e-7, "residual": 1e-7},
                count_kind="lower_bound",
                warnings=warnings,
                failure_reason=None,
                timings={
                    "build_ms": (build_done - started) * 1000.0,
                    "extract_ms": (extraction_done - extraction_started) * 1000.0,
                    "diagnose_ms": (free_done - extraction_done) * 1000.0,
                },
                memory={
                    "csr_bytes": int(12 * nnz + 4 * (n + 1)),
                    "estimated": True,
                },
                model_fingerprint=fingerprint,
            )
        if n > DENSE_MAX_EQUATIONS:
            try:
                import scipy  # noqa: F401
            except ImportError:
                return StabilityReport(
                    n_equations=n,
                    rank=None,
                    nnz=nnz,
                    completion="unsupported",
                    classification="indeterminate",
                    uncovered=uncovered,
                    warnings=warnings,
                    failure_reason=(
                        "scipy is required for the sparse eigenvalue route on a model "
                        "larger than DENSE_MAX_EQUATIONS."
                    ),
                    method="sparse_eigsh_sa",
                    backend="scipy",
                    count_kind="estimate",
                    model_fingerprint=model_fingerprint(project),
                    timings={
                        "build_ms": (build_done - started) * 1000.0,
                        "extract_ms": (extraction_done - extraction_started) * 1000.0,
                    },
                )
            diagnosis = _diagnose_sparse(matrix, equation, warnings=warnings, expander=expander)
        else:
            dense = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
            diagnosis = _diagnose_dense(dense, equation, warnings=warnings, expander=expander)
        diagnosis_done = time.perf_counter()
        reason = stop_reason()
        if reason:
            return cancelled()
        _notify(progress, "reconstruct", "Preparing the physical mechanism description.")
        if diagnosis["mechanisms"] and expander is not None:
            expansion_warning = expander.warning()
            if expansion_warning:
                diagnosis["warnings"].append(expansion_warning)
        report = StabilityReport(
            n_equations=int(diagnosis["n_equations"]),
            rank=diagnosis["rank"],
            mechanisms=diagnosis["mechanisms"],
            n_mechanisms=int(diagnosis["n_mechanisms"]),
            uncovered=uncovered,
            condition=diagnosis.get("condition"),
            completion=diagnosis["completion"],
            classification=diagnosis["classification"],
            analysis_state="initial",
            nnz=nnz,
            method=f"{extraction_method}+{diagnosis['method']}",
            backend=f"{backend}+{diagnosis['backend']}",
            versions=_versions(),
            scaling=diagnosis["scaling"],
            tolerances=diagnosis["tolerances"],
            count_kind=diagnosis["count_kind"],
            warnings=diagnosis.get("warnings", []),
            failure_reason=diagnosis.get("failure_reason"),
            timings={
                "build_ms": (build_done - started) * 1000.0,
                "extract_ms": (extraction_done - extraction_started) * 1000.0,
                "diagnose_ms": (diagnosis_done - extraction_done) * 1000.0,
            },
            memory=diagnosis.get("memory", {}),
            model_fingerprint=model_fingerprint(project),
        )
        _notify(progress, "done", "Stability check complete.")
        return report
    finally:
        ops.wipe()


def _uncovered_dofs(runner: Any) -> list[str]:
    """The runner's pre-run check, as a list of 'Node n, DOF x: …' lines."""
    try:
        runner._check_dof_coverage()
    except RuntimeError as exc:
        return [line.strip() for line in str(exc).splitlines() if line.strip().startswith("Node ")]
    return []


def _versions() -> dict[str, str]:
    from importlib import metadata

    versions = {"numpy": np.__version__}
    for package in ("scipy", "openseespy"):
        with contextlib.suppress(metadata.PackageNotFoundError):
            versions[package] = metadata.version(package)
    return versions
