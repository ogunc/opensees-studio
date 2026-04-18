"""Commands that mutate the project's coordinate/grid systems."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand
from opensees_studio.core.geometry import CoordinateGridSystem, GridSystem

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class SetCoordSystemsCommand(ProjectCommand):
    """Replace the project's full list of coordinate/grid systems atomically.

    Used by the Coordinate/Grid Systems dialog which edits the whole
    list at once (add / copy / modify / delete all go through here).
    """

    def __init__(
        self,
        vm: "ProjectViewModel",
        new_systems: list[CoordinateGridSystem],
    ) -> None:
        super().__init__(vm, "Update coordinate/grid systems")
        self._new = list(new_systems)
        self._previous: list[CoordinateGridSystem] | None = None

    def redo(self) -> None:
        self._previous = [cs.model_copy(deep=True) for cs in self.project.coord_systems]
        self.project.coord_systems = list(self._new)
        self._notify()

    def undo(self) -> None:
        if self._previous is not None:
            self.project.coord_systems = list(self._previous)
        self._notify()


class SetGridSystemCommand(ProjectCommand):
    """Compat: update the Global system's grid lines in one undoable step.

    Retained for existing callers (the single-grid dialog path). New code
    should prefer :class:`SetCoordSystemsCommand` which can edit multiple
    systems at once.
    """

    def __init__(self, vm: "ProjectViewModel", new_grid: GridSystem) -> None:
        super().__init__(vm, "Update grid system")
        self._new_grid = new_grid
        self._previous: GridSystem | None = None

    def redo(self) -> None:
        # Replace the grid on the Global system.
        for i, cs in enumerate(self.project.coord_systems):
            if cs.name == "Global":
                self._previous = cs.grid.model_copy(deep=True)
                self.project.coord_systems[i] = cs.model_copy(
                    update={"grid": self._new_grid},
                )
                break
        self._notify()

    def undo(self) -> None:
        if self._previous is None:
            return
        for i, cs in enumerate(self.project.coord_systems):
            if cs.name == "Global":
                self.project.coord_systems[i] = cs.model_copy(
                    update={"grid": self._previous},
                )
                break
        self._notify()
