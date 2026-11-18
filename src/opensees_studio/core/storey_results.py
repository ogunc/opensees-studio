"""Storey response: displacement, inter-storey drift ratio and storey shear per floor.

What a building engineer reads off ETABS' story tables, computed from the
nodal results the runner already has:

* **Storey displacement**: the lateral displacement of the floor. A floor with
  a rigid diaphragm moves with its retained node (the centre of mass when the
  diaphragm was placed there); any other floor is the mean of its joints.
* **Inter-storey drift ratio**: ``(u_floor - u_below) / h``, with ``h`` the
  storey height (:class:`core.storeys.StoreyLevel`).
* **Storey shear**: the lateral force carried by the storey, i.e. by the
  members cut just above the level below. A static case gets it from the
  members' end forces (:func:`storey_cuts`, evaluated by the runner); a
  response spectrum case from each mode's inertia forces ``w^2 m u`` above the
  cut, combined over the modes like any other response.
* **Base shear**: minus the sum of the lateral reactions (static), or the
  modal inertia force of the whole model combined over the modes.

Response spectrum peaks are combined per quantity (drift and shear of each
mode first, then SRSS/CQC), never derived from the combined displacements:
a peak drift is not the difference of two peak displacements.

No Qt, no OpenSees.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from opensees_studio.core.modal_combination import (
    DEFAULT_MODAL_DAMPING,
    combine_cqc,
    combine_srss,
    cqc_correlation,
)
from opensees_studio.core.storeys import (
    StoreyLevel,
    base_elevation,
    elevation_axis,
    elevation_tolerance,
    lateral_axes,
    nodes_at_elevation,
    storey_levels,
)

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

BASE_NAME = "Base"


@dataclass(frozen=True)
class StoreyCut:
    """The members a storey's shear runs through.

    ``members`` pairs an element id with the positions (in ``element.nodes``)
    of its nodes at or below the cut: the storey shear is minus the sum of the
    element's nodal forces at those nodes.
    """

    storey_id: int
    elevation: float
    members: tuple[tuple[int, tuple[int, ...]], ...]


def storey_cuts(project: Project) -> list[StoreyCut]:
    """One cut per storey, just above the level beneath it."""
    axis = elevation_axis(project.ndm)
    tol = elevation_tolerance(project)
    z = {n.id: float(n.coords[axis]) for n in project.nodes}
    cuts: list[StoreyCut] = []
    for level in storey_levels(project):
        limit = level.below + tol
        members: list[tuple[int, tuple[int, ...]]] = []
        for element in project.elements:
            heights = [z.get(nid) for nid in element.nodes]
            if any(h is None for h in heights):
                continue
            lower = tuple(i for i, h in enumerate(heights) if h <= limit)  # type: ignore[operator]
            if lower and len(lower) < len(heights):
                members.append((element.id, lower))
        cuts.append(StoreyCut(level.storey.id, level.below, tuple(members)))
    return cuts


def cut_force(
    cut: StoreyCut,
    element_nodes: Mapping[int, Sequence[int]],
    element_forces: Mapping[int, Sequence[float]],
    ndm: int,
) -> np.ndarray:
    """Storey shear (``ndm`` translational components) from global element nodal forces.

    ``element_forces`` holds what OpenSees' ``eleForce`` reports: the global
    forces the nodes apply to the element, the same number of values per node.
    The force the part above the cut passes down is minus their sum over the
    nodes below; with a lateral load P at the top of a cantilever it is +P.
    """
    total = np.zeros(ndm)
    for element_id, lower in cut.members:
        forces = np.asarray(element_forces.get(element_id, ()), dtype=float)
        n_nodes = len(element_nodes[element_id])
        if forces.size == 0 or forces.size % n_nodes:
            continue
        per_node = forces.size // n_nodes
        for position in lower:
            total += forces[position * per_node : position * per_node + ndm]
    return -total


# ─────────────────────────── displacement profile ───────────────────────────
def level_reference_nodes(project: Project, elevation: float) -> tuple[int, ...]:
    """The nodes whose displacement stands for the level at ``elevation``.

    The retained nodes of the horizontal diaphragms on that level, else every
    joint of the level.
    """
    axis = elevation_axis(project.ndm)
    tol = elevation_tolerance(project)
    coords = {n.id: n.coords for n in project.nodes}
    retained = tuple(
        sorted(
            {
                d.retained_node
                for d in project.diaphragms
                if d.perp_dirn == 3
                and d.retained_node in coords
                and abs(coords[d.retained_node][axis] - elevation) <= tol
            }
        )
    )
    return retained or tuple(nodes_at_elevation(project, elevation))


def _level_disp(
    disp: Mapping[int, np.ndarray], nodes: Sequence[int], axes: Sequence[int]
) -> np.ndarray:
    rows = [np.asarray(disp[nid], dtype=float) for nid in nodes if nid in disp]
    if not rows:
        return np.zeros(len(axes))
    return np.mean([[row[a] for a in axes] for row in rows], axis=0)


@dataclass(frozen=True)
class StoreyProfile:
    """Lateral displacement and drift ratio of every storey, lowest first.

    ``disp`` and ``drift`` have shape ``(n_storeys, n_lateral)``; ``base`` is
    the displacement of the base level.
    """

    levels: tuple[StoreyLevel, ...]
    disp: np.ndarray
    drift: np.ndarray
    base: np.ndarray


def storey_profile(project: Project, disp: Mapping[int, np.ndarray]) -> StoreyProfile:
    """Storey displacements and drift ratios from one nodal displacement field.

    ``disp`` maps node id to its DOF vector in the solver's DOF order, whose
    first entries are the translations (so lateral axis ``k`` is entry ``k``).
    """
    axes = lateral_axes(project.ndm)
    levels = tuple(storey_levels(project))
    base_z = base_elevation(project)
    base = _level_disp(disp, level_reference_nodes(project, base_z), axes)
    rows: list[np.ndarray] = []
    drifts: list[np.ndarray] = []
    below = base
    for level in levels:
        here = _level_disp(disp, level_reference_nodes(project, level.storey.elevation), axes)
        rows.append(here)
        drifts.append((here - below) / level.height)
        below = here
    shape = (len(levels), len(axes))
    return StoreyProfile(
        levels=levels,
        disp=np.array(rows, dtype=float).reshape(shape),
        drift=np.array(drifts, dtype=float).reshape(shape),
        base=base,
    )


def base_shear_from_reactions(project: Project, reactions: Mapping[int, np.ndarray]) -> np.ndarray:
    """Minus the sum of the lateral reactions: the lateral load the base resists."""
    axes = lateral_axes(project.ndm)
    total = np.zeros(len(axes))
    for vector in reactions.values():
        row = np.asarray(vector, dtype=float)
        total += [row[a] for a in axes]
    return -total


# ─────────────────────────── modal storey shears ───────────────────────────
def inertia_storey_shears(
    project: Project,
    levels: Sequence[StoreyLevel],
    disp: Mapping[int, np.ndarray],
    omega: float,
    masses: Mapping[int, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    """``(storey shears, base shear)`` of a modal displacement field.

    The inertia force of a node in mode ``i`` is ``w_i^2 m u``; a storey's
    shear sums it over the nodes above the cut, the base shear over every
    node. ``masses`` are canonical 6-slot vectors, ``disp`` in DOF order.
    """
    axes = lateral_axes(project.ndm)
    axis = elevation_axis(project.ndm)
    tol = elevation_tolerance(project)
    z = {n.id: float(n.coords[axis]) for n in project.nodes}
    w2 = omega * omega
    forces: dict[int, np.ndarray] = {}
    for nid, vector in disp.items():
        mass = masses.get(nid)
        if mass is None:
            continue
        row = np.asarray(vector, dtype=float)
        forces[nid] = np.array([w2 * float(mass[a]) * float(row[a]) for a in axes])
    shears = np.zeros((len(levels), len(axes)))
    for k, level in enumerate(levels):
        limit = level.below + tol
        for nid, force in forces.items():
            if z.get(nid, -np.inf) > limit:
                shears[k] += force
    base = np.sum(list(forces.values()), axis=0) if forces else np.zeros(len(axes))
    return shears, np.asarray(base, dtype=float)


@dataclass(frozen=True)
class CombinedStoreyResponse:
    """Peak storey response of a response spectrum case (all values positive)."""

    levels: tuple[StoreyLevel, ...]
    disp: np.ndarray
    drift: np.ndarray
    shear: np.ndarray
    base_shear: np.ndarray


def combine_storey_response(
    project: Project,
    modal_disp: Sequence[Mapping[int, np.ndarray]],
    omegas: Sequence[float],
    masses: Mapping[int, np.ndarray],
    *,
    method: str = "SRSS",
    damping: float | None = None,
) -> CombinedStoreyResponse:
    """Combine each mode's storey displacement, drift and shear by SRSS or CQC.

    ``modal_disp`` holds one peak displacement field per mode (``u_i =
    Gamma_i phi_i Sa_i / w_i^2``), ``omegas`` the modes' circular frequencies.
    """
    levels = tuple(storey_levels(project))
    n_lat = len(lateral_axes(project.ndm))
    n_modes = len(modal_disp)
    if n_modes == 0:
        empty = np.zeros((len(levels), n_lat))
        return CombinedStoreyResponse(levels, empty, empty, empty, np.zeros(n_lat))
    rule = method.upper()
    if rule not in ("SRSS", "CQC"):
        raise ValueError(f"Unsupported combination method: {method!r}")
    disp = np.zeros((n_modes, len(levels), n_lat))
    drift = np.zeros_like(disp)
    shear = np.zeros_like(disp)
    base = np.zeros((n_modes, n_lat))
    for i, (field, omega) in enumerate(zip(modal_disp, omegas, strict=True)):
        profile = storey_profile(project, field)
        disp[i], drift[i] = profile.disp, profile.drift
        shear[i], base[i] = inertia_storey_shears(project, levels, field, omega, masses)
    rho = (
        cqc_correlation(list(omegas), damping if damping is not None else DEFAULT_MODAL_DAMPING)
        if rule == "CQC"
        else None
    )

    def combine(peaks: np.ndarray) -> np.ndarray:
        return combine_srss(peaks) if rho is None else combine_cqc(peaks, rho)

    return CombinedStoreyResponse(
        levels=levels,
        disp=combine(disp),
        drift=combine(drift),
        shear=combine(shear),
        base_shear=combine(base),
    )
