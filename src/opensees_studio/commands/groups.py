"""Commands for groups (Define → Groups, Assign → Assign to Group) and section cuts."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand
from opensees_studio.core.custom_commands import CustomCommandBlock
from opensees_studio.core.groups import Group, with_members
from opensees_studio.core.section_cuts import SectionCut

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class SetGroupsCommand(ProjectCommand):
    """Replace the group list (Define → Groups)."""

    def __init__(self, vm: ProjectViewModel, groups: list[Group]) -> None:
        super().__init__(vm, f"Set {len(groups)} group(s)")
        self._new = list(groups)
        self._old: list[Group] = []

    def redo(self) -> None:
        kept = {g.id for g in self._new}
        used = [c.name or str(c.id) for c in self.project.section_cuts if c.group_id not in kept]
        if used:
            raise ValueError(
                "Section cut(s) " + ", ".join(used) + " use a group that would be removed; "
                "delete them first (Define → Section Cuts)."
            )
        self._old = list(self.project.groups)
        self.project.groups[:] = self._new
        self._notify()

    def undo(self) -> None:
        self.project.groups[:] = self._old
        self._notify()


class SetSectionCutsCommand(ProjectCommand):
    """Replace the section cut list (Define → Section Cuts)."""

    def __init__(self, vm: ProjectViewModel, cuts: list[SectionCut]) -> None:
        super().__init__(vm, f"Set {len(cuts)} section cut(s)")
        self._new = list(cuts)
        self._old: list[SectionCut] = []

    def redo(self) -> None:
        self._old = list(self.project.section_cuts)
        self.project.section_cuts[:] = self._new
        self._notify()

    def undo(self) -> None:
        self.project.section_cuts[:] = self._old
        self._notify()


class EditGroupMembersCommand(ProjectCommand):
    """Add joints and elements to a group, remove them, or make them its only members."""

    def __init__(
        self,
        vm: ProjectViewModel,
        group_id: int,
        nodes: Iterable[int] = (),
        elements: Iterable[int] = (),
        *,
        mode: str = "add",
    ) -> None:
        nodes, elements = list(nodes), list(elements)
        verb = {"add": "Add to", "remove": "Remove from", "replace": "Set"}[mode]
        super().__init__(
            vm, f"{verb} group {group_id}: {len(nodes)} joint(s), {len(elements)} element(s)"
        )
        self._group_id = group_id
        self._nodes, self._elements, self._mode = nodes, elements, mode
        self._old: Group | None = None

    def _index(self) -> int:
        for index, group in enumerate(self.project.groups):
            if group.id == self._group_id:
                return index
        raise KeyError(f"Group with id={self._group_id} not found.")

    def redo(self) -> None:
        index = self._index()
        self._old = self.project.groups[index]
        self.project.groups[index] = with_members(
            self._old, self._nodes, self._elements, mode=self._mode
        )
        self._notify()

    def undo(self) -> None:
        if self._old is not None:
            self.project.groups[self._index()] = self._old
        self._notify()


class SetCustomCommandsCommand(ProjectCommand):
    """Replace the custom command blocks (Define → Custom OpenSees Commands)."""

    def __init__(self, vm: ProjectViewModel, blocks: list[CustomCommandBlock]) -> None:
        super().__init__(vm, f"Set {len(blocks)} custom command block(s)")
        self._new = list(blocks)
        self._old: list[CustomCommandBlock] = []

    def redo(self) -> None:
        self._old = list(self.project.custom_commands)
        self.project.custom_commands[:] = self._new
        self._notify()

    def undo(self) -> None:
        self.project.custom_commands[:] = self._old
        self._notify()
