"""Commands for analysis case management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opensees_studio.commands.base import ProjectCommand

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class AddAnalysisCasesCommand(ProjectCommand):
    """Add one or more analysis cases."""

    def __init__(self, vm: "ProjectViewModel", cases: list[Any], *,
                 text: str | None = None) -> None:
        super().__init__(vm, text or f"Add {len(cases)} analysis case(s)")
        self._cases = list(cases)

    def redo(self) -> None:
        existing = {c.id for c in self.project.analyses}
        for case in self._cases:
            if case.id in existing:
                raise ValueError(f"Analysis case id {case.id} already exists.")
        self.project.analyses.extend(self._cases)
        self._notify()

    def undo(self) -> None:
        ids = {c.id for c in self._cases}
        self.project.analyses[:] = [c for c in self.project.analyses if c.id not in ids]
        self._notify()


class DeleteAnalysisCasesCommand(ProjectCommand):
    """Remove a set of analysis cases."""

    def __init__(self, vm: "ProjectViewModel", case_ids: set[int]) -> None:
        super().__init__(vm, f"Delete {len(case_ids)} analysis case(s)")
        self._case_ids = set(case_ids)
        self._removed: list[tuple[int, Any]] = []

    def redo(self) -> None:
        self._removed = [
            (i, c) for i, c in enumerate(self.project.analyses)
            if c.id in self._case_ids
        ]
        self.project.analyses[:] = [
            c for c in self.project.analyses if c.id not in self._case_ids
        ]
        self._notify()

    def undo(self) -> None:
        for i, c in self._removed:
            self.project.analyses.insert(min(i, len(self.project.analyses)), c)
        self._removed.clear()
        self._notify()


class UpdateAnalysisCaseCommand(ProjectCommand):
    """Replace an analysis case at a given id."""

    def __init__(self, vm: "ProjectViewModel", new_case: Any) -> None:
        super().__init__(vm, f"Edit analysis case {new_case.id}")
        self._new = new_case
        self._old: Any | None = None
        self._index: int | None = None

    def redo(self) -> None:
        for i, c in enumerate(self.project.analyses):
            if c.id == self._new.id:
                self._old = c
                self._index = i
                self.project.analyses[i] = self._new
                self._notify()
                return
        raise KeyError(f"Analysis case with id={self._new.id} not found.")

    def undo(self) -> None:
        if self._old is not None and self._index is not None:
            self.project.analyses[self._index] = self._old
        self._notify()
