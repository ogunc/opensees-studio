"""Groups: named sets of joints and elements (SAP2000 / ETABS "groups").

A :class:`Group` is a name, the ids of the joints and elements it holds, and a
colour for the canvas. Groups carry no mechanics: they let the engineer select
a part of the model again later (Select → By Group), show it alone, edit it in
the tables, or define a section cut through it.

Membership is kept clean by the delete commands (:func:`prune_groups`), so a
group never names a joint or element the model no longer has. A joint or an
element may belong to any number of groups.

No Qt, no OpenSees.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from pydantic import Field, field_validator

from opensees_studio.core._base import Entity

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

GROUP_COLOURS = (
    "#e6194b",
    "#3cb44b",
    "#4363d8",
    "#f58231",
    "#911eb4",
    "#42d4f4",
    "#f032e6",
    "#bfef45",
    "#9a6324",
    "#469990",
)
"""The colours new groups cycle through (Define → Groups)."""


class Group(Entity):
    """A named set of joints and elements."""

    node_ids: list[int] = Field(default_factory=list, description="Joints in the group.")
    element_ids: list[int] = Field(default_factory=list, description="Elements in the group.")
    colour: str = Field(default="#4363d8", description="Display colour, #rrggbb.")

    @field_validator("node_ids", "element_ids")
    @classmethod
    def _sorted_unique(cls, ids: list[int]) -> list[int]:
        return sorted(set(ids))

    @field_validator("colour")
    @classmethod
    def _hex_colour(cls, colour: str) -> str:
        text = colour.strip().lower()
        if len(text) != 7 or text[0] != "#" or any(c not in "0123456789abcdef" for c in text[1:]):
            raise ValueError(f"Group colour must be #rrggbb, got {colour!r}.")
        return text

    @property
    def size(self) -> int:
        return len(self.node_ids) + len(self.element_ids)


def colour_for(index: int) -> str:
    """The colour a new group gets when ``index`` groups already exist."""
    return GROUP_COLOURS[index % len(GROUP_COLOURS)]


def group_named(project: Project, name: str) -> Group | None:
    """The group called ``name`` (case-insensitive), or ``None``."""
    wanted = name.strip().casefold()
    return next((g for g in project.groups if g.name.strip().casefold() == wanted), None)


def group_members(project: Project, group_id: int) -> tuple[set[int], set[int]]:
    """``(joints, elements)`` of a group, limited to what the model holds."""
    group = next((g for g in project.groups if g.id == group_id), None)
    if group is None:
        return set(), set()
    nodes = {n.id for n in project.nodes}
    elements = {e.id for e in project.elements}
    return set(group.node_ids) & nodes, set(group.element_ids) & elements


def groups_of(
    project: Project, *, node_id: int | None = None, element_id: int | None = None
) -> list[Group]:
    """The groups a joint (or an element) belongs to, in the project's order."""
    return [
        g
        for g in project.groups
        if (node_id is not None and node_id in g.node_ids)
        or (element_id is not None and element_id in g.element_ids)
    ]


def with_members(
    group: Group,
    nodes: Iterable[int] = (),
    elements: Iterable[int] = (),
    *,
    mode: str = "add",
) -> Group:
    """A copy of ``group`` with ``nodes`` / ``elements`` added, removed or replacing it.

    ``mode`` is ``"add"``, ``"remove"`` or ``"replace"``.
    """
    node_set, element_set = set(nodes), set(elements)
    if mode == "add":
        new_nodes = set(group.node_ids) | node_set
        new_elements = set(group.element_ids) | element_set
    elif mode == "remove":
        new_nodes = set(group.node_ids) - node_set
        new_elements = set(group.element_ids) - element_set
    elif mode == "replace":
        new_nodes, new_elements = node_set, element_set
    else:
        raise ValueError(f"Unknown group edit mode {mode!r}.")
    return group.model_copy(
        update={"node_ids": sorted(new_nodes), "element_ids": sorted(new_elements)}
    )


def prune_groups(project: Project) -> bool:
    """Drop from every group the joints and elements the model no longer has.

    Returns ``True`` when a group changed. The delete commands call it after
    they remove joints or elements and restore the old list on undo.
    """
    nodes = {n.id for n in project.nodes}
    elements = {e.id for e in project.elements}
    changed = False
    for index, group in enumerate(project.groups):
        kept_nodes = [i for i in group.node_ids if i in nodes]
        kept_elements = [i for i in group.element_ids if i in elements]
        if kept_nodes != group.node_ids or kept_elements != group.element_ids:
            project.groups[index] = group.model_copy(
                update={"node_ids": kept_nodes, "element_ids": kept_elements}
            )
            changed = True
    return changed


def group_problems(project: Project) -> list[str]:
    """Reference problems of the groups: duplicate names, missing joints or elements."""
    problems: list[str] = []
    seen: dict[str, int] = {}
    nodes = {n.id for n in project.nodes}
    elements = {e.id for e in project.elements}
    for group in project.groups:
        key = group.name.strip().casefold()
        if key and key in seen:
            problems.append(f"Groups {seen[key]} and {group.id} share the name {group.name!r}.")
        seen.setdefault(key, group.id)
        missing_nodes = [i for i in group.node_ids if i not in nodes]
        missing_elements = [i for i in group.element_ids if i not in elements]
        if missing_nodes:
            problems.append(
                f"Group {group.name or group.id} holds missing joint(s) {missing_nodes[:10]}."
            )
        if missing_elements:
            problems.append(
                f"Group {group.name or group.id} holds missing element(s) {missing_elements[:10]}."
            )
    return problems
