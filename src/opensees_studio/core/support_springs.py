"""Distributed support springs: along a frame, along a shell edge, over a shell's area.

Three ways to rest a structure on something flexible — a beam on an elastic
foundation, the edge of a slab on a wall, a raft or a tank on soil (Winkler) —
each with its stiffness per unit length or per unit area. They are handed to the
nodes the way SAP2000 does it, by **tributary length or area**: a node takes the
stiffness times ``∫N_i dL`` (half of each segment it ends) or ``∫N_i dA``
(``quad_tributary_areas``), so a finer mesh distributes the support more evenly.

Every spring acts along one direction and has a **side**: where the supporting
medium is. ``side="negative"`` puts it on the negative side of the direction
(soil under a slab whose spring acts along +Z, or behind the face of a shell
opposite its normal), ``"positive"`` on the positive side. That fixes what
*compression* means — the structure moving into the medium — and therefore what
``behaviour`` does:

- ``"both"`` — linear, resists in both senses;
- ``"compression"`` — compression only: the support lets go when the structure
  lifts off (soil, a bearing pad);
- ``"tension"`` — tension only: a tie that slackens when pushed.

The one-sided behaviours are nonlinear: the runner solves the cases they take
part in by Newton iteration.

:func:`nodal_springs` turns all of it into one spring per node, direction and
behaviour — what the runner hangs off a grounded hidden node, and what the
model check counts as support. No Qt, no OpenSees.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.geometry.quadrature import quad_tributary_areas

SpringBehaviour = Literal["both", "compression", "tension"]
Side = Literal["negative", "positive"]

BEHAVIOURS: tuple[tuple[str, SpringBehaviour], ...] = (
    ("Linear (tension and compression)", "both"),
    ("Compression only", "compression"),
    ("Tension only", "tension"),
)

_GLOBAL = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}


class _ProjectLike(Protocol):
    """What the spring helpers need of a Project, without importing it back."""

    ndm: Any
    nodes: Any
    elements: Any
    area_springs: list[Any]
    line_springs: list[Any]
    edge_springs: list[Any]


class _Spring(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    element_id: PositiveInt
    side: Side = Field(
        default="negative",
        description="Where the supporting medium is, relative to the direction.",
    )
    behaviour: SpringBehaviour = "both"


class AreaSpring(_Spring):
    """A spring bed under a shell (Winkler): stiffness per unit area (force / length³)."""

    stiffness: PositiveFloat = Field(..., description="Force per length per area.")
    direction: Literal["normal", "X", "Y", "Z"] = Field(
        default="normal",
        description="The shell normal (local 3, right-hand turn of nodes 1-2-3-4) or a global axis.",
    )


class LineSpring(_Spring):
    """A spring bed along a frame member: stiffness per unit length (force / length²)."""

    stiffness: PositiveFloat = Field(..., description="Force per length per length.")
    direction: Literal["1", "2", "3", "X", "Y", "Z"] = Field(
        default="Z", description="The member's local 1, 2, 3 or a global axis."
    )


class EdgeSpring(_Spring):
    """A spring bed along one edge of a shell: stiffness per unit length (force / length²)."""

    edge: int = Field(..., ge=1, le=4, description="Edge k runs from node k to node k+1 (4 → 1).")
    stiffness: PositiveFloat = Field(..., description="Force per length per length.")
    direction: Literal["normal", "X", "Y", "Z"] = Field(
        default="Z", description="The shell normal or a global axis."
    )


class SpringError(ValueError):
    """A distributed spring on an element that cannot carry it."""


@dataclass(frozen=True)
class NodalSpring:
    """One spring to ground at a node, along a unit direction ``d``.

    ``d`` points from the supporting medium to the structure: the structure
    moving along ``-d`` compresses the spring.
    """

    node_id: int
    direction: tuple[float, float, float]
    stiffness: float
    behaviour: SpringBehaviour


def _unit(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length <= 0.0:
        raise SpringError("A spring direction has no length.")
    return vector / length


def _towards_structure(axis: np.ndarray, side: Side) -> np.ndarray:
    """The direction from the medium to the structure: away from the medium's side."""
    return -axis if side == "positive" else axis


def _shell_normal(points: np.ndarray) -> np.ndarray:
    return _unit(np.cross(points[2] - points[0], points[3] - points[1]))


def _shares(project: _ProjectLike) -> Iterable[tuple[int, np.ndarray, float, SpringBehaviour]]:
    """``(node, direction, stiffness)`` contributions of every distributed spring."""
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    elements = {e.id: e for e in project.elements}

    def element(spring: _Spring, corners: int) -> tuple[object, np.ndarray]:
        el = elements.get(spring.element_id)
        if el is None or len(el.nodes) != corners:
            kind = "shell" if corners == 4 else "frame member"
            raise SpringError(f"Spring on element {spring.element_id}: not a {kind}.")
        return el, np.array([coords[n] for n in el.nodes])

    for spring in project.area_springs:
        el, points = element(spring, 4)
        axis = (
            _shell_normal(points)
            if spring.direction == "normal"
            else np.array(_GLOBAL[spring.direction])
        )
        d = _towards_structure(axis, spring.side)
        for nid, area in zip(el.nodes, quad_tributary_areas(points), strict=True):  # type: ignore[attr-defined]
            yield nid, d, spring.stiffness * float(area), spring.behaviour

    for line in project.line_springs:
        el, points = element(line, 2)
        if line.direction in _GLOBAL:
            axis = np.array(_GLOBAL[line.direction])
        else:
            axes = frame_local_axes(
                project.ndm,
                points[0].tolist(),
                points[1].tolist(),
                float(getattr(el, "local_axis_angle", 0.0) or 0.0),
            )
            if axes is None:
                raise SpringError(f"Line spring on element {line.element_id}: zero length.")
            axis = axes[int(line.direction) - 1]
        d = _towards_structure(axis, line.side)
        half = 0.5 * float(np.linalg.norm(points[1] - points[0]))
        for nid in el.nodes:  # type: ignore[attr-defined]
            yield nid, d, line.stiffness * half, line.behaviour

    for edge in project.edge_springs:
        el, points = element(edge, 4)
        a, b = edge.edge - 1, edge.edge % 4
        axis = (
            _shell_normal(points)
            if edge.direction == "normal"
            else np.array(_GLOBAL[edge.direction])
        )
        d = _towards_structure(axis, edge.side)
        half = 0.5 * float(np.linalg.norm(points[b] - points[a]))
        for k in (a, b):
            yield el.nodes[k], d, edge.stiffness * half, edge.behaviour  # type: ignore[attr-defined]


def nodal_springs(project: _ProjectLike) -> list[NodalSpring]:
    """Every distributed spring as springs at the nodes, one per node, direction, behaviour.

    Contributions along the same direction (to 1e-9) with the same behaviour add
    up, so a node shared by four shells of a raft gets one spring.
    """
    merged: dict[tuple[int, tuple[float, ...], str], tuple[np.ndarray, float]] = {}
    for nid, d, k, behaviour in _shares(project):
        key = (nid, tuple(round(float(c), 9) for c in d), behaviour)
        previous = merged.get(key)
        merged[key] = (d, k + (previous[1] if previous else 0.0))
    return [
        NodalSpring(
            node_id=nid,
            direction=(float(d[0]), float(d[1]), float(d[2])),
            stiffness=k,
            behaviour=behaviour,  # type: ignore[arg-type]
        )
        for (nid, _, behaviour), (d, k) in merged.items()
        if k > 0.0
    ]


def has_one_sided_springs(project: _ProjectLike) -> bool:
    """True when a compression-only or tension-only spring makes the model nonlinear."""
    return any(
        s.behaviour != "both"
        for s in (*project.area_springs, *project.line_springs, *project.edge_springs)
    )


def total_spring_count(project: _ProjectLike) -> int:
    return len(project.area_springs) + len(project.line_springs) + len(project.edge_springs)


# ──────────────────────────── keeping springs in step with the elements ────────────────────────────
def _spring_lists(project: _ProjectLike) -> tuple[list[Any], list[Any], list[Any]]:
    """The three spring lists, typed loosely so one loop can walk them all."""
    return project.area_springs, project.line_springs, project.edge_springs


def prune_support_springs(project: _ProjectLike) -> bool:
    """Drop the springs of elements the model no longer has; ``True`` when one went."""
    present = {e.id for e in project.elements}
    changed = False
    for springs in _spring_lists(project):
        kept = [s for s in springs if s.element_id in present]
        if len(kept) != len(springs):
            springs[:] = kept
            changed = True
    return changed


def copy_support_springs(project: _ProjectLike, element_mapping: dict[int, int]) -> None:
    """Give each copied element (source id → copy id) its source's springs."""
    for springs in _spring_lists(project):
        springs.extend(
            spring.model_copy(update={"element_id": element_mapping[spring.element_id]})
            for spring in list(springs)
            if spring.element_id in element_mapping
        )


def springs_follow_pieces(
    project: _ProjectLike,
    replacements: dict[int, list[int]],
    original_corners: dict[int, np.ndarray],
    tolerance: float,
) -> None:
    """After a mesh: the springs of a replaced element go to its pieces.

    An area or line spring is the same per unit area or length on every piece. An
    edge spring goes to the edges of the pieces that lie on the original edge
    (``original_corners`` holds each replaced shell's corners).
    """
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    elements = {e.id: e for e in project.elements}
    area, line, edges = _spring_lists(project)
    for springs in (area, line):
        carried: list[Any] = []
        for spring in springs:
            pieces = replacements.get(spring.element_id)
            if pieces is None:
                carried.append(spring)
            else:
                carried.extend(spring.model_copy(update={"element_id": p}) for p in pieces)
        springs[:] = carried
    carried_edges: list[Any] = []
    for spring in edges:
        pieces = replacements.get(spring.element_id)
        corners = original_corners.get(spring.element_id)
        if pieces is None or corners is None:
            carried_edges.append(spring)
            continue
        a, b = corners[spring.edge - 1], corners[spring.edge % 4]
        axis = b - a
        length2 = float(axis @ axis)

        def on_edge(
            p: np.ndarray, a: np.ndarray = a, axis: np.ndarray = axis, length2: float = length2
        ) -> bool:
            t = float((p - a) @ axis) / length2
            return -1e-9 <= t <= 1 + 1e-9 and float(np.linalg.norm(a + t * axis - p)) <= tolerance

        for piece_id in pieces:
            piece = elements.get(piece_id)
            if piece is None or len(piece.nodes) != 4:
                continue
            nodes = piece.nodes
            for k in range(4):
                if on_edge(coords[nodes[k]]) and on_edge(coords[nodes[(k + 1) % 4]]):
                    carried_edges.append(
                        spring.model_copy(update={"element_id": piece_id, "edge": k + 1})
                    )
    edges[:] = carried_edges
