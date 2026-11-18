"""Undoable replacement of the project's AISC 358 connections."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand

if TYPE_CHECKING:
    from opensees_studio.core.design.connections import RbsConnection
    from opensees_studio.viewmodels import ProjectViewModel


class SetConnectionsCommand(ProjectCommand):
    """Replace ``Project.connections`` (add, edit or remove RBS entries)."""

    def __init__(self, vm: ProjectViewModel, connections: list[RbsConnection]) -> None:
        super().__init__(vm, f"Set {len(connections)} connection(s)")
        self._new = list(connections)
        self._old: list[RbsConnection] | None = None

    def redo(self) -> None:
        self._old = list(self.project.connections)
        self.project.connections = list(self._new)
        self._notify()

    def undo(self) -> None:
        if self._old is not None:
            self.project.connections = list(self._old)
        self._notify()
