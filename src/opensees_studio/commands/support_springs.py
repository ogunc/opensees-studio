"""Command for line, edge and area springs (Assign → Frame → Line Springs, Assign → Area → …)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand
from opensees_studio.core.support_springs import AreaSpring, EdgeSpring, LineSpring

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class SetSupportSpringsCommand(ProjectCommand):
    """Replace the three distributed-spring lists in one undo step."""

    def __init__(
        self,
        vm: ProjectViewModel,
        area: list[AreaSpring],
        line: list[LineSpring],
        edge: list[EdgeSpring],
        text: str = "Assign springs",
    ) -> None:
        super().__init__(vm, text)
        self._new = (list(area), list(line), list(edge))
        self._old: tuple[list[AreaSpring], list[LineSpring], list[EdgeSpring]] = ([], [], [])

    def redo(self) -> None:
        p = self.project
        self._old = (list(p.area_springs), list(p.line_springs), list(p.edge_springs))
        p.area_springs[:], p.line_springs[:], p.edge_springs[:] = self._new
        self._notify()

    def undo(self) -> None:
        p = self.project
        p.area_springs[:], p.line_springs[:], p.edge_springs[:] = self._old
        self._notify()
