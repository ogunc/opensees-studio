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


class ConvertElementTypeCommand(ProjectCommand):
    """Convert a selection of elements to a different concrete type.

    Preserves each element's id, name, and nodes but rebuilds it as the
    target type. ``target_type`` is one of "Truss", "ElasticBeamColumn".
    Extra fields for the new type come from ``defaults`` (a dict of
    kwargs merged into the new element's constructor).
    """

    def __init__(
        self,
        vm: "ProjectViewModel",
        element_ids: set[int],
        target_type: str,
        defaults: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            vm, f"Convert {len(element_ids)} element(s) to {target_type}",
        )
        self._element_ids = set(element_ids)
        self._target_type = target_type
        self._defaults = dict(defaults or {})
        self._previous: dict[int, Any] = {}

    def redo(self) -> None:
        from opensees_studio.core import (
            CorotTrussElement,
            DispBeamColumn,
            ElasticBeamColumn,
            ForceBeamColumn,
            TrussElement,
        )
        type_map = {
            "Truss": TrussElement,
            "CorotTruss": CorotTrussElement,
            "ElasticBeamColumn": ElasticBeamColumn,
            "ForceBeamColumn": ForceBeamColumn,
            "DispBeamColumn": DispBeamColumn,
        }
        cls = type_map.get(self._target_type)
        if cls is None:
            raise ValueError(f"Unsupported target type: {self._target_type}")
        self._previous.clear()
        for i, el in enumerate(self.project.elements):
            if el.id not in self._element_ids:
                continue
            if el.__class__ is cls:
                continue    # already the target type
            self._previous[el.id] = el
            kwargs: dict[str, Any] = {
                "id": el.id,
                "name": el.name,
                "nodes": el.nodes,
                **self._defaults,
            }
            # Preserve compatible fields where possible.
            if hasattr(el, "material_id") and "material_id" not in kwargs:
                kwargs["material_id"] = el.material_id  # type: ignore[attr-defined]
            if hasattr(el, "section_id") and "section_id" not in kwargs:
                kwargs["section_id"] = el.section_id    # type: ignore[attr-defined]
            if hasattr(el, "area") and "area" not in kwargs:
                kwargs["area"] = el.area                # type: ignore[attr-defined]
            # Drop kwargs the target class doesn't accept.
            accepted = cls.model_fields.keys()
            kwargs = {k: v for k, v in kwargs.items() if k in accepted}
            self.project.elements[i] = cls(**kwargs)
        self._notify()

    def undo(self) -> None:
        for i, el in enumerate(self.project.elements):
            if el.id in self._previous:
                self.project.elements[i] = self._previous[el.id]
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


class UpdateElementFieldsCommand(ProjectCommand):
    """Overwrite arbitrary field(s) on one element via ``model_copy(update=…)``.

    Used by the Properties dock for inline scalar edits (e.g. a truss's
    ``area``, a frame's ``geom_transf``). Fields that the element's class
    doesn't accept are ignored silently so a single callback can be
    wired for heterogeneous selections.
    """

    def __init__(
        self,
        vm: "ProjectViewModel",
        element_id: int,
        fields: dict[str, Any],
    ) -> None:
        keys = ", ".join(sorted(fields))
        super().__init__(vm, f"Edit element {element_id} ({keys})")
        self._element_id = element_id
        self._fields = dict(fields)
        self._previous: Any | None = None

    def redo(self) -> None:
        for i, el in enumerate(self.project.elements):
            if el.id != self._element_id:
                continue
            # Filter out fields not declared on the element's model.
            accepted = {
                k: v for k, v in self._fields.items()
                if k in el.__class__.model_fields
            }
            if not accepted:
                return
            self._previous = el
            self.project.elements[i] = el.model_copy(update=accepted)
            self._notify()
            return

    def undo(self) -> None:
        if self._previous is None:
            return
        for i, el in enumerate(self.project.elements):
            if el.id == self._element_id:
                self.project.elements[i] = self._previous
                self._previous = None
                self._notify()
                return


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
