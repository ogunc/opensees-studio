"""Design members: physical members, their role and their unbraced lengths.

An analysis model often splits a member into several elements (a meshed beam, a
column with one element per storey). A member check must not take the element
as the member: a beam meshed into four elements would be checked with a quarter
of its unbraced length. This module rebuilds the physical members and finds
where each is braced, so the check can take the right lengths (AISC 360 E2,
F2.2):

* **Physical member** — a chain of frame elements, end to end, collinear (within
  1 degree) and of the same section. A chain goes through a joint where other
  members frame in, as long as it has exactly one collinear continuation there.
* **Bracing points** — the member's ends, and every interior joint that holds
  the member against moving along one of its local axes (y or z): another frame
  or truss element whose direction is within 60 degrees of that axis, a
  restraint of the translation along it, a rigid diaphragm whose plane contains
  it, or a shell whose plane contains it.
* **Unbraced length along an axis** — the distance between the two bracing
  points along that axis that enclose the element.

A 2D model has no out-of-plane information, so there every joint where another
element frames in, or a restraint, braces the member out of its plane too: the
usual assumption that the floors brace the frame.

The role (column, beam, brace) comes from the member's direction, unless the
design settings give one.

No Qt, no OpenSees.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from opensees_studio.core.geometry.elements import (
    FRAME_ELEMENT_CLASSES,
    SHELL_ELEMENT_CLASSES,
    CorotTrussElement,
    TrussElement,
)
from opensees_studio.core.geometry.local_axes import frame_local_axes

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

Role = Literal["column", "beam", "brace"]
ROLE_LABELS: dict[str, str] = {"column": "Column", "beam": "Beam", "brace": "Brace"}

COLLINEAR_COS = math.cos(math.radians(1.0))
"""Two elements continue one member when their axes are within 1 degree."""

BRACING_COS = 0.5
"""A direction braces an axis when it is within 60 degrees of it."""


def direction_role(project: Project, p_i: np.ndarray, p_j: np.ndarray) -> Role:
    """``column``, ``beam`` or ``brace`` from the member's direction.

    Within 20 % of vertical is a column; within 20 % of horizontal is a beam (a
    plan diagonal in 3D is a brace); anything else is a brace.
    """
    delta = np.asarray(p_j, dtype=float) - np.asarray(p_i, dtype=float)
    length = float(np.linalg.norm(delta))
    if length <= 0.0:
        return "beam"
    vertical = abs(float(delta[2])) / length
    if vertical >= 0.8:
        return "column"
    if vertical <= 0.2:
        horizontal = math.hypot(float(delta[0]), float(delta[1]))
        if project.ndm == 2 or min(abs(float(delta[0])), abs(float(delta[1]))) <= 0.2 * horizontal:
            return "beam"
    return "brace"


@dataclass(frozen=True)
class DesignMember:
    """One physical member: its elements in order along it, and where it is braced."""

    element_ids: tuple[int, ...]
    node_ids: tuple[int, ...]
    """The ``len(element_ids) + 1`` joints along the member, from its start."""
    stations: tuple[float, ...]
    """Distance of each joint from the member's start."""
    braced_y: tuple[bool, ...]
    """Per joint: held against moving along the member's local y."""
    braced_z: tuple[bool, ...]
    role: Role

    @property
    def id(self) -> int:
        """The member is known by its first element."""
        return self.element_ids[0]

    @property
    def length(self) -> float:
        return self.stations[-1]

    def segment(self, element_id: int, axis: Literal["y", "z"]) -> tuple[int, int]:
        """Joint indices of the bracing points along ``axis`` that enclose ``element_id``."""
        braced = self.braced_y if axis == "y" else self.braced_z
        k = self.element_ids.index(element_id)
        start = max(i for i in range(k + 1) if braced[i])
        end = min(i for i in range(k + 1, len(braced)) if braced[i])
        return start, end

    def unbraced_length(self, element_id: int, axis: Literal["y", "z"]) -> float:
        """Length between the bracing points along ``axis`` that enclose ``element_id``."""
        start, end = self.segment(element_id, axis)
        return self.stations[end] - self.stations[start]


@dataclass(frozen=True)
class _Frame:
    element: Any
    nodes: tuple[int, int]
    axes: tuple[np.ndarray, np.ndarray, np.ndarray]


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0.0 else vector


def design_members(project: Project, roles: Mapping[int, str] | None = None) -> list[DesignMember]:
    """Every physical member of the frame elements, with its bracing points.

    ``roles`` maps an element id to a role the user chose; the member takes the
    role of its first element that has one, else the role of its direction.
    """
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    nodes_by_id = {n.id: n for n in project.nodes}
    frames: dict[int, _Frame] = {}
    for element in project.elements:
        if not isinstance(element, FRAME_ELEMENT_CLASSES) or len(element.nodes) != 2:
            continue
        i, j = int(element.nodes[0]), int(element.nodes[1])
        axes = frame_local_axes(
            project.ndm,
            coords[i].tolist(),
            coords[j].tolist(),
            float(getattr(element, "local_axis_angle", 0.0) or 0.0),
        )
        if axes is not None:
            frames[element.id] = _Frame(element, (i, j), axes)

    at_node: dict[int, list[Any]] = {}
    for element in project.elements:
        for nid in getattr(element, "nodes", ()):
            at_node.setdefault(int(nid), []).append(element)

    def section_key(element: Any) -> Any:
        return getattr(element, "section_id", None) or getattr(element, "section_i_id", None)

    def continuation(frame: _Frame, node: int) -> _Frame | None:
        """The one collinear frame element of the same section beyond ``node``."""
        found = [
            frames[other.id]
            for other in at_node.get(node, ())
            if other.id != frame.element.id
            and other.id in frames
            and section_key(other) == section_key(frame.element)
            and abs(float(frames[other.id].axes[0] @ frame.axes[0])) >= COLLINEAR_COS
        ]
        return found[0] if len(found) == 1 else None

    diaphragm_normals: dict[int, list[np.ndarray]] = {}
    if project.diaphragms:
        from opensees_studio.core.diaphragms import constrained_node_ids

        for diaphragm in project.diaphragms:
            normal = np.zeros(3)
            normal[diaphragm.perp_dirn - 1] = 1.0
            for nid in (*constrained_node_ids(project, diaphragm), diaphragm.retained_node):
                diaphragm_normals.setdefault(int(nid), []).append(normal)

    def braces(node: int, member_elements: set[int], axis: np.ndarray) -> bool:
        """Whether something at ``node`` holds the member against moving along ``axis``."""
        others = [e for e in at_node.get(node, ()) if e.id not in member_elements]
        if project.ndm == 2 and abs(float(axis[1])) > 0.5:
            # Out of the plane of a 2D model: any member framing in, or a support.
            restrained = any(nodes_by_id[node].restraint[:3]) if node in nodes_by_id else False
            return bool(others) or restrained
        for other in others:
            other_nodes = [int(n) for n in getattr(other, "nodes", ())]
            if isinstance(other, SHELL_ELEMENT_CLASSES) and len(other_nodes) >= 3:
                points = [coords[n] for n in other_nodes[:3]]
                normal = _unit(np.cross(points[1] - points[0], points[2] - points[0]))
                if abs(float(normal @ axis)) <= math.sqrt(1.0 - BRACING_COS**2):
                    return True
                continue
            if not isinstance(other, (*FRAME_ELEMENT_CLASSES, TrussElement, CorotTrussElement)):
                continue
            far = next((n for n in other_nodes if n != node), None)
            if far is None:
                continue
            direction = _unit(coords[far] - coords[node])
            if abs(float(direction @ axis)) >= BRACING_COS:
                return True
        node_obj = nodes_by_id.get(node)
        if node_obj is not None:
            for slot in range(3):
                if node_obj.restraint[slot] and abs(float(axis[slot])) >= BRACING_COS:
                    return True
        for normal in diaphragm_normals.get(node, ()):
            if math.sqrt(max(0.0, 1.0 - float(axis @ normal) ** 2)) >= BRACING_COS:
                return True
        return False

    members: list[DesignMember] = []
    seen: set[int] = set()
    for element_id in sorted(frames):
        if element_id in seen:
            continue
        frame = frames[element_id]
        # Walk back to the start of the chain, then forward collecting it.
        start, start_node = frame, frame.nodes[0]
        guard = 0
        while (previous := continuation(start, start_node)) is not None and guard < len(frames):
            if previous.element.id == frame.element.id:
                break  # a closed loop of collinear elements: start anywhere
            start_node = previous.nodes[0] if previous.nodes[1] == start_node else previous.nodes[1]
            start = previous
            guard += 1
        chain = [start]
        nodes = [start_node, start.nodes[1] if start.nodes[0] == start_node else start.nodes[0]]
        while (following := continuation(chain[-1], nodes[-1])) is not None:
            if following.element.id in {f.element.id for f in chain}:
                break
            chain.append(following)
            nodes.append(
                following.nodes[1] if following.nodes[0] == nodes[-1] else following.nodes[0]
            )
        ids = tuple(f.element.id for f in chain)
        seen.update(ids)
        stations = [0.0]
        for a, b in itertools.pairwise(nodes):
            stations.append(stations[-1] + float(np.linalg.norm(coords[b] - coords[a])))
        # Local axes of the member: those of its first element.
        _x, y_axis, z_axis = chain[0].axes
        member_set = set(ids)
        last = len(nodes) - 1
        braced_y = tuple(
            k in (0, last) or braces(n, member_set, y_axis) for k, n in enumerate(nodes)
        )
        braced_z = tuple(
            k in (0, last) or braces(n, member_set, z_axis) for k, n in enumerate(nodes)
        )
        chosen = next((roles[i] for i in ids if roles and i in roles), None)
        role: Role = (
            chosen  # type: ignore[assignment]
            if chosen in ROLE_LABELS
            else direction_role(project, coords[nodes[0]], coords[nodes[-1]])
        )
        members.append(
            DesignMember(
                element_ids=ids,
                node_ids=tuple(nodes),
                stations=tuple(stations),
                braced_y=braced_y,
                braced_z=braced_z,
                role=role,
            )
        )
    return members


def members_by_element(members: list[DesignMember]) -> dict[int, DesignMember]:
    """Element id -> the physical member it belongs to."""
    return {eid: member for member in members for eid in member.element_ids}
