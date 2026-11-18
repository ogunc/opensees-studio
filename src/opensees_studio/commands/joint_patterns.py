"""Commands for joint patterns (Define → Joint Patterns, Assign → Joint → Joint Pattern Values)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand
from opensees_studio.core.joint_patterns import JointPattern
from opensees_studio.core.loads import PlainLoadPattern

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class SetJointPatternsCommand(ProjectCommand):
    """Replace the joint pattern list, refusing to drop one a surface load uses."""

    def __init__(self, vm: ProjectViewModel, patterns: list[JointPattern], text: str = "") -> None:
        super().__init__(vm, text or f"Set {len(patterns)} joint pattern(s)")
        self._new = list(patterns)
        self._old: list[JointPattern] = []

    def redo(self) -> None:
        kept = {p.id for p in self._new}
        used = sorted(
            {
                load.joint_pattern_id
                for pattern in self.project.load_patterns
                if isinstance(pattern, PlainLoadPattern)
                for load in pattern.surface_loads
                if load.joint_pattern_id is not None and load.joint_pattern_id not in kept
            }
        )
        if used:
            names = {p.id: p.name or f"#{p.id}" for p in self.project.joint_patterns}
            raise ValueError(
                "Joint pattern(s) "
                + ", ".join(names.get(i, f"#{i}") for i in used)
                + " carry a surface load; remove those loads first."
            )
        self._old = list(self.project.joint_patterns)
        self.project.joint_patterns[:] = self._new
        self._notify()

    def undo(self) -> None:
        self.project.joint_patterns[:] = self._old
        self._notify()
