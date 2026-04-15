"""Geometric transformation commands.

- :class:`MoveNodesCommand`     — translate nodes in place.
- :class:`ReplicateCommand`     — copy nodes (and elements connecting them)
  ``n_copies`` times along an offset.
- :class:`MirrorCommand`        — copy nodes (and connecting elements)
  reflected across a global plane (XY, YZ, or XZ).

For Replicate and Mirror, only elements whose **all** endpoint nodes
fall in the selected set are duplicated — partial-cut elements are
silently skipped, matching SAP/ETABS behavior.

All copies inherit the source node's restraint, mass, and name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from opensees_studio.commands.base import ProjectCommand
from opensees_studio.core import Node

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


# ─────────────────────────── Move ───────────────────────────
class MoveNodesCommand(ProjectCommand):
    """Translate selected nodes in place by ``offset``."""

    def __init__(
        self,
        vm: "ProjectViewModel",
        node_ids: set[int],
        offset: tuple[float, float, float],
    ) -> None:
        super().__init__(vm, f"Move {len(node_ids)} node(s)")
        self._node_ids = set(node_ids)
        self._offset = offset
        self._previous: dict[int, tuple[float, float, float]] = {}

    def redo(self) -> None:
        dx, dy, dz = self._offset
        self._previous.clear()
        for i, n in enumerate(self.project.nodes):
            if n.id in self._node_ids:
                self._previous[n.id] = n.coords
                self.project.nodes[i] = n.model_copy(update={
                    "coords": (n.coords[0] + dx, n.coords[1] + dy, n.coords[2] + dz)
                })
        self._notify()

    def undo(self) -> None:
        for i, n in enumerate(self.project.nodes):
            if n.id in self._previous:
                self.project.nodes[i] = n.model_copy(update={"coords": self._previous[n.id]})
        self._notify()


# ─────────────────────────── Replicate ───────────────────────────
class ReplicateCommand(ProjectCommand):
    """Copy selected nodes (and connecting elements) ``n_copies`` times."""

    def __init__(
        self,
        vm: "ProjectViewModel",
        node_ids: set[int],
        element_ids: set[int],
        offset: tuple[float, float, float],
        n_copies: int = 1,
    ) -> None:
        if n_copies < 1:
            raise ValueError("n_copies must be ≥ 1.")
        super().__init__(vm, f"Replicate × {n_copies}")
        self._node_ids = set(node_ids)
        self._element_ids = set(element_ids)
        self._offset = offset
        self._n_copies = n_copies
        self._added_node_ids: set[int] = set()
        self._added_element_ids: set[int] = set()

    def redo(self) -> None:
        dx, dy, dz = self._offset
        # Snapshot the source nodes/elements once (won't change during redo).
        src_nodes = [n for n in self.project.nodes if n.id in self._node_ids]
        src_elements = [
            e for e in self.project.elements
            if e.id in self._element_ids and all(nid in self._node_ids for nid in e.nodes)
        ]
        next_node_id = self.project.next_node_id()
        next_elem_id = self.project.next_element_id()
        self._added_node_ids.clear()
        self._added_element_ids.clear()

        for k in range(1, self._n_copies + 1):
            mapping: dict[int, int] = {}
            for orig in src_nodes:
                new_node = orig.model_copy(update={
                    "id": next_node_id,
                    "coords": (orig.coords[0] + k * dx,
                               orig.coords[1] + k * dy,
                               orig.coords[2] + k * dz),
                })
                self.project.nodes.append(new_node)
                self._added_node_ids.add(next_node_id)
                mapping[orig.id] = next_node_id
                next_node_id += 1
            for orig in src_elements:
                new_elem = orig.model_copy(update={
                    "id": next_elem_id,
                    "nodes": tuple(mapping[nid] for nid in orig.nodes),
                })
                self.project.elements.append(new_elem)
                self._added_element_ids.add(next_elem_id)
                next_elem_id += 1
        self._notify()

    def undo(self) -> None:
        self.project.nodes[:] = [
            n for n in self.project.nodes if n.id not in self._added_node_ids
        ]
        self.project.elements[:] = [
            e for e in self.project.elements if e.id not in self._added_element_ids
        ]
        self._added_node_ids.clear()
        self._added_element_ids.clear()
        self._notify()


# ─────────────────────────── Mirror ───────────────────────────
Plane = Literal["XY", "YZ", "XZ"]


class MirrorCommand(ProjectCommand):
    """Copy selected nodes (and connecting elements) reflected across a global plane.

    Plane → axis flipped:
        - "XY" plane (z=0) → flips z
        - "YZ" plane (x=0) → flips x
        - "XZ" plane (y=0) → flips y
    """

    def __init__(
        self,
        vm: "ProjectViewModel",
        node_ids: set[int],
        element_ids: set[int],
        plane: Plane,
    ) -> None:
        super().__init__(vm, f"Mirror across {plane} plane")
        self._node_ids = set(node_ids)
        self._element_ids = set(element_ids)
        self._plane = plane
        self._added_node_ids: set[int] = set()
        self._added_element_ids: set[int] = set()

    @staticmethod
    def _reflect(coords: tuple[float, float, float], plane: Plane) -> tuple[float, float, float]:
        x, y, z = coords
        if plane == "XY":
            return (x, y, -z)
        if plane == "YZ":
            return (-x, y, z)
        return (x, -y, z)  # XZ

    def redo(self) -> None:
        src_nodes = [n for n in self.project.nodes if n.id in self._node_ids]
        src_elements = [
            e for e in self.project.elements
            if e.id in self._element_ids and all(nid in self._node_ids for nid in e.nodes)
        ]
        next_node_id = self.project.next_node_id()
        next_elem_id = self.project.next_element_id()
        self._added_node_ids.clear()
        self._added_element_ids.clear()
        mapping: dict[int, int] = {}

        for orig in src_nodes:
            new_node = orig.model_copy(update={
                "id": next_node_id,
                "coords": self._reflect(orig.coords, self._plane),
            })
            self.project.nodes.append(new_node)
            self._added_node_ids.add(next_node_id)
            mapping[orig.id] = next_node_id
            next_node_id += 1
        for orig in src_elements:
            new_elem = orig.model_copy(update={
                "id": next_elem_id,
                "nodes": tuple(mapping[nid] for nid in orig.nodes),
            })
            self.project.elements.append(new_elem)
            self._added_element_ids.add(next_elem_id)
            next_elem_id += 1
        self._notify()

    def undo(self) -> None:
        self.project.nodes[:] = [
            n for n in self.project.nodes if n.id not in self._added_node_ids
        ]
        self.project.elements[:] = [
            e for e in self.project.elements if e.id not in self._added_element_ids
        ]
        self._added_node_ids.clear()
        self._added_element_ids.clear()
        self._notify()
