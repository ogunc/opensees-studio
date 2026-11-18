"""Connectivity: what in a model looks joined on screen and is not.

Three faults that solve without an error and give a wrong structure:

* a **loose joint** — a node that no element, constraint, rigid link or
  diaphragm uses (left over after a delete, or drawn and never connected);
* a **joint on a bar** — a node that lies inside a frame or truss without being
  one of its ends: a column that "meets" a beam mid-span but passes by it;
* a **joint on a shell edge** — a node inside an edge of a shell, not at a
  corner: the bar or shell that ends there hangs, the edge does not carry it.

The first two are fixed by Edit → Merge Joints and Edit → Divide Frames at
Joints; the last needs the shell subdivided (Edit → Mesh) so a corner lands on
the joint. Pure: no Qt, no OpenSeesPy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from opensees_studio.core.duplicates import default_tolerance
from opensees_studio.core.geometry.elements import (
    FRAME_ELEMENT_CLASSES,
    CorotTrussElement,
    TrussElement,
)
from opensees_studio.core.project import Project


def _bar(element: object) -> bool:
    """A two-node element that spans a length: a frame or a truss.

    Zero-length elements, bearings and links join coincident nodes and are never
    split, so they are not bars here.
    """
    return isinstance(element, (*FRAME_ELEMENT_CLASSES, TrussElement, CorotTrussElement))


def _parameter(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> tuple[float, float]:
    """``(t, distance)`` of ``point`` to the segment ``start``-``end`` (t along it)."""
    axis = end - start
    length_sq = float(axis @ axis)
    if length_sq == 0.0:
        return 0.0, float(np.linalg.norm(point - start))
    t = float((point - start) @ axis) / length_sq
    t = min(max(t, 0.0), 1.0)
    return t, float(np.linalg.norm(start + t * axis - point))


@dataclass
class ConnectivityReport:
    """The faults found, each as ids the Select menu can pick."""

    tolerance: float
    loose_joints: list[int] = field(default_factory=list)
    joints_on_bars: list[tuple[int, int]] = field(default_factory=list)  # (element, node)
    joints_on_shell_edges: list[tuple[int, int]] = field(default_factory=list)  # (shell, node)

    @property
    def is_clean(self) -> bool:
        return not (self.loose_joints or self.joints_on_bars or self.joints_on_shell_edges)

    def summary(self) -> str:
        if self.is_clean:
            return "Every joint is connected."
        parts = []
        if self.loose_joints:
            parts.append(f"{len(self.loose_joints)} loose joint(s)")
        if self.joints_on_bars:
            bars = len({e for e, _ in self.joints_on_bars})
            parts.append(f"{len(self.joints_on_bars)} joint(s) lying inside {bars} bar(s)")
        if self.joints_on_shell_edges:
            shells = len({e for e, _ in self.joints_on_shell_edges})
            parts.append(
                f"{len(self.joints_on_shell_edges)} joint(s) on the edges of {shells} shell(s)"
            )
        return ", ".join(parts) + "."


def loose_joints(project: Project) -> list[int]:
    """Nodes nothing uses: no element, constraint, rigid link or diaphragm."""
    used: set[int] = set()
    for element in project.elements:
        used.update(element.nodes)
    for constraint in project.mp_constraints:
        used.update((constraint.retained_node, constraint.constrained_node))
    for link in project.rigid_links:
        used.update((link.retained_node, link.constrained_node))
    for diaphragm in project.diaphragms:
        used.add(diaphragm.retained_node)
        used.update(getattr(diaphragm, "constrained_nodes", ()))
    return sorted(node.id for node in project.nodes if node.id not in used)


def _points_inside(
    project: Project,
    edges: list[tuple[int, int, int]],
    tolerance: float,
    element_ids: set[int] | None,
) -> list[tuple[int, int]]:
    """``(element id, node id)`` for every node strictly inside one of ``edges``.

    ``edges`` are ``(element id, node a, node b)``. A coarse box test runs first
    so a big model is not an all-pairs search.
    """
    coords = {node.id: np.asarray(node.coords, dtype=float) for node in project.nodes}
    ids = np.array(list(coords), dtype=int)
    points = np.array([coords[i] for i in ids]) if len(ids) else np.zeros((0, 3))
    found: list[tuple[int, int]] = []
    for element_id, a, b in edges:
        if element_ids is not None and element_id not in element_ids:
            continue
        start, end = coords[a], coords[b]
        low = np.minimum(start, end) - tolerance
        high = np.maximum(start, end) + tolerance
        near = np.all((points >= low) & (points <= high), axis=1)
        length = float(np.linalg.norm(end - start))
        if length == 0.0:
            continue
        margin = tolerance / length
        for node_id in ids[near]:
            node_id = int(node_id)
            if node_id in (a, b):
                continue
            t, distance = _parameter(coords[node_id], start, end)
            if distance <= tolerance and margin < t < 1.0 - margin:
                found.append((element_id, node_id))
    return found


def joints_on_bars(
    project: Project, tolerance: float, element_ids: set[int] | None = None
) -> list[tuple[int, int]]:
    """``(bar id, node id)`` for the joints lying inside a frame or truss."""
    edges = [(e.id, e.nodes[0], e.nodes[1]) for e in project.elements if _bar(e)]
    return _points_inside(project, edges, tolerance, element_ids)


def joints_on_shell_edges(project: Project, tolerance: float) -> list[tuple[int, int]]:
    """``(shell id, node id)`` for the joints inside a shell or quad edge (not a corner)."""
    edges = []
    for element in project.elements:
        if len(element.nodes) != 4:
            continue
        n = element.nodes
        edges += [(element.id, n[k], n[(k + 1) % 4]) for k in range(4)]
    found = _points_inside(project, edges, tolerance, None)
    # A node that is a corner of the same shell is not hanging (a warped edge).
    corners = {e.id: set(e.nodes) for e in project.elements if len(e.nodes) == 4}
    return sorted({(e, n) for e, n in found if n not in corners[e]})


def check_connectivity(project: Project, *, tolerance: float | None = None) -> ConnectivityReport:
    """Every connectivity fault of ``project``."""
    tolerance = default_tolerance(project) if tolerance is None else tolerance
    return ConnectivityReport(
        tolerance=tolerance,
        loose_joints=loose_joints(project),
        joints_on_bars=joints_on_bars(project, tolerance),
        joints_on_shell_edges=joints_on_shell_edges(project, tolerance),
    )
