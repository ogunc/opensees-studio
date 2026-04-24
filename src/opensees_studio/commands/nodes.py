"""Commands that add, remove, or modify nodes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand
from opensees_studio.core import Node

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class AddNodesCommand(ProjectCommand):
    """Add one or more nodes in a single undoable step."""

    def __init__(self, vm: "ProjectViewModel", nodes: list[Node], *, text: str | None = None) -> None:
        super().__init__(vm, text or f"Add {len(nodes)} node(s)")
        self._nodes = list(nodes)

    def redo(self) -> None:
        existing_ids = {n.id for n in self.project.nodes}
        for node in self._nodes:
            if node.id in existing_ids:
                raise ValueError(f"Node id {node.id} already exists.")
        self.project.nodes.extend(self._nodes)
        self._notify()

    def undo(self) -> None:
        ids = {n.id for n in self._nodes}
        self.project.nodes[:] = [n for n in self.project.nodes if n.id not in ids]
        self._notify()


class DeleteNodesCommand(ProjectCommand):
    """Delete nodes and (cascading) any elements that reference them.

    The deleted nodes and elements are stashed so undo can re-insert
    them in their original positions.
    """

    def __init__(self, vm: "ProjectViewModel", node_ids: set[int]) -> None:
        super().__init__(vm, f"Delete {len(node_ids)} node(s)")
        self._node_ids = set(node_ids)
        self._removed_nodes: list[tuple[int, Node]] = []      # (index, node)
        self._removed_elements: list[tuple[int, object]] = [] # (index, element)
        self._removed_mp_constraints: list[tuple[int, object]] = []

    def redo(self) -> None:
        # Cascade: snapshot every element that references a doomed node.
        self._removed_elements = [
            (i, el) for i, el in enumerate(self.project.elements)
            if any(nid in self._node_ids for nid in el.nodes)
        ]
        doomed_elem_ids = {el.id for _, el in self._removed_elements}
        self.project.elements[:] = [
            el for el in self.project.elements if el.id not in doomed_elem_ids
        ]

        self._removed_mp_constraints = [
            (i, mp) for i, mp in enumerate(self.project.mp_constraints)
            if mp.retained_node in self._node_ids or mp.constrained_node in self._node_ids
        ]
        doomed_mp = {id(mp) for _, mp in self._removed_mp_constraints}
        self.project.mp_constraints[:] = [
            mp for mp in self.project.mp_constraints if id(mp) not in doomed_mp
        ]

        self._removed_nodes = [
            (i, n) for i, n in enumerate(self.project.nodes) if n.id in self._node_ids
        ]
        self.project.nodes[:] = [
            n for n in self.project.nodes if n.id not in self._node_ids
        ]
        self._notify()

    def undo(self) -> None:
        # Re-insert nodes first (elements depend on them).
        for i, n in self._removed_nodes:
            self.project.nodes.insert(min(i, len(self.project.nodes)), n)
        for i, mp in self._removed_mp_constraints:
            self.project.mp_constraints.insert(min(i, len(self.project.mp_constraints)), mp)
        for i, el in self._removed_elements:
            self.project.elements.insert(min(i, len(self.project.elements)), el)
        self._removed_nodes.clear()
        self._removed_elements.clear()
        self._removed_mp_constraints.clear()
        self._notify()


class SetRestraintCommand(ProjectCommand):
    """Apply the same restraint pattern to a set of nodes."""

    def __init__(
        self,
        vm: "ProjectViewModel",
        node_ids: set[int],
        restraint: tuple[bool, bool, bool, bool, bool, bool],
    ) -> None:
        super().__init__(vm, f"Set restraint on {len(node_ids)} node(s)")
        self._node_ids = set(node_ids)
        self._new_restraint = restraint
        self._previous: dict[int, tuple[bool, ...]] = {}

    def redo(self) -> None:
        self._previous.clear()
        for i, n in enumerate(self.project.nodes):
            if n.id in self._node_ids:
                self._previous[n.id] = n.restraint
                self.project.nodes[i] = n.model_copy(update={"restraint": self._new_restraint})
        self._notify()

    def undo(self) -> None:
        for i, n in enumerate(self.project.nodes):
            if n.id in self._previous:
                self.project.nodes[i] = n.model_copy(update={"restraint": self._previous[n.id]})
        self._notify()


class SetMassCommand(ProjectCommand):
    """Apply the same lumped-mass vector to a set of nodes (6-tuple)."""

    def __init__(
        self,
        vm: "ProjectViewModel",
        node_ids: set[int],
        mass: tuple[float, float, float, float, float, float],
    ) -> None:
        super().__init__(vm, f"Set mass on {len(node_ids)} node(s)")
        self._node_ids = set(node_ids)
        self._new_mass = mass
        self._previous: dict[int, tuple[float, ...]] = {}

    def redo(self) -> None:
        self._previous.clear()
        for i, n in enumerate(self.project.nodes):
            if n.id in self._node_ids:
                self._previous[n.id] = n.mass
                self.project.nodes[i] = n.model_copy(update={"mass": self._new_mass})
        self._notify()

    def undo(self) -> None:
        for i, n in enumerate(self.project.nodes):
            if n.id in self._previous:
                self.project.nodes[i] = n.model_copy(update={"mass": self._previous[n.id]})
        self._notify()
