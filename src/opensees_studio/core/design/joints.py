"""Connections by joint topology: what frames into what, and which connection it takes.

At every joint the physical members (:mod:`core.design.members`) either pass
through or end. Each member end is a **connection**, classified by what it
frames into:

* a **beam** end into a column: *to the column flange* when the beam runs along
  the column's depth d (it meets the flange), *to the column web* otherwise;
* a **beam** end into a beam that goes on through the joint: *to a girder*;
* a **brace** end: *brace* (a gusset plate);
* a **column** end onto another column of a different section: *column splice*;
* a **column** end on a support: *column base*;
* anything else: *other*.

A beam end whose major-axis moment is released is a **simple** (shear)
connection; otherwise it is a **moment** connection. The suggested connection
follows the topology, simple or moment, and the seismic system of the design
basis (AISC 341 / 358): a shear tab for a simple beam end; the reduced beam
section (RBS) for an SMF or IMF moment end, a fully restrained moment
connection otherwise; a gusset plate for a brace; a splice for a column; a base
plate for a column base.

No Qt, no OpenSees.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from opensees_studio.core.design.members import DesignMember, design_members
from opensees_studio.core.geometry.local_axes import frame_local_axes

if TYPE_CHECKING:
    from opensees_studio.core.design.settings import DesignSettings
    from opensees_studio.core.project import Project

Topology = Literal[
    "beam to column flange",
    "beam to column web",
    "beam to girder",
    "brace",
    "column splice",
    "column base",
    "other",
]

SHEAR_TAB = "Single-plate shear connection (shear tab)"
RBS = "Reduced beam section, AISC 358 Ch. 5 (Design → Connections)"
FR_MOMENT = "Fully restrained moment connection (not checked here)"
GUSSET = "Gusset plate (Design → Gussets for SCBF)"
SPLICE = "Column splice (Design → Column Splices for SCBF)"
BASE = "Base plate (Design → Base Plates)"


@dataclass(frozen=True)
class Connection:
    """One member end at one joint, what it frames into and the connection it takes."""

    node_id: int
    element_id: int
    """The member's element at this joint."""
    end: str
    """``i`` or ``j`` of that element."""
    member_role: str
    topology: Topology
    simple: bool
    """The major-axis moment is released at this end (a shear connection)."""
    supporting_element: int | None
    """The column or girder the end frames into, None for a base or an unknown support."""
    suggested: str

    @property
    def key(self) -> tuple[int, str]:
        return self.element_id, self.end


def _major_moment(project: Project, element: Any) -> str:
    """``M3`` or ``M2``: the moment the section is stiffer for (2D: ``M3``)."""
    if project.ndm == 2:
        return "M3"
    section = next(
        (s for s in project.sections if s.id == getattr(element, "section_id", -1)), None
    )
    iy = float(getattr(section, "Iy", 0.0) or 0.0)
    iz = float(getattr(section, "Iz", 0.0) or 0.0)
    return "M2" if iy > iz else "M3"


def _released(project: Project, element: Any, end: str) -> bool:
    releases = getattr(element, "releases", None)
    if releases is None:
        return False
    return _major_moment(project, element) in releases.end(end).released


def _web_direction(project: Project, element: Any, coords: dict[int, np.ndarray]) -> np.ndarray:
    """Global direction of the column's depth d (its web), from its local axes."""
    axes = frame_local_axes(
        project.ndm,
        coords[int(element.nodes[0])].tolist(),
        coords[int(element.nodes[1])].tolist(),
        float(getattr(element, "local_axis_angle", 0.0) or 0.0),
    )
    if axes is None:
        return np.array([1.0, 0.0, 0.0])
    # M3 bends towards local y: a section stiffer for M3 has its depth along y.
    return axes[1] if _major_moment(project, element) == "M3" else axes[2]


def joint_connections(project: Project, settings: DesignSettings | None = None) -> list[Connection]:
    """Every member end of the frame, classified by topology, with its suggested connection."""
    from opensees_studio.core.design.settings import DesignSettings

    settings = settings or DesignSettings()
    roles = {m.element_id: m.role for m in settings.members if m.role is not None}
    members = design_members(project, roles)
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    nodes = {n.id: n for n in project.nodes}
    elements = {e.id: e for e in project.elements}
    seismic = settings.seismic_system

    # Which members end at each joint, and which pass through it.
    ending: dict[int, list[tuple[DesignMember, int, str]]] = {}
    passing: dict[int, list[DesignMember]] = {}
    for member in members:
        first, last = member.node_ids[0], member.node_ids[-1]
        for node, element_id in ((first, member.element_ids[0]), (last, member.element_ids[-1])):
            element = elements[element_id]
            end = "i" if int(element.nodes[0]) == node else "j"
            ending.setdefault(node, []).append((member, element_id, end))
        for node in member.node_ids[1:-1]:
            passing.setdefault(node, []).append(member)

    out: list[Connection] = []
    for node_id, ends in sorted(ending.items()):
        through = passing.get(node_id, [])
        columns_through = [m for m in through if m.role == "column"]
        beams_through = [m for m in through if m.role == "beam"]
        ending_columns = [(m, e, end) for m, e, end in ends if m.role == "column"]
        restrained = any(nodes[node_id].restraint[:3])
        if len(ends) == 1 and not through and not restrained:
            continue  # a free tip (a cantilever's end) connects to nothing
        for member, element_id, end in ends:
            element = elements[element_id]
            simple = _released(project, element, end)
            support: int | None = None
            topology: Topology = "other"
            if member.role == "beam":
                column = columns_through or [m for m, _e, _x in ending_columns]
                if column:
                    support_member = column[0]
                    support = support_member.element_ids[0]
                    web = _web_direction(project, elements[support], coords)
                    other = next(
                        n for n in (member.node_ids[1], member.node_ids[-2]) if n != node_id
                    )
                    direction = coords[other] - coords[node_id]
                    direction = direction / max(float(np.linalg.norm(direction)), 1e-12)
                    flange = abs(float(direction @ web)) >= 0.5 or project.ndm == 2
                    topology = "beam to column flange" if flange else "beam to column web"
                elif beams_through:
                    support = beams_through[0].element_ids[0]
                    topology = "beam to girder"
            elif member.role == "brace":
                topology = "brace"
            elif member.role == "column":
                far = coords[
                    member.node_ids[-1] if member.node_ids[0] == node_id else member.node_ids[0]
                ]
                upper = far[2] > coords[node_id][2]
                if restrained and upper:
                    topology = "column base"
                else:
                    others = [m for m, _e, _x in ending_columns if m is not member]
                    if others and upper:
                        # One splice per joint: reported on the column above it.
                        support = others[0].element_ids[0]
                        topology = "column splice"
                    else:
                        # The column below a splice, or a column top under a roof beam:
                        # the connection is the one listed for the other member.
                        continue
            out.append(
                Connection(
                    node_id=node_id,
                    element_id=element_id,
                    end=end,
                    member_role=member.role,
                    topology=topology,
                    simple=simple,
                    supporting_element=support,
                    suggested=_suggest(topology, simple, seismic),
                )
            )
    return out


def _suggest(topology: Topology, simple: bool, seismic: str) -> str:
    if topology in ("beam to column flange", "beam to column web", "beam to girder"):
        if simple:
            return SHEAR_TAB
        if topology == "beam to column flange" and seismic in ("SMF", "IMF"):
            return RBS
        return FR_MOMENT
    if topology == "brace":
        return GUSSET
    if topology == "column splice":
        return SPLICE
    if topology == "column base":
        return BASE
    return "No connection type for this topology"
