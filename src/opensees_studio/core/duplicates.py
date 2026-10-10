"""Find — and explain — nodes and elements that the model defines twice.

A model that has been copied, mirrored or imported twice accumulates
coincident nodes and repeated elements. Neither is loud: the analysis runs, the
numbers are wrong, and the deformed shape looks almost right. This module is the
*report*; :class:`~opensees_studio.commands.duplicates.FixDuplicatesCommand` is
the correction.

Two details are what make the report usable rather than dangerous:

* **A coincident pair is often deliberate.** A zero-length element or a bearing
  joins two nodes at the same point on purpose, and a hinge can be modelled as
  two coincident nodes tied by ``equalDOF``. Those clusters come back as
  *exempt*, with the reason, instead of being offered for merging — merging them
  would silently delete every isolator in the model.
* **Elements are compared by their whole definition**, not by their nodes: two
  elements over the same nodes with different sections or materials are
  *parallel*, which is a modelling choice, and are reported as information
  only. Duplicates (same type, same nodes, same properties) are the ones that
  double a stiffness without anyone asking.

Tolerance is relative to the size of the model, so the same numbers work in
metres and in millimetres.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from opensees_studio.core.geometry.bearings import BEARING_CLASSES
from opensees_studio.core.geometry.elements import (
    ZeroLengthElement,
    ZeroLengthSectionElement,
)
from opensees_studio.core.project import Project

#: Element types whose two nodes are meant to sit on top of each other.
ZERO_LENGTH_CLASSES = (
    ZeroLengthElement,
    ZeroLengthSectionElement,
    *BEARING_CLASSES,
)

#: Coincidence tolerance relative to the model's bounding-box diagonal.
RELATIVE_TOLERANCE = 1e-6

#: Floor for the tolerance (project units), so a dimensionless or tiny model
#: does not end up comparing coordinates exactly.
MIN_TOLERANCE = 1e-9


@dataclass(frozen=True)
class NodeCluster:
    """Nodes at (almost) the same point."""

    coords: tuple[float, float, float]
    keeper_id: int
    duplicate_ids: tuple[int, ...]
    exempt_reason: str | None = None

    @property
    def ids(self) -> tuple[int, ...]:
        return (self.keeper_id, *self.duplicate_ids)

    @property
    def mergeable(self) -> bool:
        return self.exempt_reason is None

    def summary(self) -> str:
        where = "(" + ", ".join(f"{value:g}" for value in self.coords) + ")"
        if self.exempt_reason is not None:
            return f"{where}: nodes {list(self.ids)} left alone — {self.exempt_reason}"
        return f"{where}: nodes {list(self.ids)} → keep {self.keeper_id}"


@dataclass(frozen=True)
class ElementCluster:
    """Elements that describe the same member."""

    type: str
    nodes: tuple[int, ...]
    keeper_id: int
    duplicate_ids: tuple[int, ...]
    parallel_only: bool = False

    @property
    def ids(self) -> tuple[int, ...]:
        return (self.keeper_id, *self.duplicate_ids)

    def summary(self) -> str:
        verb = "parallel" if self.parallel_only else "duplicate"
        return f"{self.type} {verb}: elements {list(self.ids)} share nodes {list(self.nodes)}"


@dataclass(frozen=True)
class DuplicateReport:
    """What the model has twice."""

    tolerance: float
    node_clusters: list[NodeCluster] = field(default_factory=list)
    exempt_clusters: list[NodeCluster] = field(default_factory=list)
    element_clusters: list[ElementCluster] = field(default_factory=list)
    parallel_clusters: list[ElementCluster] = field(default_factory=list)

    @property
    def duplicate_node_count(self) -> int:
        return sum(len(cluster.duplicate_ids) for cluster in self.node_clusters)

    @property
    def duplicate_element_count(self) -> int:
        return sum(len(cluster.duplicate_ids) for cluster in self.element_clusters)

    @property
    def is_clean(self) -> bool:
        return not (self.node_clusters or self.element_clusters)

    def summary(self) -> str:
        if self.is_clean and not self.exempt_clusters and not self.parallel_clusters:
            return "No duplicate nodes or elements found."
        parts = [
            f"{len(self.node_clusters)} coincident node group(s) "
            f"({self.duplicate_node_count} node(s) to merge)",
            f"{len(self.element_clusters)} duplicate element group(s) "
            f"({self.duplicate_element_count} element(s) to remove)",
        ]
        if self.parallel_clusters:
            parts.append(f"{len(self.parallel_clusters)} parallel element group(s)")
        if self.exempt_clusters:
            parts.append(f"{len(self.exempt_clusters)} group(s) left alone")
        return "; ".join(parts) + "."


# ──────────────────────────── tolerance ────────────────────────────
def default_tolerance(project: Project) -> float:
    """Coincidence tolerance: one part per million of the model's size."""
    if not project.nodes:
        return MIN_TOLERANCE
    coords = [node.coords for node in project.nodes]
    diagonal = math.dist(
        (min(c[0] for c in coords), min(c[1] for c in coords), min(c[2] for c in coords)),
        (max(c[0] for c in coords), max(c[1] for c in coords), max(c[2] for c in coords)),
    )
    return max(MIN_TOLERANCE, RELATIVE_TOLERANCE * diagonal)


# ──────────────────────────── nodes ────────────────────────────
def _coincident_groups(project: Project, tolerance: float) -> list[list[int]]:
    """Group node ids that sit within ``tolerance`` of each other.

    A hash grid over cells of ``tolerance`` with a 27-cell neighbourhood search,
    so two points are never missed for landing on either side of a cell edge.
    """
    cells: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    positions = {node.id: node.coords for node in project.nodes}
    for node in project.nodes:
        cells[
            (
                math.floor(node.coords[0] / tolerance),
                math.floor(node.coords[1] / tolerance),
                math.floor(node.coords[2] / tolerance),
            )
        ].append(node.id)

    parent: dict[int, int] = {node.id: node.id for node in project.nodes}

    def find(node_id: int) -> int:
        while parent[node_id] != node_id:
            parent[node_id] = parent[parent[node_id]]
            node_id = parent[node_id]
        return node_id

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    keys = list(cells)
    for key in keys:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    neighbour = (key[0] + dx, key[1] + dy, key[2] + dz)
                    if neighbour not in cells:
                        continue
                    for first in cells[key]:
                        for second in cells[neighbour]:
                            if first >= second:
                                continue
                            if math.dist(positions[first], positions[second]) <= tolerance:
                                union(first, second)

    grouped: dict[int, list[int]] = defaultdict(list)
    for node_id in parent:
        grouped[find(node_id)].append(node_id)
    return [sorted(ids) for ids in grouped.values() if len(ids) > 1]


def _exemption(project: Project, ids: list[int]) -> str | None:
    """Why a coincident group must not be merged, or None when it is a mistake."""
    members = set(ids)
    for element in project.elements:
        if isinstance(element, ZERO_LENGTH_CLASSES) and set(element.nodes) <= members:
            return f"joined by a zero-length element ({element.type})"
    for constraint in project.mp_constraints:
        if {constraint.retained_node, constraint.constrained_node} <= members:
            return "tied together by an equalDOF constraint"
    return None


def find_node_clusters(
    project: Project, *, tolerance: float | None = None
) -> tuple[list[NodeCluster], list[NodeCluster]]:
    """Return ``(mergeable, exempt)`` groups of coincident nodes."""
    tolerance = default_tolerance(project) if tolerance is None else tolerance
    by_id = {node.id: node for node in project.nodes}
    mergeable: list[NodeCluster] = []
    exempt: list[NodeCluster] = []
    for ids in _coincident_groups(project, tolerance):
        keeper = min(ids)
        cluster = NodeCluster(
            coords=by_id[keeper].coords,
            keeper_id=keeper,
            duplicate_ids=tuple(sorted(set(ids) - {keeper})),
            exempt_reason=_exemption(project, ids),
        )
        (exempt if cluster.exempt_reason else mergeable).append(cluster)
    return mergeable, exempt


# ──────────────────────────── elements ────────────────────────────
def _canonical_nodes(nodes: tuple[int, ...]) -> tuple[int, ...]:
    """The node ids in a form that ignores order.

    Two nodes are unordered — a beam from 1 to 2 is the beam from 2 to 1 — and a
    face is identified by the nodes it joins, so a quad listed from another
    corner (or wound the other way) is still the same face. A figure-eight
    listing of the same four nodes is *also* the same set: it is a broken
    element, and one report entry is the right way to show it.
    """
    return tuple(sorted(nodes))


def _element_key(element: Any) -> tuple[str, tuple[int, ...], str]:
    """Everything that defines an element except its id and its name."""
    payload = element.model_dump(exclude={"id", "name"})
    nodes = tuple(payload.pop("nodes"))
    payload.pop("type", None)
    fields = ";".join(f"{name}={payload[name]!r}" for name in sorted(payload))
    return (element.type, _canonical_nodes(nodes), fields)


def find_element_clusters(
    project: Project,
) -> tuple[list[ElementCluster], list[ElementCluster]]:
    """Return ``(duplicates, parallel)`` groups of elements.

    ``duplicates`` share their whole definition, so removing the extras changes
    nothing except the double stiffness they were adding. ``parallel`` share
    their nodes but differ in something else (a section, a material), which is
    reported and not touched.
    """
    by_key: dict[tuple[str, tuple[int, ...], str], list[Any]] = defaultdict(list)
    by_nodes: dict[tuple[str, tuple[int, ...]], list[Any]] = defaultdict(list)
    for element in project.elements:
        by_key[_element_key(element)].append(element)
        by_nodes[(element.type, _canonical_nodes(tuple(element.nodes)))].append(element)

    duplicates: list[ElementCluster] = []
    parallel: list[ElementCluster] = []
    for elements in by_key.values():
        if len(elements) < 2:
            continue
        ids = sorted(element.id for element in elements)
        duplicates.append(
            ElementCluster(
                type=elements[0].type,
                nodes=tuple(elements[0].nodes),
                keeper_id=ids[0],
                duplicate_ids=tuple(ids[1:]),
            )
        )
    for (element_type, nodes), elements in by_nodes.items():
        if len(elements) < 2 or len({_element_key(element) for element in elements}) < 2:
            continue  # a true duplicate group, already reported above
        ids = sorted(element.id for element in elements)
        parallel.append(
            ElementCluster(
                type=element_type,
                nodes=nodes,
                keeper_id=ids[0],
                duplicate_ids=tuple(ids[1:]),
                parallel_only=True,
            )
        )
    return duplicates, parallel


# ──────────────────────────── the report ────────────────────────────
def check_duplicates(project: Project, *, tolerance: float | None = None) -> DuplicateReport:
    """Everything that is defined twice in ``project``."""
    tolerance = default_tolerance(project) if tolerance is None else tolerance
    mergeable, exempt = find_node_clusters(project, tolerance=tolerance)
    duplicates, parallel = find_element_clusters(project)
    return DuplicateReport(
        tolerance=tolerance,
        node_clusters=mergeable,
        exempt_clusters=exempt,
        element_clusters=duplicates,
        parallel_clusters=parallel,
    )
