"""Apply Edit → Interactive Table Editing: the edited model data in one undo step."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opensees_studio.commands.base import ProjectCommand

if TYPE_CHECKING:
    from opensees_studio.core import Project
    from opensees_studio.viewmodels import ProjectViewModel

TABLE_FIELDS = ("nodes", "elements", "load_patterns", "groups")
"""The project lists the tables edit; the rest of the model is left alone."""


class ApplyModelTablesCommand(ProjectCommand):
    """Put the joints, elements and load patterns of an edited copy into the project."""

    def __init__(self, vm: ProjectViewModel, edited: Project) -> None:
        super().__init__(vm, "Edit model tables")
        self._new = {name: list(getattr(edited, name)) for name in TABLE_FIELDS}
        self._old: dict[str, list[Any]] = {}

    def _put(self, values: dict[str, list[Any]]) -> None:
        for name, items in values.items():
            getattr(self.project, name)[:] = items

    def redo(self) -> None:
        self._old = {name: list(getattr(self.project, name)) for name in TABLE_FIELDS}
        self._put(self._new)
        self._notify()

    def undo(self) -> None:
        self._put(self._old)
        self._notify()
