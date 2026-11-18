"""Mass source: nodal mass derived from the weight of the model and its loads.

SAP2000 and ETABS call it the *mass source*: instead of typing a mass at every
joint, the mass is ``W / g`` of

* the elements' self weight (``element_self_mass``: the frames and shells that
  carry a unit weight, as in :mod:`core.self_weight`), and
* chosen load patterns, each scaled by a factor (the usual ``D + 0.3 L``).

A pattern contributes the *downward* (gravity) component of its nodal loads,
its uniform and point element loads, and its own self-weight multiplier. An
element load is lumped on the element's two end nodes (half each for a uniform
load, by the lever rule for a point load); a shell's weight goes to its
corners by tributary area. A node whose summed weight comes out upward gets no
mass from it. Note that a pattern carrying self weight *and*
``element_self_mass`` counts the self weight twice, as in ETABS.

The mass goes on the lateral translations; ``include_vertical`` adds the
vertical one; a restrained DOF gets none. Masses typed on the nodes always count.

With ``lump_at_diaphragms`` the in-plane mass of every rigid diaphragm is
moved to its retained node, together with the rotational inertia
``sum(m * r^2)`` about it. That is exact only when the retained node is at the
centre of that mass (the rigid-body mass matrix about any other point couples
translation and rotation, which a lumped ``mass`` command cannot express); a
diaphragm whose retained node is off the centre keeps its mass on the joints,
which the constraint then carries exactly. Either way the dynamics are the
same; lumping changes where the mass is reported.

No Qt, no OpenSees.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from opensees_studio.core.diaphragms import IN_PLANE_SLOTS, centre_of_mass, constrained_node_ids
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.loads import PlainLoadPattern
from opensees_studio.core.units import gravity

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

LUMP_COUPLING_REL_TOL = 1e-9
"""A retained node counts as at the centre of mass when the first mass moment
about it is below this fraction of ``total mass * diaphragm size``."""


class MassSourcePattern(BaseModel):
    """One load pattern of the mass source and its factor."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    pattern_id: PositiveInt
    factor: float = Field(default=1.0, ge=0.0, description="Scale on the pattern's weight.")


class MassSource(BaseModel):
    """Where the model's mass comes from, besides the masses typed on nodes."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    element_self_mass: bool = Field(
        default=True, description="Self weight of the weighted frames and shells, over g."
    )
    patterns: list[MassSourcePattern] = Field(default_factory=list)
    include_vertical: bool = Field(
        default=False, description="Also put the mass on the vertical translation."
    )
    lump_at_diaphragms: bool = Field(
        default=True,
        description="Move each diaphragm's in-plane mass and rotational inertia to its retained node.",
    )


# ─────────────────────────── weight per node ───────────────────────────
def _frame_end_shares(
    project: Project, coords: dict[int, np.ndarray], element: object
) -> tuple[np.ndarray, np.ndarray, float] | None:
    """``(x, y, z)`` local axes stacked as rows, and the length, or None."""
    nodes: tuple[int, ...] = tuple(getattr(element, "nodes", ()))
    if len(nodes) != 2:
        return None
    axes = frame_local_axes(project.ndm, coords[nodes[0]].tolist(), coords[nodes[1]].tolist())
    if axes is None:
        return None
    length = float(np.linalg.norm(coords[nodes[1]] - coords[nodes[0]]))
    return np.vstack(axes), np.asarray(nodes), length


def self_weight_per_node(project: Project, multiplier: float = 1.0) -> dict[int, float]:
    """Node id -> downward weight of the weighted frames (half per end), trusses and shells."""
    # Imported here: core.self_weight -> core.geometry -> core (package) -> project
    # -> mass_source would otherwise be a cycle.
    from opensees_studio.core.self_weight import (
        gravity_direction,
        nodal_self_weight_loads,
        weight_per_length,
    )

    if multiplier == 0.0:
        return {}
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    down = gravity_direction(project.ndm)
    out: dict[int, float] = {}
    for element in project.elements:
        w = weight_per_length(project, element)
        if not w or len(element.nodes) != 2:
            continue
        i, j = element.nodes
        half = 0.5 * w * multiplier * float(np.linalg.norm(coords[j] - coords[i]))
        out[i] = out.get(i, 0.0) + half
        out[j] = out.get(j, 0.0) + half
    for nid, force in nodal_self_weight_loads(project, multiplier).items():
        out[nid] = out.get(nid, 0.0) + float(force @ down)
    return out


def pattern_weight_per_node(project: Project, pattern: PlainLoadPattern) -> dict[int, float]:
    """Node id -> downward weight the pattern applies, lumped on nodes (signed)."""
    from opensees_studio.core.self_weight import gravity_direction

    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    elements = {e.id: e for e in project.elements}
    down = gravity_direction(project.ndm)
    out: dict[int, float] = {}

    def add(nid: int, value: float) -> None:
        out[nid] = out.get(nid, 0.0) + value

    for nodal in pattern.nodal_loads:
        add(nodal.node_id, float(np.asarray(nodal.forces[:3], dtype=float) @ down))
    for uniform in pattern.element_loads:
        element = elements.get(uniform.element_id)
        frame = _frame_end_shares(project, coords, element) if element is not None else None
        if frame is None:
            continue
        axes, nodes, length = frame
        # Local (wx, wy, wz) per unit length to a global vector, then downward.
        q = float((np.array([uniform.wx, uniform.wy, uniform.wz]) @ axes) @ down) * length
        add(int(nodes[0]), 0.5 * q)
        add(int(nodes[1]), 0.5 * q)
    for point in pattern.point_loads:
        element = elements.get(point.element_id)
        frame = _frame_end_shares(project, coords, element) if element is not None else None
        if frame is None:
            continue
        axes, nodes, _length = frame
        p = float((np.array([point.px, point.py, point.pz]) @ axes) @ down)
        add(int(nodes[0]), (1.0 - point.x) * p)
        add(int(nodes[1]), point.x * p)
    for nid, value in self_weight_per_node(project, pattern.self_weight).items():
        add(nid, value)
    return out


def source_weight_per_node(project: Project, source: MassSource) -> dict[int, float]:
    """Node id -> total downward weight the mass source turns into mass (never negative)."""
    total: dict[int, float] = {}
    contributions: list[tuple[dict[int, float], float]] = []
    if source.element_self_mass:
        contributions.append((self_weight_per_node(project), 1.0))
    patterns = {p.id: p for p in project.load_patterns}
    for entry in source.patterns:
        pattern = patterns.get(entry.pattern_id)
        if isinstance(pattern, PlainLoadPattern) and entry.factor:
            contributions.append((pattern_weight_per_node(project, pattern), entry.factor))
    for weights, factor in contributions:
        for nid, value in weights.items():
            total[nid] = total.get(nid, 0.0) + factor * value
    return {nid: value for nid, value in total.items() if value > 0.0}


# ─────────────────────────── nodal masses ───────────────────────────
def _translation_slots(ndm: int, include_vertical: bool) -> tuple[int, ...]:
    lateral = (0,) if ndm == 2 else (0, 1)
    vertical = (2,)  # Z, in 2D (the X-Z plane) and in 3D
    return lateral + vertical if include_vertical else lateral


def effective_nodal_masses(project: Project) -> dict[int, np.ndarray]:
    """Node id -> the canonical 6-slot mass the solver gets.

    The typed nodal mass plus, with a mass source, the derived mass and the
    diaphragm lumping. Without a mass source this is exactly ``node.mass``.
    """
    masses = {n.id: np.asarray(n.mass, dtype=float).copy() for n in project.nodes}
    source = project.mass_source
    if source is None:
        return masses
    g = gravity(project.meta.units)
    slots = _translation_slots(project.ndm, source.include_vertical)
    restraint = {n.id: n.restraint for n in project.nodes}
    for nid, weight in source_weight_per_node(project, source).items():
        if nid in masses:
            for slot in slots:
                # A support carries its own weight: mass on a fixed DOF never
                # moves and would only dilute the participating mass ratios.
                if not restraint[nid][slot]:
                    masses[nid][slot] += weight / g
    if source.lump_at_diaphragms and project.ndm == 3:
        _lump_at_diaphragms(project, masses)
    return masses


def _lump_at_diaphragms(project: Project, masses: dict[int, np.ndarray]) -> None:
    """Move each diaphragm's in-plane mass to its retained node, when that is exact."""
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    for diaphragm in project.diaphragms:
        retained = diaphragm.retained_node
        if retained not in masses:
            continue
        members = [nid for nid in constrained_node_ids(project, diaphragm) if nid in masses]
        if not members:
            continue
        a, b, rot = IN_PLANE_SLOTS[diaphragm.perp_dirn]
        # In-plane coordinates follow the translation slots (slot k is axis k).
        d = np.array([coords[nid] - coords[retained] for nid in members])
        da, db = d[:, a], d[:, b]
        ma = np.array([masses[nid][a] for nid in members])
        mb = np.array([masses[nid][b] for nid in members])
        total = float(ma.sum() + mb.sum())
        if total <= 0.0:
            continue
        size = float(np.abs(d[:, [a, b]]).max()) or 1.0
        coupling = max(abs(float(ma @ db)), abs(float(mb @ da)))
        if coupling > LUMP_COUPLING_REL_TOL * total * size:
            continue  # off the centre of mass: the joints keep it (exact)
        inertia = float(ma @ db**2 + mb @ da**2) + sum(float(masses[nid][rot]) for nid in members)
        masses[retained][a] += float(ma.sum())
        masses[retained][b] += float(mb.sum())
        masses[retained][rot] += inertia
        for nid in members:
            masses[nid][a] = masses[nid][b] = masses[nid][rot] = 0.0


def total_translational_mass(project: Project) -> tuple[float, float, float]:
    """Sum of the effective mass in X, Y and Z (a check value for the dialog)."""
    masses = effective_nodal_masses(project)
    if not masses:
        return (0.0, 0.0, 0.0)
    total = np.sum(list(masses.values()), axis=0)
    return (float(total[0]), float(total[1]), float(total[2]))


def diaphragm_centre_of_mass(
    project: Project, node_ids: Sequence[int], perp_dirn: int = 3
) -> tuple[float, float, float]:
    """Where a new retained node goes: the centre of the in-plane mass of ``node_ids``.

    Each node weighs the mean of its effective mass in the two in-plane
    translations (the same masses :func:`effective_nodal_masses` hands the
    solver, before any lumping onto this diaphragm); without mass it is the
    centroid. The coordinate across the plane is the nodes' mean, so the node
    lies in the floor.
    """
    a, b, _rot = IN_PLANE_SLOTS[perp_dirn]
    masses = effective_nodal_masses(project)
    coords = {n.id: n.coords for n in project.nodes}
    weights = {
        nid: 0.5 * float(masses[nid][a] + masses[nid][b]) for nid in node_ids if nid in masses
    }
    return centre_of_mass(coords, weights, node_ids)
