"""Section cuts: the resultant force through a part of the model (SAP2000 "section cuts").

A :class:`SectionCut` names a group (:mod:`core.groups`). Its resultant is the
sum of the end forces of the group's elements at the group's joints, with the
moments taken about the centroid of those joints (or a typed point):

* a column group with its base joints gives the force in the columns at the
  base: the storey or wall shear, the axial load of a pier;
* a slab strip with the joints along one edge gives the force through that edge.

Sign: the cut reports what the elements pass *into* the cut joints, i.e. minus
the sum of OpenSees' ``eleForce`` (the forces the joints apply to the elements),
which equals the resultant of the loads on the elements' side of the cut. A
cantilever column carrying a lateral load P and a weight W at its top, cut at
its base, reports +P and -W.

Components are global, in storage order (Fx, Fy, Fz, Mx, My, Mz); a 2D model
fills Fx, Fz, My (:mod:`core.plane`). No Qt, no OpenSees.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from pydantic import Field

from opensees_studio.core._base import Entity
from opensees_studio.core.plane import from_solver_dofs

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

COMPONENTS = ("Fx", "Fy", "Fz", "Mx", "My", "Mz")


class SectionCut(Entity):
    """A cut through the elements and joints of a group."""

    group_id: int = Field(..., gt=0, description="Group whose elements and joints form the cut.")
    centre: tuple[float, float, float] | None = Field(
        default=None,
        description="Point the moments are taken about; None = centroid of the cut joints.",
    )


@dataclass(frozen=True)
class CutGeometry:
    """What the runner needs to evaluate a cut: element positions and the moment centre.

    ``members`` pairs an element id with the positions (in ``element.nodes``) of
    its joints that belong to the cut.
    """

    cut_id: int
    members: tuple[tuple[int, tuple[int, ...]], ...]
    joints: tuple[int, ...]
    centre: tuple[float, float, float]


def cut_geometry(project: Project, cut: SectionCut) -> CutGeometry:
    """The elements and joints of ``cut``'s group, limited to what the model holds."""
    group = next((g for g in project.groups if g.id == cut.group_id), None)
    node_ids = {n.id for n in project.nodes}
    joints = set(group.node_ids) & node_ids if group is not None else set()
    element_ids = set(group.element_ids) if group is not None else set()
    cut_elements = [
        e for e in project.elements if e.id in element_ids and any(n in joints for n in e.nodes)
    ]
    members = tuple(
        (e.id, tuple(i for i, nid in enumerate(e.nodes) if nid in joints)) for e in cut_elements
    )
    used = sorted({nid for e in cut_elements for nid in e.nodes if nid in joints})
    if cut.centre is not None:
        centre = cut.centre
    elif used:
        coords = {n.id: n.coords for n in project.nodes}
        mean = np.mean([coords[nid] for nid in used], axis=0)
        centre = (float(mean[0]), float(mean[1]), float(mean[2]))
    else:
        centre = (0.0, 0.0, 0.0)
    return CutGeometry(cut.id, members, tuple(used), centre)


def section_cuts(project: Project) -> list[CutGeometry]:
    """The geometry of every section cut of the project."""
    return [cut_geometry(project, cut) for cut in project.section_cuts]


def cut_resultant(
    geometry: CutGeometry,
    element_nodes: Mapping[int, Sequence[int]],
    element_forces: Mapping[int, Sequence[float]],
    node_coords: Mapping[int, Sequence[float]],
    ndm: int,
    ndf: int,
) -> np.ndarray:
    """The six global components of the cut from OpenSees ``eleForce`` vectors.

    An element with fewer values per node than ``ndf`` (a truss) contributes
    translations only.
    """
    force = np.zeros(3)
    moment = np.zeros(3)
    centre = np.asarray(geometry.centre, dtype=float)
    for element_id, positions in geometry.members:
        values = np.asarray(element_forces.get(element_id, ()), dtype=float)
        nodes = element_nodes[element_id]
        if values.size == 0 or values.size % len(nodes):
            continue
        per_node = values.size // len(nodes)
        layout_ndf = ndf if per_node >= ndf else ndm
        for position in positions:
            chunk = values[position * per_node : position * per_node + layout_ndf]
            g = np.asarray(from_solver_dofs(chunk, ndm, layout_ndf))
            arm = np.asarray(node_coords[nodes[position]], dtype=float) - centre
            force += g[:3]
            moment += g[3:] + np.cross(arm, g[:3])
    result = -np.concatenate([force, moment])
    if ndm == 2:
        keep = (0, 2, 4) if ndf == 3 else (0, 2)
        result = np.array([v if i in keep else 0.0 for i, v in enumerate(result)])
    elif ndf == 3:
        result[3:] = 0.0
    return result


def cut_problems(project: Project) -> list[str]:
    """Reference problems of the section cuts: a missing group."""
    group_ids = {g.id for g in project.groups}
    return [
        f"Section cut {cut.name or cut.id} uses missing group {cut.group_id}."
        for cut in project.section_cuts
        if cut.group_id not in group_ids
    ]
