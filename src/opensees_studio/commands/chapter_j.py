"""Undoable replacement of the project's Chapter J connection checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand

if TYPE_CHECKING:
    from opensees_studio.core.design.chapter_j_model import ChapterJCheck
    from opensees_studio.viewmodels import ProjectViewModel


class SetChapterJChecksCommand(ProjectCommand):
    """Replace ``Project.chapter_j_checks`` (add, edit or remove checks)."""

    def __init__(self, vm: ProjectViewModel, checks: list[ChapterJCheck]) -> None:
        super().__init__(vm, f"Set {len(checks)} Chapter J check(s)")
        self._new = list(checks)
        self._old: list[ChapterJCheck] | None = None

    def redo(self) -> None:
        self._old = list(self.project.chapter_j_checks)
        self.project.chapter_j_checks = list(self._new)
        self._notify()

    def undo(self) -> None:
        if self._old is not None:
            self.project.chapter_j_checks = list(self._old)
        self._notify()
