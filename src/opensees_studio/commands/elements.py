"""Commands that add or remove elements."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opensees_studio.commands.base import ProjectCommand

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class AddElementsCommand(ProjectCommand):
    """Add one or more elements in a single undoable step."""

    def __init__(self, vm: "ProjectViewModel", elements: list[Any], *, text: str | None = None) -> None:
        super().__init__(vm, text or f"Add {len(elements)} element(s)")
        self._elements = list(elements)

    def redo(self) -> None:
        existing_ids = {e.id for e in self.project.elements}
        node_ids = {n.id for n in self.project.nodes}
        for el in self._elements:
            if el.id in existing_ids:
                raise ValueError(f"Element id {el.id} already exists.")
            for nid in el.nodes:
                if nid not in node_ids:
                    raise ValueError(f"Element {el.id} references missing node {nid}.")
        self.project.elements.extend(self._elements)
        self._notify()

    def undo(self) -> None:
        ids = {e.id for e in self._elements}
        self.project.elements[:] = [e for e in self.project.elements if e.id not in ids]
        self._notify()


class DeleteElementsCommand(ProjectCommand):
    """Remove a set of elements (no cascade — nodes are not affected)."""

    def __init__(self, vm: "ProjectViewModel", element_ids: set[int]) -> None:
        super().__init__(vm, f"Delete {len(element_ids)} element(s)")
        self._element_ids = set(element_ids)
        self._removed: list[tuple[int, Any]] = []

    def redo(self) -> None:
        self._removed = [
            (i, el) for i, el in enumerate(self.project.elements)
            if el.id in self._element_ids
        ]
        self.project.elements[:] = [
            el for el in self.project.elements if el.id not in self._element_ids
        ]
        self._notify()

    def undo(self) -> None:
        for i, el in self._removed:
            self.project.elements.insert(min(i, len(self.project.elements)), el)
        self._removed.clear()
        self._notify()
