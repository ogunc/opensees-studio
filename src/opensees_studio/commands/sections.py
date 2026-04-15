"""Commands that add or remove sections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opensees_studio.commands.base import ProjectCommand

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class AddSectionsCommand(ProjectCommand):
    """Add one or more sections in a single undoable step."""

    def __init__(self, vm: "ProjectViewModel", sections: list[Any], *, text: str | None = None) -> None:
        super().__init__(vm, text or f"Add {len(sections)} section(s)")
        self._sections = list(sections)

    def redo(self) -> None:
        existing = {s.id for s in self.project.sections}
        for sec in self._sections:
            if sec.id in existing:
                raise ValueError(f"Section id {sec.id} already exists.")
        self.project.sections.extend(self._sections)
        self._notify()

    def undo(self) -> None:
        ids = {s.id for s in self._sections}
        self.project.sections[:] = [s for s in self.project.sections if s.id not in ids]
        self._notify()


class DeleteSectionsCommand(ProjectCommand):
    """Remove sections (no cascade — elements referencing them must be cleaned separately)."""

    def __init__(self, vm: "ProjectViewModel", section_ids: set[int]) -> None:
        super().__init__(vm, f"Delete {len(section_ids)} section(s)")
        self._section_ids = set(section_ids)
        self._removed: list[tuple[int, Any]] = []

    def redo(self) -> None:
        self._removed = [
            (i, s) for i, s in enumerate(self.project.sections)
            if s.id in self._section_ids
        ]
        self.project.sections[:] = [
            s for s in self.project.sections if s.id not in self._section_ids
        ]
        self._notify()

    def undo(self) -> None:
        for i, s in self._removed:
            self.project.sections.insert(min(i, len(self.project.sections)), s)
        self._removed.clear()
        self._notify()


class UpdateSectionCommand(ProjectCommand):
    """Replace a section's parameters at a given id."""

    def __init__(self, vm: "ProjectViewModel", new_section: Any) -> None:
        super().__init__(vm, f"Edit section {new_section.id}")
        self._new = new_section
        self._old: Any | None = None
        self._index: int | None = None

    def redo(self) -> None:
        for i, s in enumerate(self.project.sections):
            if s.id == self._new.id:
                self._old = s
                self._index = i
                self.project.sections[i] = self._new
                self._notify()
                return
        raise KeyError(f"Section with id={self._new.id} not found.")

    def undo(self) -> None:
        if self._old is not None and self._index is not None:
            self.project.sections[self._index] = self._old
        self._notify()
