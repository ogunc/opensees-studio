"""Commands for load combinations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand
from opensees_studio.core import LoadCombination

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class AddCombinationsCommand(ProjectCommand):
    """Add one or more load combinations."""

    def __init__(
        self,
        vm: ProjectViewModel,
        combinations: list[LoadCombination],
        *,
        text: str | None = None,
    ) -> None:
        super().__init__(vm, text or f"Add {len(combinations)} load combination(s)")
        self._combinations = list(combinations)

    def redo(self) -> None:
        existing = {c.id for c in self.project.combinations}
        for combo in self._combinations:
            if combo.id in existing:
                raise ValueError(f"Load combination id {combo.id} already exists.")
        self.project.combinations.extend(self._combinations)
        self._notify()

    def undo(self) -> None:
        ids = {c.id for c in self._combinations}
        self.project.combinations[:] = [c for c in self.project.combinations if c.id not in ids]
        self._notify()


class DeleteCombinationsCommand(ProjectCommand):
    """Remove a set of load combinations."""

    def __init__(self, vm: ProjectViewModel, combination_ids: set[int]) -> None:
        super().__init__(vm, f"Delete {len(combination_ids)} load combination(s)")
        self._ids = set(combination_ids)
        self._removed: list[tuple[int, LoadCombination]] = []

    def redo(self) -> None:
        self._removed = [
            (i, c) for i, c in enumerate(self.project.combinations) if c.id in self._ids
        ]
        self.project.combinations[:] = [
            c for c in self.project.combinations if c.id not in self._ids
        ]
        self._notify()

    def undo(self) -> None:
        for i, c in self._removed:
            self.project.combinations.insert(min(i, len(self.project.combinations)), c)
        self._removed.clear()
        self._notify()


class UpdateCombinationCommand(ProjectCommand):
    """Replace the load combination with the same id."""

    def __init__(self, vm: ProjectViewModel, new_combination: LoadCombination) -> None:
        super().__init__(vm, f"Edit load combination '{new_combination.name}'")
        self._new = new_combination
        self._old: LoadCombination | None = None
        self._index: int | None = None

    def redo(self) -> None:
        for i, c in enumerate(self.project.combinations):
            if c.id == self._new.id:
                self._old = c
                self._index = i
                self.project.combinations[i] = self._new
                self._notify()
                return
        raise KeyError(f"Load combination with id={self._new.id} not found.")

    def undo(self) -> None:
        if self._old is not None and self._index is not None:
            self.project.combinations[self._index] = self._old
        self._notify()
