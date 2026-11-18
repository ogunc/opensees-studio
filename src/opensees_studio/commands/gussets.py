"""Undoable replacement of the project's SCBF gusset plates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand

if TYPE_CHECKING:
    from opensees_studio.core.design.gusset_model import Gusset
    from opensees_studio.viewmodels import ProjectViewModel


class SetGussetsCommand(ProjectCommand):
    """Replace ``Project.gussets`` (add, edit or remove plates)."""

    def __init__(self, vm: ProjectViewModel, gussets: list[Gusset]) -> None:
        super().__init__(vm, f"Set {len(gussets)} gusset(s)")
        self._new = list(gussets)
        self._old: list[Gusset] | None = None

    def redo(self) -> None:
        self._old = list(self.project.gussets)
        self.project.gussets = list(self._new)
        self._notify()

    def undo(self) -> None:
        if self._old is not None:
            self.project.gussets = list(self._old)
        self._notify()
