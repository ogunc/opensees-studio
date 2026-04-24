"""Commands for multi-point constraints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand
from opensees_studio.core import EqualDOFConstraint

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class AddEqualDOFConstraintCommand(ProjectCommand):
    """Append an ``equalDOF`` constraint to the project (undoable)."""

    def __init__(self, vm: "ProjectViewModel", constraint: EqualDOFConstraint) -> None:
        super().__init__(
            vm,
            f"Add equalDOF {constraint.retained_node}->{constraint.constrained_node}",
        )
        self._constraint = constraint

    def redo(self) -> None:
        for mp in self.project.mp_constraints:
            if (
                mp.retained_node == self._constraint.retained_node
                and mp.constrained_node == self._constraint.constrained_node
                and tuple(mp.dofs) == tuple(self._constraint.dofs)
            ):
                raise ValueError("An identical equalDOF constraint already exists.")
        self.project.mp_constraints.append(self._constraint)
        self._notify()

    def undo(self) -> None:
        self.project.mp_constraints[:] = [
            mp for mp in self.project.mp_constraints
            if mp != self._constraint
        ]
        self._notify()
