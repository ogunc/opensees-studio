"""Review the model before it runs: loose nodes, unconnected members, static instability.

OpenSees does not tell you what is wrong with a model that cannot be solved. A
node nobody connects to, a bar that references a node that was deleted, or a
frame that is missing one support all end the same way: a singular stiffness
matrix, a warning the solver prints and moves past, and displacements that are
the load vector in disguise. This module is the report that comes *before* the
run. It never changes the project; it says what is wrong, where, and — for the
cases a modeller can act on — what to look at.

What it checks, from cheapest to most involved:

* **References and geometry** — an element or an equalDOF constraint pointing at
  a node that does not exist, an element listing the same node twice, a bar or
  frame of zero length, a zero-length element or bearing whose nodes are apart.
* **Loose nodes** — a node no element and no constraint touches. Free, it is a
  singular DOF (*error*); fully restrained, it is only clutter (*warning*).
* **Connectivity** — the model split into parts that nothing links. A part with
  no support at all is a rigid body (*error*); several supported parts are
  usually a node somebody forgot to merge (*warning*, with the pair of nodes
  that sit on top of each other when there is one).
* **Static stability** — whether any group of nodes can move *without deforming
  a single element*. That is the definition of a mechanism, and it is a
  question about kinematics, not about the values of E and A.

Stability is decided on an *idealised* model, on purpose. Each element is
replaced by its independent deformation modes (a truss has one, a frame in 3D
has six, a shell has the eighteen that are not rigid-body motion) with unit
stiffness, and the stiffness matrix is ``K = BᵀB`` over the free DOF. The null
space of ``K`` is the set of mechanisms. Nothing about the real properties
enters, so the answer does not depend on units or on how stiff one member is
next to another, and it needs no OpenSees. The price is that it is a *linear,
small-displacement* answer: a model that is stable only through its
deformation (a cable) or through a gap or a slider is out of its scope.

The checks are written to err on the side of *not* blocking a good model. An
element type the module does not know couples every DOF of its nodes, which can
hide a mechanism but never invents one.
"""

from __future__ import annotations

import math
import os
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from opensees_studio.core.diaphragms import (
    IN_PLANE_SLOTS,
    auto_fixed_slots,
    constrained_node_ids,
)
from opensees_studio.core.duplicates import ZERO_LENGTH_CLASSES, default_tolerance
from opensees_studio.core.geometry.elements import (
    BeamWithHingesElement,
    CorotTrussElement,
    DispBeamColumn,
    ElasticBeamColumn,
    ForceBeamColumn,
    QuadElement,
    ShellDKGTElement,
    ShellMITC4Element,
    TrussElement,
    ZeroLengthElement,
)
from opensees_studio.core.modal import dof_indices
from opensees_studio.core.project import Project
from opensees_studio.core.support_springs import nodal_springs

#: Canonical slot names of the six stored DOF (see ``core.modal.dof_indices``).
DOF_LABELS: tuple[str, ...] = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")

TRUSS_CLASSES = (TrussElement, CorotTrussElement)
FRAME_CLASSES = (ElasticBeamColumn, ForceBeamColumn, DispBeamColumn, BeamWithHingesElement)

#: Free DOF above which the stability check is skipped for one connected part.
#: The test is dense linear algebra, so cost grows with the cube of this number;
#: ``OPENSEES_STUDIO_STABILITY_MAX_DOF`` overrides it.
DEFAULT_MAX_STABILITY_DOF = 3000
MAX_DOF_ENV = "OPENSEES_STUDIO_STABILITY_MAX_DOF"

#: Smallest pivot of the Cholesky factor, on a unit-diagonal ``K``, that proves the
#: part stable without further work. ``K`` is positive semi-definite, so a pivot is
#: never below its smallest eigenvalue and a clean factorisation is a certificate.
STABLE_PIVOT = 1e-10

#: Eigenvalue of the unit-diagonal ``K``, relative to the largest one, below which
#: a motion counts as a mechanism. An exact mechanism sits at rounding level
#: (~1e-15); a long chain of short members that is merely flexible sits well above.
NULL_EIGEN_RATIO = 1e-12

#: A DOF takes part in a mechanism when the projector on the null space has at
#: least this on its diagonal (0 = never moves, 1 = moves freely).
PARTICIPATION = 1e-4

#: Mechanism modes described one by one; a finding with more says how many.
MAX_MODES = 6

#: A node takes part in a mode when it moves at least this share of the largest motion.
MODE_SHARE = 0.05

#: Relative residual below which a mode counts as a rigid-body motion of its nodes.
RIGID_RESIDUAL = 1e-6

#: How many node ids a message lists before it says "and N more".
LISTED_IDS = 8


class Severity(Enum):
    """How much a finding matters to the run."""

    ERROR = "error"
    """The analysis will fail, or return numbers that mean nothing."""
    WARNING = "warning"
    """Probably a mistake, but the model can still be solved."""
    INFO = "info"
    """Something the check could not do, or a fact worth knowing."""


_RANK = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


MechanismKind = str
"""``"rigid_translation"``, ``"rigid_rotation"``, ``"free_rotation"``, ``"free_joint"``,
``"sway"`` or ``"mechanism"`` (a motion of several parts that is none of the above)."""


@dataclass(frozen=True)
class MechanismMode:
    """One free motion of a mechanism, in global DOF slots, and what it is.

    ``motion`` maps a node to its six stored-slot components (``Ux, Uy, Uz, Rx,
    Ry, Rz``; slots the model does not use are zero), scaled so the largest is
    1. The basis is localised (each mode is pinned to a DOF none of the others
    moves), so two independent hinges come out as two modes, not a blend.
    """

    motion: dict[int, tuple[float, ...]]
    kind: MechanismKind
    description: str
    hint: str
    node_ids: tuple[int, ...] = ()
    element_ids: tuple[int, ...] = ()
    """Elements that take part: those the motion carries, or the ones that hold a
    moving group to the rest of the structure without resisting it."""


@dataclass(frozen=True)
class Finding:
    """One thing the check found."""

    severity: Severity
    code: str
    message: str
    node_ids: tuple[int, ...] = ()
    element_ids: tuple[int, ...] = ()
    hint: str = ""
    modes: tuple[MechanismMode, ...] = ()
    """For a mechanism: each independent free motion (at most :data:`MAX_MODES`)."""

    def summary(self) -> str:
        text = f"{self.severity.value.upper()}: {self.message}"
        return f"{text} {self.hint}".rstrip() if self.hint else text


@dataclass(frozen=True)
class ModelCheckReport:
    """What the check found, and how far it got."""

    findings: tuple[Finding, ...] = ()
    node_count: int = 0
    element_count: int = 0
    part_count: int = 0
    mechanism_count: int = 0
    stability_checked: bool = False
    stability_skipped_parts: int = 0
    """Supported parts the stability test left out (over the DOF limit, or switched off)."""

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def infos(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.INFO]

    @property
    def has_errors(self) -> bool:
        return any(f.severity is Severity.ERROR for f in self.findings)

    @property
    def is_clean(self) -> bool:
        """No error and no warning (information alone does not count)."""
        return not any(f.severity in (Severity.ERROR, Severity.WARNING) for f in self.findings)

    @property
    def is_complete(self) -> bool:
        """Every check ran, including stability on every supported part."""
        return self.stability_checked and self.stability_skipped_parts == 0

    def summary(self) -> str:
        errors, warnings = len(self.errors), len(self.warnings)
        skipped = self.stability_skipped_parts
        not_checked = (
            f"stability was not checked for {_plural(skipped, 'part')} of the model"
            if skipped
            else "stability was not checked"
        )
        if errors == 0 and warnings == 0:
            if not self.is_complete:
                return (
                    f"Model check incomplete: {self.node_count} nodes, {self.element_count} "
                    f"elements; {not_checked}. The checks that ran found no problems."
                )
            return (
                f"Model check passed: {self.node_count} nodes, {self.element_count} elements, "
                "no problems found."
            )
        parts = []
        if errors:
            parts.append(f"{errors} error{'s' if errors != 1 else ''}")
        if warnings:
            parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
        text = "Model check: " + ", ".join(parts) + "."
        if skipped:
            text += f" Incomplete: {not_checked}."
        return text


# ──────────────────────────── small helpers ────────────────────────────
def _ids(values: Iterable[int], limit: int = LISTED_IDS) -> str:
    items = sorted(set(values))
    shown = ", ".join(str(i) for i in items[:limit])
    return shown if len(items) <= limit else f"{shown} … and {len(items) - limit} more"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def max_stability_dof() -> int:
    """The per-part DOF limit of the stability test (env override honoured)."""
    raw = os.environ.get(MAX_DOF_ENV)
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return DEFAULT_MAX_STABILITY_DOF


class _UnionFind:
    def __init__(self, items: Iterable[int]) -> None:
        self._parent = {item: item for item in items}

    def find(self, item: int) -> int:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[max(root_a, root_b)] = min(root_a, root_b)


# A row of the compatibility matrix: coefficient per (node id, DOF index).
Row = dict[tuple[int, int], float]


def _rotation_dofs(ndm: int, ndf: int) -> dict[int, int]:
    """Rotation axis (0=x, 1=y, 2=z) → DOF index, for the models that have rotations."""
    if (ndm, ndf) == (2, 3):
        return {2: 2}
    if (ndm, ndf) == (3, 6):
        return {0: 3, 1: 4, 2: 5}
    return {}


#: Nodal DOF index (0-based, within ``ndf``) that each zeroLength material direction
#: acts on, per (ndm, ndf). Directions are not nodal DOF numbers: 1, 2, 3 translate
#: along and 4, 5, 6 rotate about the element's local x, y, z axes, which are the
#: global axes here (the runner writes no ``-orient``). OpenSees projects them onto
#: the nodal DOF (``ZeroLength::setTran1d``), and in 2D it also reads direction 3 as
#: 6, the rotation about z. A direction missing from a row gets no stiffness.
_ZERO_LENGTH_DOF: dict[tuple[int, int], dict[int, int]] = {
    (2, 2): {1: 0, 2: 1},
    (2, 3): {1: 0, 2: 1, 3: 2, 6: 2},
    (3, 3): {1: 0, 2: 1, 3: 2},
    (3, 6): {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5},
}


def zero_length_dof(ndm: int, ndf: int, direction: int) -> int | None:
    """The nodal DOF index a zeroLength ``-dir`` acts on, or ``None`` if it has no stiffness."""
    return _ZERO_LENGTH_DOF.get((ndm, ndf), {}).get(direction)


def _complement_rows(basis: np.ndarray) -> np.ndarray:
    """Rows spanning the orthogonal complement of the columns of ``basis``."""
    _, s, vt = np.linalg.svd(basis.T, full_matrices=True)
    rank = int((s > 1e-10 * s.max()).sum()) if s.size else 0
    return vt[rank:]


def _rigid_body_matrix(points: np.ndarray, ndm: int, ndf: int) -> np.ndarray:
    """Rigid-body motions of an element as columns over its ``nodes × ndf`` DOF."""
    count = len(points)
    centre = np.zeros(3)
    centre[:ndm] = points.mean(axis=0)
    columns: list[np.ndarray] = []
    for axis in range(ndm):
        col = np.zeros(count * ndf)
        for a in range(count):
            col[a * ndf + axis] = 1.0
        columns.append(col)
    axes = [np.array([0.0, 0.0, 1.0])] if ndm == 2 else list(np.eye(3))
    for w in axes:
        col = np.zeros(count * ndf)
        for a in range(count):
            point = np.zeros(3)
            point[:ndm] = points[a]
            u = np.cross(w, point - centre)
            for axis in range(ndm):
                col[a * ndf + axis] = u[axis]
            if ndf == 3 and ndm == 2:
                col[a * ndf + 2] = w[2]
            elif ndf == 6:
                col[a * ndf + 3 : a * ndf + 6] = w
        columns.append(col)
    return np.stack(columns, axis=1)


def _perpendiculars(e: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Two unit vectors that, with ``e``, make an orthonormal triad."""
    helper = np.array([0.0, 0.0, 1.0]) if abs(e[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    a1 = np.cross(e, helper)
    a1 /= np.linalg.norm(a1)
    a2 = np.cross(e, a1)
    return a1, a2


def _frame_rows(
    ids: tuple[int, int], pi: np.ndarray, pj: np.ndarray, ndm: int, ndf: int
) -> list[Row]:
    """Basic deformations of a prismatic frame: axial, torsion, two bending rotations per end."""
    i, j = ids
    d = pj - pi
    length = float(np.linalg.norm(d))
    e = d / length
    rows: list[Row] = []

    def add(row: Row, node: int, dof: int, value: float) -> None:
        row[(node, dof)] = row.get((node, dof), 0.0) + value

    axial: Row = {}
    for axis in range(ndm):
        add(axial, j, axis, e[axis])
        add(axial, i, axis, -e[axis])
    rows.append(axial)

    if ndm == 2:
        n = np.array([-e[1], e[0]])
        for end in (i, j):
            row: Row = {}
            add(row, end, 2, 1.0)
            for axis in range(2):
                add(row, j, axis, -n[axis] / length)
                add(row, i, axis, n[axis] / length)
            rows.append(row)
        return rows

    torsion: Row = {}
    for axis in range(3):
        add(torsion, j, 3 + axis, e[axis])
        add(torsion, i, 3 + axis, -e[axis])
    rows.append(torsion)
    for a in _perpendiculars(e):
        w = np.cross(a, e)  # a·(e × Δu) = (a × e)·Δu
        for end in (i, j):
            row = {}
            for axis in range(3):
                add(row, end, 3 + axis, a[axis])
                add(row, j, axis, -w[axis] / length)
                add(row, i, axis, w[axis] / length)
            rows.append(row)
    return rows


def _identity_rows(ids: tuple[int, ...], dofs: Iterable[int]) -> list[Row]:
    """One stiff spring per DOF between the first node and each of the others."""
    first, *rest = ids
    return [{(other, dof): 1.0, (first, dof): -1.0} for other in rest for dof in dofs]


def _element_rows(
    project: Project, element: Any, points: dict[int, np.ndarray], ndm: int, ndf: int
) -> list[Row]:
    """The deformation modes of one element, as rows over its nodes' DOF."""
    ids = tuple(element.nodes)
    if isinstance(element, TRUSS_CLASSES):
        d = points[ids[1]] - points[ids[0]]
        e = d / np.linalg.norm(d)
        row: Row = {}
        for axis in range(ndm):
            row[(ids[1], axis)] = float(e[axis])
            row[(ids[0], axis)] = float(-e[axis])
        return [row]
    if isinstance(element, FRAME_CLASSES):
        return _frame_rows((ids[0], ids[1]), points[ids[0]], points[ids[1]], ndm, ndf)
    if isinstance(element, (QuadElement, ShellMITC4Element, ShellDKGTElement)):
        pts = np.array([points[n] for n in ids])
        complement = _complement_rows(_rigid_body_matrix(pts, ndm, ndf))
        rows = []
        for vector in complement:
            row = {}
            for a, node in enumerate(ids):
                for dof in range(ndf):
                    value = float(vector[a * ndf + dof])
                    if abs(value) > 1e-14:
                        row[(node, dof)] = value
            if row:
                rows.append(row)
        return rows
    if isinstance(element, ZeroLengthElement):
        acted = {zero_length_dof(ndm, ndf, d) for d in element.dofs}
        return _identity_rows(ids, sorted(dof for dof in acted if dof is not None))
    # Zero-length sections, bearings, and any type this module does not know: a
    # connection that resists every DOF. Over-coupling can hide a mechanism but
    # never reports one that is not there.
    return _identity_rows(ids, range(ndf))


# ──────────────────────────── the check ────────────────────────────
def check_model(
    project: Project,
    *,
    check_stability: bool = True,
    tolerance: float | None = None,
) -> ModelCheckReport:
    """Review ``project`` and report what would stop it from solving.

    Args:
        project: The model. It is never modified.
        check_stability: Run the kinematic stability test (the one costly step).
        tolerance: Distance under which two nodes are the same point. Defaults
            to one part per million of the model's size.
    """
    findings: list[Finding] = []
    ndm, ndf = project.ndm, project.ndf
    tol = default_tolerance(project) if tolerance is None else tolerance

    def report(**extra: Any) -> ModelCheckReport:
        ordered = sorted(findings, key=lambda f: _RANK[f.severity])
        return ModelCheckReport(
            findings=tuple(ordered),
            node_count=len(project.nodes),
            element_count=len(project.elements),
            **extra,
        )

    if not project.nodes:
        findings.append(
            Finding(
                Severity.ERROR,
                "no_nodes",
                "The model has no nodes.",
                hint="Draw or define nodes first.",
            )
        )
        return report()
    if not project.elements:
        findings.append(
            Finding(
                Severity.ERROR,
                "no_elements",
                f"The model has {_plural(len(project.nodes), 'node')} but no elements.",
                node_ids=tuple(n.id for n in project.nodes),
                hint="Nothing connects the nodes: draw frames, trusses or other elements.",
            )
        )
        return report()

    nodes = {n.id: n for n in project.nodes}
    axes, idx = _plane_layout(project, tol)
    points = {n.id: np.array([n.coords[axis] for axis in axes], dtype=float) for n in project.nodes}

    # ── references and geometry ─────────────────────────────────────
    usable: list[Any] = []
    rejected: list[Any] = []
    for el in project.elements:
        label = f"Element {el.id} ({el.type})"
        missing = [n for n in el.nodes if n not in nodes]
        if missing:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "missing_node",
                    f"{label} refers to missing node{'s' if len(missing) > 1 else ''} {_ids(missing)}.",
                    element_ids=(el.id,),
                    hint="The node was deleted or never created: reconnect or remove the element.",
                )
            )
            rejected.append(el)
            continue
        if len(set(el.nodes)) != len(el.nodes):
            findings.append(
                Finding(
                    Severity.ERROR,
                    "repeated_node",
                    f"{label} lists the same node more than once: {list(el.nodes)}.",
                    node_ids=tuple(sorted(set(el.nodes))),
                    element_ids=(el.id,),
                )
            )
            rejected.append(el)
            continue
        if isinstance(el, (*TRUSS_CLASSES, *FRAME_CLASSES)):
            length = float(np.linalg.norm(points[el.nodes[1]] - points[el.nodes[0]]))
            if length <= tol:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "zero_length_member",
                        f"{label} has zero length: nodes {el.nodes[0]} and {el.nodes[1]} are at the same point.",
                        node_ids=tuple(el.nodes),
                        element_ids=(el.id,),
                        hint="Merge the two nodes or delete the element.",
                    )
                )
                rejected.append(el)
                continue
        elif isinstance(el, ZERO_LENGTH_CLASSES) and len(el.nodes) == 2:
            gap = float(np.linalg.norm(points[el.nodes[1]] - points[el.nodes[0]]))
            if gap > max(tol, 1e-6 * _model_size(project)):
                findings.append(
                    Finding(
                        Severity.WARNING,
                        "separated_zero_length",
                        f"{label} joins nodes {el.nodes[0]} and {el.nodes[1]}, {gap:g} apart; "
                        "it is meant to join nodes at the same point.",
                        node_ids=tuple(el.nodes),
                        element_ids=(el.id,),
                    )
                )
        if isinstance(el, FRAME_CLASSES) and not _rotation_dofs(ndm, ndf):
            findings.append(
                Finding(
                    Severity.ERROR,
                    "dof_mismatch",
                    f"{label} needs rotational DOF but the model has ndm={ndm}, ndf={ndf}.",
                    element_ids=(el.id,),
                    hint="Use ndf=3 for a 2D frame or ndf=6 for a 3D frame.",
                )
            )
            rejected.append(el)
            continue
        if isinstance(el, QuadElement) and (ndm, ndf) != (2, 2):
            findings.append(
                Finding(
                    Severity.ERROR,
                    "dof_mismatch",
                    f"{label} is a 2D solid and needs ndm=2, ndf=2 (the model has ndm={ndm}, ndf={ndf}).",
                    element_ids=(el.id,),
                )
            )
            rejected.append(el)
            continue
        if isinstance(el, (ShellMITC4Element, ShellDKGTElement)) and (ndm, ndf) != (3, 6):
            findings.append(
                Finding(
                    Severity.ERROR,
                    "dof_mismatch",
                    f"{label} is a shell and needs ndm=3, ndf=6 (the model has ndm={ndm}, ndf={ndf}).",
                    element_ids=(el.id,),
                )
            )
            rejected.append(el)
            continue
        if isinstance(el, ZeroLengthElement):
            bad = [d for d in el.dofs if zero_length_dof(ndm, ndf, d) is None]
            if bad:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "dof_mismatch",
                        f"{label} acts in direction{'s' if len(set(bad)) > 1 else ''} "
                        f"{_ids(bad)}, which OpenSees gives no stiffness in a model with "
                        f"ndm={ndm}, ndf={ndf}.",
                        element_ids=(el.id,),
                        hint="zeroLength directions 1-3 are translations along x, y, z and 4-6 "
                        "rotations about x, y, z; a 2D rotational spring is direction 6.",
                    )
                )
        usable.append(el)

    constraints: list[Any] = []
    for mp in project.mp_constraints:
        label = f"equalDOF constraint {mp.retained_node}→{mp.constrained_node}"
        missing = [n for n in (mp.retained_node, mp.constrained_node) if n not in nodes]
        if missing:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "missing_node",
                    f"{label} refers to missing node{'s' if len(missing) > 1 else ''} {_ids(missing)}.",
                    node_ids=tuple(
                        n for n in (mp.retained_node, mp.constrained_node) if n in nodes
                    ),
                )
            )
            continue
        bad = [d for d in mp.dofs if d < 1 or d > ndf]
        if bad:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "dof_mismatch",
                    f"{label} constrains DOF {_ids(bad)} but the model has only {ndf} DOF per node.",
                    node_ids=(mp.retained_node, mp.constrained_node),
                )
            )
            continue
        constraints.append(mp)

    local_dofs = {slot: number + 1 for number, slot in enumerate(idx)}
    for link in project.rigid_links:
        label = f"rigid link {link.retained_node}->{link.constrained_node}"
        missing = [n for n in (link.retained_node, link.constrained_node) if n not in nodes]
        if missing:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "missing_node",
                    f"{label} refers to missing node{'s' if len(missing) > 1 else ''} "
                    f"{_ids(missing)}.",
                    node_ids=tuple(
                        n for n in (link.retained_node, link.constrained_node) if n in nodes
                    ),
                )
            )
            continue
        constraints.append(
            _Connection(link.retained_node, link.constrained_node, tuple(range(1, ndf + 1)))
        )

    for diaphragm in project.diaphragms:
        label = f"diaphragm {diaphragm.id}"
        if diaphragm.retained_node not in nodes:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "missing_node",
                    f"{label} refers to missing retained node {diaphragm.retained_node}.",
                )
            )
            continue
        dofs = tuple(
            local_dofs[slot]
            for slot in IN_PLANE_SLOTS.get(diaphragm.perp_dirn, ())
            if slot in local_dofs
        )
        if not dofs:
            continue
        for nid in constrained_node_ids(project, diaphragm):
            if nid not in nodes:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "missing_node",
                        f"{label} refers to missing constrained node {nid}.",
                        node_ids=(diaphragm.retained_node,),
                    )
                )
                continue
            constraints.append(_Connection(diaphragm.retained_node, nid, dofs))

    fixed_slots = auto_fixed_slots(project)

    # ── loose nodes ─────────────────────────────────────────────────
    touched: set[int] = set()
    for el in usable:
        touched.update(el.nodes)
    for mp in constraints:
        touched.update((mp.retained_node, mp.constrained_node))
    # An element that was rejected above still "touches" its nodes: they are not
    # loose, the element is what is wrong, and that has its own finding.
    for el in rejected:
        touched.update(n for n in el.nodes if n in nodes)

    for node in project.nodes:
        if node.id in touched:
            continue
        active_free = any(not node.restraint[slot] for slot in idx)
        if active_free:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "orphan_node",
                    f"Node {node.id} is not connected to anything.",
                    node_ids=(node.id,),
                    hint="Connect it with an element, restrain it, or delete it.",
                )
            )
        else:
            findings.append(
                Finding(
                    Severity.WARNING,
                    "orphan_support",
                    f"Node {node.id} is fully restrained but no element reaches it.",
                    node_ids=(node.id,),
                    hint="It has no effect on the analysis; delete it if it is a leftover.",
                )
            )

    # ── connectivity ────────────────────────────────────────────────
    live = [n for n in nodes if n in touched]
    groups = _UnionFind(live)
    for el in usable:
        first, *rest = el.nodes
        for other in rest:
            groups.union(first, other)
    for mp in constraints:
        groups.union(mp.retained_node, mp.constrained_node)
    parts: dict[int, list[int]] = defaultdict(list)
    for nid in live:
        parts[groups.find(nid)].append(nid)
    part_list = sorted((sorted(members) for members in parts.values()), key=lambda m: m[0])

    sprung = {s.node_id for s in nodal_springs(project)} | {
        n.id for n in project.nodes if any(n.spring[slot] > 0 for slot in idx)
    }

    def is_supported(members: Iterable[int]) -> bool:
        return any(n in sprung or any(nodes[n].restraint[slot] for slot in idx) for n in members)

    floating = [m for m in part_list if not is_supported(m)]
    supported = [m for m in part_list if is_supported(m)]
    for members in floating:
        whole = len(part_list) == 1
        findings.append(
            Finding(
                Severity.ERROR,
                "floating_part",
                "The model has no supports: it can move as a rigid body."
                if whole
                else f"A part of the model ({_plural(len(members), 'node')}: {_ids(members)}) "
                "has no support: it can move as a rigid body.",
                node_ids=tuple(members),
                hint="Assign supports (Assign → Joint → Supports…) or connect it to a supported part.",
            )
        )
    if len(supported) > 1:
        findings.append(_disconnected_parts(supported, nodes, points, tol))

    # ── static stability ────────────────────────────────────────────
    mechanisms = 0
    checked = False
    skipped = 0 if check_stability else len(supported)
    if check_stability:
        limit = max_stability_dof()
        for members in supported:
            outcome = _check_part(
                project, members, usable, constraints, nodes, points, idx, fixed_slots, limit
            )
            if outcome is None:
                findings.append(
                    Finding(
                        Severity.INFO,
                        "stability_skipped",
                        f"Stability not checked for a part of {_plural(len(members), 'node')}: it is "
                        f"larger than the {limit}-DOF limit of this test.",
                        node_ids=tuple(members),
                        hint=f"Raise {MAX_DOF_ENV} to check it, or run the model and read the log.",
                    )
                )
                skipped += 1
                continue
            checked = True
            mechanisms += outcome.count
            findings.extend(outcome.findings)

    return report(
        part_count=len(part_list),
        mechanism_count=mechanisms,
        stability_checked=checked,
        stability_skipped_parts=skipped,
    )


def _plane_layout(project: Project, tol: float) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Coordinate axes and nodal DOF slots for the model's 2D/3D convention.

    The upstream 2D convention is X-Y; this fork draws 2D models in X-Z. A
    project whose 2D nodes have Y ordinates keeps the upstream reading, while
    the fork's X-Z models use the vertical axis. The all-zero line case is
    ambiguous and keeps the upstream reading because the mechanics are the
    same; only the label differs.
    """
    if project.ndm != 2:
        return (0, 1, 2), dof_indices(project.ndm, project.ndf)
    has_y = any(abs(float(node.coords[1])) > tol for node in project.nodes)
    has_z = any(abs(float(node.coords[2])) > tol for node in project.nodes)
    if has_z and not has_y:
        return (0, 2), dof_indices(2, project.ndf)
    if has_y and not has_z:
        return (0, 1), (0, 1) if project.ndf == 2 else (0, 1, 5)
    # A line on the origin is ambiguous geometrically. Its supports and masses
    # still say which plane convention the project uses: a fork model stores
    # the second translation in Uz, the upstream model in Uy.
    fork_signal = any(node.restraint[2] or node.spring[2] or node.mass[2] for node in project.nodes)
    upstream_signal = any(
        node.restraint[1] or node.spring[1] or node.mass[1] for node in project.nodes
    )
    if fork_signal and not upstream_signal:
        return (0, 2), dof_indices(2, project.ndf)
    if upstream_signal and not fork_signal:
        return (0, 1), (0, 1) if project.ndf == 2 else (0, 1, 5)
    return (0, 2), dof_indices(2, project.ndf)


def _model_size(project: Project) -> float:
    coords = np.array([n.coords for n in project.nodes], dtype=float)
    return float(np.linalg.norm(coords.max(axis=0) - coords.min(axis=0)))


def _disconnected_parts(
    supported: list[list[int]],
    nodes: dict[int, Any],
    points: dict[int, np.ndarray],
    tol: float,
) -> Finding:
    """Several supported parts: say so, and name nodes that sit on each other."""
    part_of = {nid: k for k, members in enumerate(supported) for nid in members}
    cells: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    cell = max(tol, 1e-12)
    for nid in part_of:
        p = np.zeros(3)
        p[: len(points[nid])] = points[nid]
        cells[(int(p[0] // cell), int(p[1] // cell), int(p[2] // cell))].append(nid)
    pairs: list[tuple[int, int]] = []
    for nid, k in part_of.items():
        p = np.zeros(3)
        p[: len(points[nid])] = points[nid]
        cx, cy, cz = (int(p[0] // cell), int(p[1] // cell), int(p[2] // cell))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for other in cells.get((cx + dx, cy + dy, cz + dz), ()):
                        other_point = np.zeros(3)
                        other_point[: len(points[other])] = points[other]
                        if (
                            other > nid
                            and part_of[other] != k
                            and float(np.linalg.norm(other_point - p)) <= tol
                        ):
                            pairs.append((nid, other))
    sizes = ", ".join(str(len(m)) for m in supported[:LISTED_IDS])
    message = (
        f"The model is made of {len(supported)} separate parts that nothing connects "
        f"({sizes} nodes)."
    )
    if pairs:
        shown = "; ".join(f"{a} and {b}" for a, b in pairs[:4])
        more = "" if len(pairs) <= 4 else f" … and {len(pairs) - 4} more"
        hint = (
            f"Nodes {shown}{more} sit at the same point but are separate: "
            "merge them (Edit → Check Model for Duplicates)."
        )
    else:
        hint = "If that is not intended, a member or a connection is missing between them."
    involved = sorted({n for pair in pairs for n in pair}) or [m[0] for m in supported]
    return Finding(
        Severity.WARNING, "disconnected_parts", message, node_ids=tuple(involved), hint=hint
    )


@dataclass(frozen=True)
class _Connection:
    """A rigid link or diaphragm tie, in the same shape as an equalDOF."""

    retained_node: int
    constrained_node: int
    dofs: tuple[int, ...]


@dataclass
class _PartOutcome:
    count: int = 0
    findings: list[Finding] = field(default_factory=list)


def _check_part(
    project: Project,
    members: list[int],
    elements: list[Any],
    constraints: list[Any],
    nodes: dict[int, Any],
    points: dict[int, np.ndarray],
    idx: tuple[int, ...],
    fixed_slots: dict[int, set[int]],
    limit: int,
) -> _PartOutcome | None:
    """Mechanisms of one connected, supported part; ``None`` if it is too large."""
    ndm, ndf = project.ndm, project.ndf
    member_set = set(members)

    # Free DOF of the part: every active DOF that is not restrained. A floating
    # diaphragm master also has its out-of-plane slots fixed by the runner.
    column: dict[tuple[int, int], int] = {}
    for nid in members:
        fixed = fixed_slots.get(nid, set())
        for dof in range(ndf):
            if not nodes[nid].restraint[idx[dof]] and idx[dof] not in fixed:
                column[(nid, dof)] = len(column)
    size = len(column)
    if size == 0:
        return _PartOutcome()
    if size > limit:
        return None

    stiffness = np.zeros((size, size))

    def accumulate(rows: list[Row]) -> None:
        kept: list[tuple[list[int], list[float]]] = []
        for row in rows:
            cols = [column[key] for key in row if key in column]
            vals = [value for key, value in row.items() if key in column]
            norm = math.sqrt(sum(v * v for v in vals))
            if norm < 1e-12:
                continue  # every DOF of this deformation is a support
            kept.append((cols, [v / norm for v in vals]))
        if not kept:
            return
        local = sorted({c for cols, _ in kept for c in cols})
        where = {c: k for k, c in enumerate(local)}
        block = np.zeros((len(kept), len(local)))
        for r, (cols, vals) in enumerate(kept):
            for c, v in zip(cols, vals, strict=True):
                block[r, where[c]] += v
        stiffness[np.ix_(local, local)] += block.T @ block

    for el in elements:
        if el.nodes[0] in member_set:
            accumulate(_element_rows(project, el, points, ndm, ndf))
    for mp in constraints:
        if mp.retained_node in member_set:
            accumulate(
                [
                    {(mp.constrained_node, d - 1): 1.0, (mp.retained_node, d - 1): -1.0}
                    for d in mp.dofs
                ]
            )
    # Support springs hold the DOFs they act on: a joint spring its own DOF, a
    # line, edge or area spring the translation along its direction. One-sided
    # springs count as engaged (this is a linear test).
    spring_rows: list[Row] = []
    for nid in members:
        for dof in range(ndf):
            if nodes[nid].spring[idx[dof]] > 0:
                spring_rows.append({(nid, dof): 1.0})
    for spring in nodal_springs(project):
        if spring.node_id in member_set:
            row: Row = {}
            for dof in range(ndf):
                slot = idx[dof]
                if slot < 3 and abs(spring.direction[slot]) > 1e-12:
                    row[(spring.node_id, dof)] = spring.direction[slot]
            if row:
                spring_rows.append(row)
    accumulate(spring_rows)

    outcome = _PartOutcome()
    labels = {v: k for k, v in column.items()}
    diagonal = np.diag(stiffness).copy()
    uncovered = [k for k in range(size) if diagonal[k] <= 1e-12]
    null_mask = np.zeros(size)  # participation of each DOF in the null space

    for k in uncovered:
        null_mask[k] = 1.0
    covered = [k for k in range(size) if k not in set(uncovered)]
    null_dim = len(uncovered)

    if covered:
        sub = stiffness[np.ix_(covered, covered)]
        scale = 1.0 / np.sqrt(np.diag(sub))
        unit = sub * scale[:, None] * scale[None, :]
        if not _certainly_stable(unit):
            values, vectors = np.linalg.eigh(unit)
            is_null = values < NULL_EIGEN_RATIO * max(values[-1], 1e-300)
            if is_null.any():
                null_dim += int(is_null.sum())
                projector = (vectors[:, is_null] ** 2).sum(axis=1)
                for pos, k in enumerate(covered):
                    null_mask[k] = max(null_mask[k], projector[pos])

    if null_dim == 0:
        return outcome

    moving = [labels[k] for k in range(size) if null_mask[k] >= PARTICIPATION]
    by_node: dict[int, list[str]] = defaultdict(list)
    for nid, dof in moving:
        by_node[nid].append(DOF_LABELS[idx[dof]])
    outcome.count = null_dim

    # The null space itself, for describing and drawing each motion.
    columns: list[np.ndarray] = []
    for k in uncovered:
        unit_vector = np.zeros(size)
        unit_vector[k] = 1.0
        columns.append(unit_vector)
    if covered and null_dim > len(uncovered):
        for vector in vectors[:, is_null].T:
            full = np.zeros(size)
            full[covered] = vector * scale  # back from the unit-diagonal scaling
            columns.append(full)
    basis = _localised(np.column_stack(columns)) if columns else np.zeros((size, 0))
    part_elements = [el for el in elements if el.nodes[0] in member_set]
    modes = []
    for j in range(min(basis.shape[1], MAX_MODES)):
        motion: dict[int, np.ndarray] = {}
        for k in range(size):
            if basis[k, j] != 0.0:
                nid, dof = labels[k]
                motion.setdefault(nid, np.zeros(6))[idx[dof]] = basis[k, j]
        modes.append(_describe_mode(project, motion, nodes, members, part_elements))
    outcome.findings.append(_mechanism_finding(project, null_dim, by_node, elements, tuple(modes)))
    return outcome


def _localised(basis: np.ndarray) -> np.ndarray:
    """A basis of the same space where each vector is pinned to its own DOF.

    Elimination with complete pivoting picks one DOF per vector; the combination
    that is 1 on its own pivot and 0 on the others keeps independent hinges apart
    instead of the arbitrary blend an eigen-solver returns for a repeated zero
    eigenvalue.
    """
    m = basis.shape[1]
    work = basis.copy()
    rows: list[int] = []
    free_cols = list(range(m))
    for _ in range(m):
        block = np.abs(work[:, free_cols])
        block[rows, :] = 0.0
        row, k = np.unravel_index(int(np.argmax(block)), block.shape)
        col = free_cols.pop(int(k))
        rows.append(int(row))
        pivot = work[row, col]
        if pivot == 0.0:
            break
        for other in free_cols:
            work[:, other] -= work[row, other] / pivot * work[:, col]
    try:
        local = basis @ np.linalg.inv(basis[rows, :])
    except np.linalg.LinAlgError:
        local = basis
    peak = np.max(np.abs(local), axis=0)
    peak[peak == 0.0] = 1.0
    local = local / peak
    local[np.abs(local) < 1e-12] = 0.0
    return np.asarray(local, dtype=float)


_AXES = ("X", "Y", "Z")


def _direction_text(vector: np.ndarray) -> str:
    """'X' for a vector along an axis, otherwise its unit components."""
    unit = vector / np.linalg.norm(vector)
    axis = int(np.argmax(np.abs(unit)))
    if abs(unit[axis]) > 0.995:
        return _AXES[axis]
    return "(" + ", ".join(f"{c:.2f}" for c in unit) + ")"


def _describe_mode(
    project: Project,
    raw: dict[int, np.ndarray],
    nodes: dict[int, Any],
    members: list[int],
    elements: list[Any],
) -> MechanismMode:
    """Classify one free motion and say what to do about it."""
    peak = max((float(np.max(np.abs(v))) for v in raw.values()), default=1.0) or 1.0
    motion = {nid: v / peak for nid, v in raw.items()}
    moving = sorted(n for n, v in motion.items() if float(np.max(np.abs(v))) >= MODE_SHARE)
    moving_set = set(moving)
    stored = {n: tuple(float(c) for c in motion[n]) for n in sorted(motion)}
    translation = {n: motion[n][:3] for n in moving}
    rotation = {n: motion[n][3:] for n in moving}
    largest_t = max((float(np.max(np.abs(t))) for t in translation.values()), default=0.0)
    carried = [el for el in elements if all(n in moving_set for n in el.nodes)]
    boundary = [
        el
        for el in elements
        if any(n in moving_set for n in el.nodes) and not all(n in moving_set for n in el.nodes)
    ]
    where = _ids(moving)

    def mode(kind: str, description: str, hint: str, involved: list[Any]) -> MechanismMode:
        return MechanismMode(
            motion=stored,
            kind=kind,
            description=description,
            hint=hint,
            node_ids=tuple(moving),
            element_ids=tuple(sorted({el.id for el in involved}))[: 4 * LISTED_IDS],
        )

    # Rotations only: a joint that turns while nothing around it translates.
    if largest_t < RIGID_RESIDUAL:
        axes = sorted(
            {_AXES[a] for r in rotation.values() for a in range(3) if abs(r[a]) >= MODE_SHARE}
        )
        about = "/".join(axes)
        attached = [el for el in elements if any(n in moving_set for n in el.nodes)]
        if attached and all(isinstance(el, TRUSS_CLASSES) for el in attached):
            hint = (
                "Only bars reach these joints, and bars carry no moment: restrain the "
                "rotations there, or use a truss model (ndf=2 in 2D, ndf=3 in 3D)."
            )
        elif len(moving) == 2 and len(carried) == 1:
            hint = (
                f"Member {carried[0].id} can spin about its own axis: restrain its "
                "torsion at one end (a support, or a joint that is not a ball)."
            )
        else:
            hint = (
                "Every member end at these joints is released (or a bar): keep one end "
                "rigid, or restrain the rotation with a support."
            )
        return mode(
            "free_rotation",
            f"Joint(s) {where} rotate freely about {about}: nothing resists the rotation.",
            hint,
            attached,
        )

    # A rigid-body motion of the moving nodes: u = t + w × p, theta = w.
    rows: list[np.ndarray] = []
    rhs: list[float] = []
    for n in moving:
        p = np.asarray(nodes[n].coords, dtype=float)
        skew = np.array([[0.0, p[2], -p[1]], [-p[2], 0.0, p[0]], [p[1], -p[0], 0.0]])
        for a in range(3):
            rows.append(np.concatenate([np.eye(3)[a], skew[a]]))
            rhs.append(float(translation[n][a]))
        for a in range(3):
            if _rotation_slot_active(project, a):
                rows.append(np.concatenate([np.zeros(3), np.eye(3)[a]]))
                rhs.append(float(rotation[n][a]))
    matrix, vector = np.array(rows), np.array(rhs)
    solution, *_ = np.linalg.lstsq(matrix, vector, rcond=None)
    residual = float(np.linalg.norm(matrix @ solution - vector)) / max(
        float(np.linalg.norm(vector)), 1e-300
    )
    whole = moving_set == set(members)
    if len(moving) == 1 and not whole:
        # One joint on its own: every member reaching it lines up with the motion.
        direction = _direction_text(translation[moving[0]])
        return mode(
            "free_joint",
            f"Joint {moving[0]} can move along {direction}: the members that reach it "
            "line up, or none of them stiffens that direction.",
            "Brace the joint across that direction, restrain it with a support, or "
            "check for bars that meet in a straight line.",
            boundary,
        )
    subject = (
        "The whole structure" if whole else f"A group of {_plural(len(moving), 'joint')} ({where})"
    )
    if residual < RIGID_RESIDUAL:
        t, w = solution[:3], solution[3:]
        extent = max(
            (float(np.linalg.norm(np.asarray(nodes[n].coords, dtype=float))) for n in moving),
            default=1.0,
        )
        if float(np.linalg.norm(w)) * max(extent, 1.0) < 1e-6 * float(np.linalg.norm(t)) or (
            float(np.linalg.norm(w)) < 1e-12
        ):
            direction = _direction_text(t)
            if whole:
                hint = (
                    f"Nothing holds the structure along {direction}: add a support that "
                    "restrains that translation (Assign → Joint → Supports…)."
                )
            else:
                hint = (
                    "It hangs on the rest only through elements that do not resist this "
                    "motion (hinges, releases, bars in line): add a brace or a support to "
                    "the group, or remove a release."
                )
            return mode(
                "rigid_translation",
                f"{subject} slides along {direction} as a rigid body.",
                hint,
                boundary or carried,
            )
        w_norm = float(np.linalg.norm(w))
        centre = np.cross(w, t) / (w_norm**2)
        pivot = min(
            moving or members,
            key=lambda n: float(
                np.linalg.norm(
                    np.cross(np.asarray(nodes[n].coords, dtype=float) - centre, w / w_norm)
                )
            ),
        )
        direction = _direction_text(w)
        if whole:
            hint = (
                f"The supports only hold a line or a point: add a support away from joint "
                f"{pivot}, or restrain the rotation about {direction} there."
            )
        else:
            hint = (
                "The group is joined to the rest by hinges on one line or one point: make "
                "one of those connections rigid, or brace the group."
            )
        return mode(
            "rigid_rotation",
            f"{subject} turns as a rigid body about an axis parallel to {direction} "
            f"near joint {pivot}.",
            hint,
            boundary or carried,
        )

    # Lateral sway: joints move sideways (no elevation change) while members turn.
    vertical = 2  # Z is the elevation axis of every model, 2D included
    lateral = [a for a in range(3) if a != vertical]
    sway = sum(float(np.linalg.norm(translation[n][lateral])) for n in moving)
    lift = sum(abs(float(translation[n][vertical])) for n in moving)
    elevations = {round(float(nodes[n].coords[vertical]), 9) for n in moving}
    if sway > 0.0 and lift < 1e-3 * sway and len(elevations) <= max(1, len(moving) // 2):
        mean = np.mean([translation[n] for n in moving], axis=0)
        direction = _direction_text(mean) if float(np.linalg.norm(mean)) > 0 else "sideways"
        return mode(
            "sway",
            f"Joints {where} sway along {direction}: the frame has no lateral "
            "stiffness in that direction.",
            "Add bracing or a shear wall, fix the column bases, or make the "
            "beam-column joints rigid (remove end releases).",
            boundary + carried,
        )
    return mode(
        "mechanism",
        f"Joints {where} move without deforming any element.",
        "Look for a missing support or brace, a hinge with nothing resisting it, "
        "or bars that line up exactly.",
        boundary + carried,
    )


def _rotation_slot_active(project: Project, axis: int) -> bool:
    """Whether the global rotation slot ``3 + axis`` is a DOF of the model."""
    return (3 + axis) in set(dof_indices(project.ndm, project.ndf))


def _certainly_stable(unit: np.ndarray) -> bool:
    """True when a Cholesky factorisation of the unit-diagonal ``K`` proves it positive definite."""
    try:
        factor = np.linalg.cholesky(unit)
    except np.linalg.LinAlgError:
        return False
    return bool((np.diag(factor) ** 2).min() > STABLE_PIVOT)


def _mechanism_finding(
    project: Project,
    count: int,
    by_node: dict[int, list[str]],
    elements: list[Any],
    modes: tuple[MechanismMode, ...] = (),
) -> Finding:
    node_ids = tuple(sorted(by_node))
    detail = "; ".join(f"node {n} ({', '.join(by_node[n])})" for n in node_ids[:LISTED_IDS])
    if len(node_ids) > LISTED_IDS:
        detail += f"; … and {len(node_ids) - LISTED_IDS} more nodes"
    lead = (
        "The structure is unstable: 1 free motion deforms no element."
        if count == 1
        else f"The structure is unstable: {count} independent free motions deform no element."
    )
    touching = {n for n in node_ids}
    attached = [el for el in elements if any(n in touching for n in el.nodes)]
    only_rotations = all(label.startswith("R") for labels in by_node.values() for label in labels)
    if only_rotations and attached and all(isinstance(el, TRUSS_CLASSES) for el in attached):
        hint = (
            "Only rotations are free at nodes that nothing but bars reach: restrain Rx/Ry/Rz there, "
            "or use ndf=2 (2D truss) / ndf=3 (3D truss)."
        )
    elif len(modes) == 1:
        hint = modes[0].hint
    else:
        hint = (
            "Look for a missing support or brace, a hinge with nothing resisting it, "
            "or bars that line up exactly."
        )
    message = f"{lead} Free to move: {detail}."
    if modes:
        listed = " ".join(f"({k}) {m.description}" for k, m in enumerate(modes, start=1))
        message += f" {listed}"
        if count > len(modes):
            message += f" … and {count - len(modes)} more."
    return Finding(
        Severity.ERROR,
        "mechanism",
        message,
        node_ids=node_ids,
        element_ids=tuple(sorted(el.id for el in attached))[: 4 * LISTED_IDS],
        hint=hint,
        modes=modes,
    )
