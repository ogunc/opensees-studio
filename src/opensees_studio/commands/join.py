"""Edit → Join Frames: one undo step around :func:`core.geometry.join.join_frames`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opensees_studio.commands.base import ProjectCommand, restore_project, snapshot_project
from opensees_studio.core.geometry.join import JoinReport, join_frames

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class JoinFramesCommand(ProjectCommand):
    """Join the selected frames that continue each other; undo restores the pieces."""

    def __init__(self, vm: ProjectViewModel, element_ids: set[int]) -> None:
        super().__init__(vm, f"Join frames ({len(element_ids)} selected)")
        self._element_ids = set(element_ids)
        self._before: dict[str, Any] | None = None
        self.report = JoinReport()

    def redo(self) -> None:
        self._before = snapshot_project(self.project)
        self.report = join_frames(self.project, self._element_ids)
        self._notify()

    def undo(self) -> None:
        if self._before is not None:
            restore_project(self.project, self._before)
        self._notify()
