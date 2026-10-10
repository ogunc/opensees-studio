"""Meshing: subdividing members, subdividing shells, and joining them up.

Three operations that a structural modeller expects to be automatic, all of them
pure geometry on the project's own models:

* **Bars** (any two-node element) are split into equal pieces no longer than a
  target size. The pieces inherit the section, the material and the element's own
  fields, and the distributed loads of the original follow it — a bar cut in
  three must carry the same `q`, not a third of it.
* **Shells** (any four-node face) are subdivided ``m x n`` by bilinear
  interpolation in their own natural coordinates, which keeps the winding and
  works for a general quadrilateral, not only for a rectangle. The interior grid
  is built through a **shared node table seeded with the model's existing
  nodes**, so a shell's corners are the nodes that were already there, two meshed
  shells of the same size share their common edge, and a mesh never lands a new
  node on top of an old one.
* **The joins** are what make a mesh usable: a bar is split at every node that
  lies on it (so a frame that meets a slab edge is connected there), and bars are
  split where they cross each other. Both are done with a tolerance the caller
  owns, and both reuse the node that already exists instead of creating one.

Everything here is a *plan* — the nodes and elements to add, the elements to
remove, and the notes of what was skipped — so it can be tested without touching
a project and applied by one command in one undo step. This module is part of
``core``: no Qt, no openseespy.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from opensees_studio.core.geometry.node import Node, Restraint6
from opensees_studio.core.project import Project

#: A node with nothing restrained.
FREE_RESTRAINT: Restraint6 = (False, False, False, False, False, False)


def inherit_restraint(first: Restraint6, second: Restraint6) -> Restraint6:
    """The DOF both of ``first`` and ``second`` have restrained."""
    return (
        bool(first[0]) and bool(second[0]),
        bool(first[1]) and bool(second[1]),
        bool(first[2]) and bool(second[2]),
        bool(first[3]) and bool(second[3]),
        bool(first[4]) and bool(second[4]),
        bool(first[5]) and bool(second[5]),
    )


#: Two points closer than this are the same point, in project units. Small
#: enough for millimetre models and large enough for floating-point noise.
COINCIDENT_TOLERANCE = 1e-6

Point3 = tuple[float, float, float]


class MeshError(ValueError):
    """The requested mesh cannot be built."""


@dataclass
class MeshPlan:
    """Nodes and elements to add, elements to remove, and what was left out."""

    new_nodes: list[Node] = field(default_factory=list)
    new_elements: list[Any] = field(default_factory=list)
    removed_element_ids: list[int] = field(default_factory=list)
    #: removed element id -> the elements that replace it (their loads follow).
    replacements: dict[int, list[int]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.new_nodes or self.new_elements or self.removed_element_ids)

    def summary(self) -> str:
        if self.is_empty:
            return self.notes[0] if self.notes else "Nothing to mesh."
        parts = []
        if self.new_elements:
            parts.append(f"+{len(self.new_elements)} element(s)")
            parts.append(f"+{len(self.new_nodes)} node(s)")
        if self.removed_element_ids:
            parts.append(f"-{len(self.removed_element_ids)} element(s) replaced")
        text = ", ".join(parts) + "."
        if self.notes:
            text += " " + " ".join(self.notes)
        return text


class _Working:
    """A model being meshed: the project's nodes and elements plus what we add.

    The stages chain through this, so "mesh the shells and then join the bars to
    the new edges" sees the nodes the first stage created.
    """

    def __init__(self, project: Project) -> None:
        self.nodes: list[Node] = list(project.nodes)
        self.elements: list[Any] = list(project.elements)
        self.removed: set[int] = set()
        self.replacements: dict[int, list[int]] = defaultdict(list)
        self.added_nodes: dict[int, Node] = {}
        self.added_elements: dict[int, Any] = {}
        self.notes: list[str] = []
        self.refused: list[str] = []
        self.next_node = project.next_node_id()
        self.next_element = project.next_element_id()
        self._node_by_id: dict[int, Node] = {node.id: node for node in self.nodes}
        self._by_cell: dict[tuple[int, int, int], list[int]] = defaultdict(list)
        self._points: dict[int, Point3] = {}
        for node in self.nodes:
            self._index(node.id, node.coords)

    # ── node table ──────────────────────────────────────────────────
    def _cell(self, point: Point3, tolerance: float) -> tuple[int, int, int]:
        step = tolerance or 1.0
        return (
            math.floor(point[0] / step),
            math.floor(point[1] / step),
            math.floor(point[2] / step),
        )

    def _index(self, node_id: int, point: Point3, tolerance: float = COINCIDENT_TOLERANCE) -> None:
        self._by_cell[self._cell(point, tolerance)].append(node_id)
        self._points[node_id] = point

    def node_at(
        self,
        point: Point3,
        tolerance: float = COINCIDENT_TOLERANCE,
        *,
        on_edge_of: tuple[int, int] | None = None,
    ) -> int:
        """The id of a node at ``point``, creating one when there is none.

        ``on_edge_of`` names the two nodes a new node is inserted *between along a
        supported edge* (a shell's edge). The new node then inherits the DOFs both
        of them have restrained, so meshing a slab whose edge is supported does not
        quietly unsupport the middle of that edge. Two things it deliberately does
        not do: interior mesh nodes are free (nothing is inherited), and a node
        created at a crossing of two members is free (a crossing is not a support).
        """
        cell = self._cell(point, tolerance)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for node_id in self._by_cell.get(
                        (cell[0] + dx, cell[1] + dy, cell[2] + dz), ()
                    ):
                        other = self._points[node_id]
                        if (
                            abs(other[0] - point[0]) <= tolerance
                            and abs(other[1] - point[1]) <= tolerance
                            and abs(other[2] - point[2]) <= tolerance
                        ):
                            return node_id
        restraint = FREE_RESTRAINT
        if on_edge_of is not None:
            first, second = (self._node_by_id[node_id] for node_id in on_edge_of)
            restraint = inherit_restraint(first.restraint, second.restraint)
        node = Node(id=self.next_node, coords=point, restraint=restraint)
        self.next_node += 1
        self.nodes.append(node)
        self._node_by_id[node.id] = node
        self.added_nodes[node.id] = node
        self._index(node.id, point, tolerance)
        return node.id

    def replace(self, element: Any, chunks: list[list[int]]) -> None:
        """Replace ``element`` with one element per chunk of nodes."""
        self.removed.add(element.id)
        for nodes in chunks:
            new = element.model_copy(update={"id": self.next_element, "nodes": tuple(nodes)})
            self.next_element += 1
            self.elements.append(new)
            self.added_elements[new.id] = new
            self.replacements[element.id].append(new.id)

    def plan(self) -> MeshPlan:
        return MeshPlan(
            new_nodes=[self.added_nodes[key] for key in sorted(self.added_nodes)],
            new_elements=[self.added_elements[key] for key in sorted(self.added_elements)],
            removed_element_ids=sorted(self.removed),
            replacements={key: value for key, value in self.replacements.items()},
            notes=self.notes,
            refused=self.refused,
        )


# ──────────────────────────── helpers ────────────────────────────
def _coords(node_id: int, lookup: dict[int, Node]) -> np.ndarray:
    return np.asarray(lookup[node_id].coords, dtype=float)


def _segment_parameter(
    point: np.ndarray, start: np.ndarray, end: np.ndarray
) -> tuple[float, float]:
    """``(t, distance)`` of ``point`` on the segment ``start`` -> ``end``."""
    direction = end - start
    length_squared = float(direction @ direction)
    if length_squared <= 0.0:
        return 0.0, float(np.linalg.norm(point - start))
    t = float((point - start) @ direction) / length_squared
    closest = start + min(max(t, 0.0), 1.0) * direction
    return t, float(np.linalg.norm(point - closest))


def _closest_between_segments(
    p0: np.ndarray, p1: np.ndarray, q0: np.ndarray, q1: np.ndarray
) -> tuple[float, float, float]:
    """``(s, t, distance)`` between two segments (the standard clamped solution)."""
    u, v, w = p1 - p0, q1 - q0, p0 - q0
    a, b, c = float(u @ u), float(u @ v), float(v @ v)
    d, e = float(u @ w), float(v @ w)
    denominator = a * c - b * b
    s = t = 0.0
    if denominator > 1e-18:  # not parallel
        s = (b * e - c * d) / denominator
        t = (a * e - b * d) / denominator
    s = min(max(s, 0.0), 1.0)
    t = min(max(t, 0.0), 1.0)
    # Refine: with one parameter clamped the other is the projection.
    s = min(max((b * t - d) / a, 0.0), 1.0) if a > 1e-18 else 0.0
    t = min(max((b * s + e) / c, 0.0), 1.0) if c > 1e-18 else 0.0
    distance = float(np.linalg.norm((p0 + s * u) - (q0 + t * v)))
    return s, t, distance


def _bar_like(element: Any) -> bool:
    return len(element.nodes) == 2


def _face_like(element: Any) -> bool:
    return len(element.nodes) == 4


def _edge_pair(
    i: int, j: int, m: int, n: int, *, corners: tuple[int, int, int, int]
) -> tuple[int, int] | None:
    """The two corner nodes of the shell edge a grid point lies on, if any."""
    c0, c1, c2, c3 = corners
    if j == 0 and 0 < i < m:
        return c0, c1
    if i == m and 0 < j < n:
        return c1, c2
    if j == n and 0 < i < m:
        return c3, c2
    if i == 0 and 0 < j < n:
        return c0, c3
    return None  # a corner (an existing node) or an interior point


def _target_divisions(length: float, target: float) -> int:
    if target <= 0.0:
        raise MeshError("The target size must be positive.")
    if length <= target:
        return 1
    return max(1, math.ceil(length / target - 1e-9))


# ──────────────────────────── bars ────────────────────────────
def mesh_bars(
    project: Project,
    element_ids: set[int] | None = None,
    *,
    target_size: float,
    working: _Working | None = None,
) -> MeshPlan:
    """Split the selected bars into pieces no longer than ``target_size``."""
    state = working or _Working(project)
    lookup = {node.id: node for node in state.nodes}
    selected = [
        element
        for element in state.elements
        if element.id not in state.removed
        and _bar_like(element)
        and (element_ids is None or element.id in element_ids)
    ]
    split = 0
    for element in selected:
        start, end = _coords(element.nodes[0], lookup), _coords(element.nodes[1], lookup)
        length = float(np.linalg.norm(end - start))
        divisions = _target_divisions(length, target_size)
        if divisions == 1:
            continue
        interior = [
            state.node_at(tuple(start + (end - start) * (index / divisions)))
            for index in range(1, divisions)
        ]
        chain = [element.nodes[0], *interior, element.nodes[1]]
        state.replace(element, [[chain[i], chain[i + 1]] for i in range(len(chain) - 1)])
        lookup = {node.id: node for node in state.nodes}
        split += 1
    state.notes.append(
        f"{split} bar(s) split at {target_size:g}." if split else "No bar longer than the target."
    )
    return state.plan()


# ──────────────────────────── shells ────────────────────────────
def mesh_shells(
    project: Project,
    element_ids: set[int] | None = None,
    *,
    target_size: float,
    working: _Working | None = None,
) -> MeshPlan:
    """Subdivide the selected shells into quads no larger than ``target_size``.

    The subdivision is ``m x n`` in the element's natural coordinates, computed
    from the mean length of the two pairs of opposite edges, and the interior
    grid comes from the bilinear map of the four corners — so a general
    quadrilateral meshes without leaving its own edges, and the winding (which a
    shell's normal depends on) is preserved.
    """
    state = working or _Working(project)
    lookup = {node.id: node for node in state.nodes}
    selected = [
        element
        for element in state.elements
        if element.id not in state.removed
        and _face_like(element)
        and (element_ids is None or element.id in element_ids)
    ]
    meshed = 0
    for element in selected:
        corners = [_coords(node_id, lookup) for node_id in element.nodes]
        p0, p1, p2, p3 = corners
        across = 0.5 * (float(np.linalg.norm(p1 - p0)) + float(np.linalg.norm(p2 - p3)))
        down = 0.5 * (float(np.linalg.norm(p3 - p0)) + float(np.linalg.norm(p2 - p1)))
        m = _target_divisions(across, target_size)
        n = _target_divisions(down, target_size)
        if m == 1 and n == 1:
            continue
        c0, c1, c2, c3 = element.nodes  # the shell's own corners, in winding order
        grid: list[list[int]] = []
        for j in range(n + 1):
            eta = j / n
            row: list[int] = []
            for i in range(m + 1):
                xi = i / m
                point = (
                    (1 - xi) * (1 - eta) * p0
                    + xi * (1 - eta) * p1
                    + xi * eta * p2
                    + (1 - xi) * eta * p3
                )
                edge = _edge_pair(i, j, m, n, corners=(c0, c1, c2, c3))
                row.append(state.node_at(tuple(point), on_edge_of=edge))
            grid.append(row)
        cells = [
            [
                grid[j][i],
                grid[j][i + 1],
                grid[j + 1][i + 1],
                grid[j + 1][i],
            ]
            for j in range(n)
            for i in range(m)
        ]
        state.replace(element, cells)
        lookup = {node.id: node for node in state.nodes}
        meshed += 1
    state.notes.append(
        f"{meshed} shell(s) subdivided at {target_size:g}."
        if meshed
        else "No shell larger than the target."
    )
    return state.plan()


# ──────────────────────────── the joins ────────────────────────────
def split_bars_at_nodes(
    project: Project,
    element_ids: set[int] | None = None,
    *,
    tolerance: float = COINCIDENT_TOLERANCE,
    working: _Working | None = None,
) -> MeshPlan:
    """Split bars at every node that lies inside them.

    This is the join that makes a mesh conforming: a column whose top lands in the
    middle of a beam's span, or a frame drawn across a slab edge, gets a node
    there instead of passing by.
    """
    state = working or _Working(project)
    lookup = {node.id: node for node in state.nodes}
    candidates = [node for node in state.nodes]
    split = 0
    for element in [
        element
        for element in state.elements
        if element.id not in state.removed
        and _bar_like(element)
        and (element_ids is None or element.id in element_ids)
    ]:
        start, end = _coords(element.nodes[0], lookup), _coords(element.nodes[1], lookup)
        hits: list[tuple[float, int]] = []
        for node in candidates:
            if node.id in element.nodes:
                continue
            point = np.asarray(node.coords, dtype=float)
            t, distance = _segment_parameter(point, start, end)
            if distance <= tolerance and tolerance < t < 1.0 - tolerance:
                hits.append((t, node.id))
        if not hits:
            continue
        chain = [element.nodes[0]]
        chain.extend(node_id for _, node_id in sorted(hits))
        chain.append(element.nodes[1])
        if len(chain) <= 2:
            continue
        state.replace(element, [[chain[i], chain[i + 1]] for i in range(len(chain) - 1)])
        split += 1
    state.notes.append(
        f"{split} bar(s) split at nodes lying on them." if split else "No node lies on a bar."
    )
    return state.plan()


def split_bars_at_crossings(
    project: Project,
    element_ids: set[int] | None = None,
    *,
    tolerance: float = COINCIDENT_TOLERANCE,
    working: _Working | None = None,
) -> MeshPlan:
    """Split crossing bars at the point where they meet.

    Two bars that cross without a node at the crossing are two members passing
    each other: nothing is connected there, which is almost never what was meant.
    Both are split, so the crossing becomes a shared node.
    """
    state = working or _Working(project)
    lookup = {node.id: node for node in state.nodes}
    bars = [
        element
        for element in state.elements
        if element.id not in state.removed
        and _bar_like(element)
        and (element_ids is None or element.id in element_ids)
    ]
    cuts: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for index, first in enumerate(bars):
        for second in bars[index + 1 :]:
            if set(first.nodes) & set(second.nodes):
                continue  # already share a node: they meet at it
            a0, a1 = _coords(first.nodes[0], lookup), _coords(first.nodes[1], lookup)
            b0, b1 = _coords(second.nodes[0], lookup), _coords(second.nodes[1], lookup)
            s, t, distance = _closest_between_segments(a0, a1, b0, b1)
            if distance > tolerance or not (tolerance < s < 1 - tolerance):
                continue
            if not (tolerance < t < 1 - tolerance):
                continue
            point = (a0 + s * (a1 - a0) + b0 + t * (b1 - b0)) / 2.0
            node_id = state.node_at(tuple(point), tolerance)
            cuts[first.id].append((s, node_id))
            cuts[second.id].append((t, node_id))
            lookup = {node.id: node for node in state.nodes}

    for element in bars:
        hits = cuts.get(element.id)
        if not hits:
            continue
        chain = [element.nodes[0], *(node_id for _, node_id in sorted(hits)), element.nodes[1]]
        if len(chain) <= 2:
            continue
        state.replace(element, [[chain[i], chain[i + 1]] for i in range(len(chain) - 1)])
    state.notes.append(
        f"{sum(1 for e in bars if cuts.get(e.id))} bar(s) split at crossings."
        if cuts
        else "No crossing bars."
    )
    return state.plan()


# ──────────────────────────── the whole thing ────────────────────────────
def auto_mesh(
    project: Project,
    element_ids: set[int] | None = None,
    *,
    target_size: float,
    bars: bool = True,
    shells: bool = True,
    at_nodes: bool = True,
    at_crossings: bool = True,
    tolerance: float = COINCIDENT_TOLERANCE,
) -> MeshPlan:
    """Mesh the selection and join it up, in the order the operations depend on.

    Shells first (a bar should be joined to the *meshed* edge, not to the coarse
    one), then the crossings (which may put a node on a bar that is then meshed
    further), then the bars, and finally the nodes lying on them. Every stage
    feeds the next through one working model, so the plan is consistent.
    """
    state = _Working(project)
    if shells:
        mesh_shells(project, element_ids, target_size=target_size, working=state)
    if at_crossings:
        split_bars_at_crossings(project, element_ids, tolerance=tolerance, working=state)
    if bars:
        mesh_bars(project, element_ids, target_size=target_size, working=state)
    if at_nodes:
        split_bars_at_nodes(project, element_ids, tolerance=tolerance, working=state)
    plan = state.plan()
    plan.notes = state.notes
    return plan
