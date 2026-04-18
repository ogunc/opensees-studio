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


class AssignSectionCommand(ProjectCommand):
    """Set ``section_id`` on a set of frame elements.

    Silently skips elements that don't carry a ``section_id`` field
    (e.g. trusses, zero-length elements).
    """

    def __init__(self, vm: "ProjectViewModel", element_ids: set[int], section_id: int) -> None:
        super().__init__(vm, f"Assign section {section_id} to {len(element_ids)} element(s)")
        self._element_ids = set(element_ids)
        self._section_id = section_id
        self._previous: dict[int, int] = {}

    def redo(self) -> None:
        self._previous.clear()
        for i, el in enumerate(self.project.elements):
            if el.id not in self._element_ids:
                continue
            if not hasattr(el, "section_id"):
                continue
            self._previous[el.id] = el.section_id  # type: ignore[attr-defined]
            self.project.elements[i] = el.model_copy(update={"section_id": self._section_id})
        self._notify()

    def undo(self) -> None:
        for i, el in enumerate(self.project.elements):
            if el.id in self._previous:
                self.project.elements[i] = el.model_copy(
                    update={"section_id": self._previous[el.id]}
                )
        self._previous.clear()
        self._notify()


class ReplaceElementsCommand(ProjectCommand):
    """Replace elements (by id) with new element objects — undoable.

    Used for operations like 'Assign Hinge' that swap one element type
    for another while preserving the id and node connectivity.
    """

    def __init__(self, vm: "ProjectViewModel", replacements: list[Any]) -> None:
        super().__init__(vm, f"Replace {len(replacements)} element(s)")
        self._replacements = {el.id: el for el in replacements}
        self._previous: dict[int, Any] = {}

    def redo(self) -> None:
        self._previous.clear()
        for i, el in enumerate(self.project.elements):
            if el.id in self._replacements:
                self._previous[el.id] = el
                self.project.elements[i] = self._replacements[el.id]
        self._notify()

    def undo(self) -> None:
        for i, el in enumerate(self.project.elements):
            if el.id in self._previous:
                self.project.elements[i] = self._previous[el.id]
        self._previous.clear()
        self._notify()


class AssignMaterialCommand(ProjectCommand):
    """Set ``material_id`` on a set of elements (truss-style)."""

    def __init__(self, vm: "ProjectViewModel", element_ids: set[int], material_id: int) -> None:
        super().__init__(vm, f"Assign material {material_id} to {len(element_ids)} element(s)")
        self._element_ids = set(element_ids)
        self._material_id = material_id
        self._previous: dict[int, int] = {}

    def redo(self) -> None:
        self._previous.clear()
        for i, el in enumerate(self.project.elements):
            if el.id not in self._element_ids:
                continue
            if not hasattr(el, "material_id"):
                continue
            self._previous[el.id] = el.material_id  # type: ignore[attr-defined]
            self.project.elements[i] = el.model_copy(update={"material_id": self._material_id})
        self._notify()

    def undo(self) -> None:
        for i, el in enumerate(self.project.elements):
            if el.id in self._previous:
                self.project.elements[i] = el.model_copy(
                    update={"material_id": self._previous[el.id]}
                )
        self._previous.clear()
        self._notify()
