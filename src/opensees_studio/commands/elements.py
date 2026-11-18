"""Commands that add or remove elements."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opensees_studio.commands.base import ProjectCommand
from opensees_studio.core.groups import Group, prune_groups

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class AddElementsCommand(ProjectCommand):
    """Add one or more elements in a single undoable step."""

    def __init__(
        self, vm: ProjectViewModel, elements: list[Any], *, text: str | None = None
    ) -> None:
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

    def __init__(self, vm: ProjectViewModel, element_ids: set[int]) -> None:
        super().__init__(vm, f"Delete {len(element_ids)} element(s)")
        self._element_ids = set(element_ids)
        self._removed: list[tuple[int, Any]] = []
        self._groups: list[Group] = []

    def redo(self) -> None:
        self._removed = [
            (i, el) for i, el in enumerate(self.project.elements) if el.id in self._element_ids
        ]
        self.project.elements[:] = [
            el for el in self.project.elements if el.id not in self._element_ids
        ]
        self._groups = list(self.project.groups)
        prune_groups(self.project)
        self._notify()

    def undo(self) -> None:
        self.project.groups[:] = self._groups
        for i, el in self._removed:
            self.project.elements.insert(min(i, len(self.project.elements)), el)
        self._removed.clear()
        self._notify()


class AssignSectionCommand(ProjectCommand):
    """Set ``section_id`` on a set of frame elements.

    Silently skips elements that don't carry a ``section_id`` field
    (e.g. trusses, zero-length elements).  Assigning a
    :class:`~opensees_studio.core.NonprismaticSection` materialises the
    selection: the member is replaced by its subdivided elastic pieces, so
    the command snapshots and restores the whole model for undo.
    """

    def __init__(self, vm: ProjectViewModel, element_ids: set[int], section_id: int) -> None:
        super().__init__(vm, f"Assign section {section_id} to {len(element_ids)} element(s)")
        self._element_ids = set(element_ids)
        self._section_id = section_id
        self._previous: dict[int, int] = {}
        self._snapshot: tuple[list[Any], ...] | None = None

    def _take_snapshot(self) -> tuple[list[Any], ...]:
        return (
            [n.model_copy(deep=True) for n in self.project.nodes],
            [el.model_copy(deep=True) for el in self.project.elements],
            [s.model_copy(deep=True) for s in self.project.sections],
            [p.model_copy(deep=True) for p in self.project.load_patterns],
            [g.model_copy(deep=True) for g in self.project.groups],
        )

    def _restore(self) -> None:
        if self._snapshot is None:
            return
        nodes, elements, sections, patterns, groups = self._snapshot
        self.project.nodes[:] = nodes
        self.project.elements[:] = elements
        self.project.sections[:] = sections
        self.project.load_patterns[:] = patterns
        self.project.groups[:] = groups

    def redo(self) -> None:
        from opensees_studio.core import ElasticBeamColumn, NonprismaticSection
        from opensees_studio.services.nonprismatic import materialize_nonprismatic

        section = next((s for s in self.project.sections if s.id == self._section_id), None)
        if isinstance(section, NonprismaticSection):
            targets = [
                el
                for el in self.project.elements
                if el.id in self._element_ids and hasattr(el, "section_id")
            ]
            bad = [el.id for el in targets if not isinstance(el, ElasticBeamColumn)]
            if bad:
                raise ValueError(
                    "A nonprismatic section can only be assigned to "
                    "ElasticBeamColumn elements; element(s) "
                    f"{', '.join(map(str, bad))} are a different frame type."
                )
            self._snapshot = self._take_snapshot()
            try:
                for i, el in enumerate(self.project.elements):
                    if el.id in self._element_ids and hasattr(el, "section_id"):
                        self.project.elements[i] = el.model_copy(
                            update={"section_id": self._section_id}
                        )
                materialize_nonprismatic(self.project, element_ids=self._element_ids)
            except Exception:
                self._restore()
                self._snapshot = None
                raise
            self._notify()
            return
        self._previous.clear()
        for i, el in enumerate(self.project.elements):
            if el.id not in self._element_ids:
                continue
            sid = getattr(el, "section_id", None)
            if sid is None:
                continue
            self._previous[el.id] = sid
            self.project.elements[i] = el.model_copy(update={"section_id": self._section_id})
        self._notify()

    def undo(self) -> None:
        if self._snapshot is not None:
            self._restore()
            self._snapshot = None
            self._notify()
            return
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
        vm: ProjectViewModel,
        element_ids: set[int],
        target_type: str,
        defaults: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            vm,
            f"Convert {len(element_ids)} element(s) to {target_type}",
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
                continue  # already the target type
            self._previous[el.id] = el
            kwargs: dict[str, Any] = {
                "id": el.id,
                "name": el.name,
                "nodes": el.nodes,
                **self._defaults,
            }
            # Preserve compatible fields where possible.
            if hasattr(el, "material_id") and "material_id" not in kwargs:
                kwargs["material_id"] = el.material_id
            if hasattr(el, "section_id") and "section_id" not in kwargs:
                kwargs["section_id"] = el.section_id
            if hasattr(el, "area") and "area" not in kwargs:
                kwargs["area"] = el.area
            if hasattr(el, "unit_weight") and "unit_weight" not in kwargs:
                kwargs["unit_weight"] = el.unit_weight
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

    def __init__(self, vm: ProjectViewModel, replacements: list[Any]) -> None:
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
        vm: ProjectViewModel,
        element_id: int,
        fields: dict[str, Any],
    ) -> None:
        keys = ", ".join(sorted(fields))
        super().__init__(vm, f"Edit element {element_id} ({keys})")
        self._element_id = element_id
        self._previous: Any | None = None
        # Built and validated before the push (see AssignElementFieldsCommand).
        self._updated: Any | None = None
        for el in self.project.elements:
            if el.id == element_id:
                # Filter out fields not declared on the element's model.
                accepted = {k: v for k, v in fields.items() if k in type(el).model_fields}
                if accepted:
                    self._updated = type(el).model_validate({**el.model_dump(), **accepted})
                break

    def redo(self) -> None:
        if self._updated is None:
            return
        for i, el in enumerate(self.project.elements):
            if el.id == self._element_id:
                self._previous = el
                self.project.elements[i] = self._updated
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

    def __init__(self, vm: ProjectViewModel, element_ids: set[int], material_id: int) -> None:
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
            self._previous[el.id] = el.material_id
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


class AssignElementFieldsCommand(ProjectCommand):
    """Set the same field value(s) on a set of elements, validated, in one undoable step.

    Used by the Frame menu assignments (geometric transformation, beam
    integration). Elements whose class lacks any of the fields are skipped,
    so a mixed selection of frames and trusses assigns to the frames only.
    Each changed element is rebuilt through Pydantic validation when the
    command is created, so an invalid value raises before anything changes.
    ``per_element`` adds values that differ per element (``{id: {field: value}}``).
    """

    def __init__(
        self,
        vm: ProjectViewModel,
        element_ids: set[int],
        fields: dict[str, Any],
        *,
        text: str | None = None,
        per_element: dict[int, dict[str, Any]] | None = None,
    ) -> None:
        keys = ", ".join(sorted(fields))
        super().__init__(vm, text or f"Assign {keys} to {len(element_ids)} element(s)")
        per_element = per_element or {}
        # Validated here, before the push: an exception raised inside redo() would
        # be swallowed by Qt and leave a half-applied command on the stack.
        self._updated: dict[int, Any] = {
            el.id: type(el).model_validate(
                {**el.model_dump(), **fields, **per_element.get(el.id, {})}
            )
            for el in self.project.elements
            if el.id in element_ids and self.accepts(el, fields)
        }
        self._previous: dict[int, Any] = {}

    @staticmethod
    def accepts(element: Any, fields: dict[str, Any]) -> bool:
        """``element`` declares every one of ``fields``."""
        return all(k in type(element).model_fields for k in fields)

    def redo(self) -> None:
        self._previous.clear()
        for i, el in enumerate(self.project.elements):
            if el.id in self._updated:
                self._previous[el.id] = el
                self.project.elements[i] = self._updated[el.id]
        self._notify()

    def undo(self) -> None:
        for i, el in enumerate(self.project.elements):
            if el.id in self._previous:
                self.project.elements[i] = self._previous[el.id]
        self._previous.clear()
        self._notify()

    @property
    def changed_ids(self) -> set[int]:
        """Elements the command changes."""
        return set(self._updated)
