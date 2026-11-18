"""Undoable replacement of the project's SCBF column splices."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand

if TYPE_CHECKING:
    from opensees_studio.core.design.column_splice_model import ColumnSplice
    from opensees_studio.viewmodels import ProjectViewModel


class SetColumnSplicesCommand(ProjectCommand):
    """Replace ``Project.column_splices`` (add, edit or remove splices)."""

    def __init__(self, vm: ProjectViewModel, splices: list[ColumnSplice]) -> None:
        super().__init__(vm, f"Set {len(splices)} column splice(s)")
        self._new = list(splices)
        self._old: list[ColumnSplice] | None = None

    def redo(self) -> None:
        self._old = list(self.project.column_splices)
        self.project.column_splices = list(self._new)
        self._notify()

    def undo(self) -> None:
        if self._old is not None:
            self.project.column_splices = list(self._old)
        self._notify()
