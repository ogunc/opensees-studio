"""Undoable change of the project information used by the report cover."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand

if TYPE_CHECKING:
    from opensees_studio.core import ProjectMeta
    from opensees_studio.viewmodels import ProjectViewModel


class SetProjectMetaCommand(ProjectCommand):
    """Replace ``Project.meta`` (name, author, company, date, revisions)."""

    def __init__(self, vm: ProjectViewModel, meta: ProjectMeta) -> None:
        super().__init__(vm, "Edit project information")
        self._new = meta
        self._old: ProjectMeta | None = None

    def redo(self) -> None:
        self._old = self.project.meta
        self.project.meta = self._new
        self._notify()

    def undo(self) -> None:
        if self._old is not None:
            self.project.meta = self._old
        self._notify()
