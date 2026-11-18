"""View → Color By: which category each element is drawn in.

The viewport can paint its frames and shells by **section**, by **material** or
by **group** instead of in one colour. This module decides the categories and
their colours from the project alone (pure: no Qt, no VTK), so the renderer and
the legend read the same answer and it can be tested on its own.

* **Section** — the sections an element references (``section_id``, the two
  hinge sections of a ``BeamWithHinges``); a member with none (a truss) falls
  in "(no section)".
* **Material** — every material the element reaches, directly or through its
  section's fibres (``core.selection.element_material_ids``); a reinforced
  concrete fibre section is one category, "concrete + steel".
* **Group** — the first group (in the project's order) that lists the element,
  drawn in that group's own colour; elements in no group fall in "(no group)".

Categories are ordered by their label so the colours do not change when an
unrelated element is added; colours come from a qualitative palette, and the
"no …" category always takes the viewport's ordinary colour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from opensees_studio.core.project import Project
from opensees_studio.core.selection import element_material_ids, element_section_ids
from opensees_studio.core.view_settings import ColorBy

COLOR_BY_MODES: tuple[ColorBy, ...] = ("none", "section", "material", "group")

#: Qualitative palette (Tableau 20 order, darker then lighter), cycled when a
#: model has more categories than colours.
PALETTE: tuple[str, ...] = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
    "#c49c94", "#f7b6d2", "#c7c7c7", "#dbdb8d", "#9edae5",
)  # fmt: skip


@dataclass
class Categories:
    """The categories of one colouring: labels, colours and each element's index."""

    labels: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    index: dict[int, int] = field(default_factory=dict)  # element id -> category

    def legend(self) -> list[tuple[str, str]]:
        """``(label, colour)`` pairs, in category order."""
        return list(zip(self.labels, self.colors, strict=True))


def _name(entity: Any, kind: str) -> str:
    name = getattr(entity, "name", "") or ""
    return f"#{entity.id} {name}".strip() if name else f"{kind} #{entity.id}"


def _keys(project: Project, mode: ColorBy) -> tuple[dict[int, str], dict[str, str]]:
    """Element id -> category label, and label -> a fixed colour where there is one."""
    by_element: dict[int, str] = {}
    fixed: dict[str, str] = {}
    if mode == "section":
        sections = {s.id: s for s in project.sections}
        for element in project.elements:
            ids = sorted(element_section_ids(element))
            names = [_name(sections[i], "Section") for i in ids if i in sections]
            by_element[element.id] = " + ".join(names) if names else "(no section)"
    elif mode == "material":
        materials = {m.id: m for m in project.materials}
        for element in project.elements:
            ids = sorted(element_material_ids(project, element))
            names = [_name(materials[i], "Material") for i in ids if i in materials]
            by_element[element.id] = " + ".join(names) if names else "(no material)"
    elif mode == "group":
        for group in reversed(project.groups):  # the first group listing it wins
            label = _name(group, "Group")
            fixed[label] = group.colour
            for element_id in group.element_ids:
                by_element[element_id] = label
        for element in project.elements:
            by_element.setdefault(element.id, "(no group)")
    return by_element, fixed


def element_categories(project: Project, mode: ColorBy, default_color: str) -> Categories:
    """The categories of ``mode`` for every element of ``project``.

    ``mode == "none"`` gives one category in ``default_color``.
    """
    if mode == "none":
        return Categories(
            labels=["All elements"],
            colors=[default_color],
            index={element.id: 0 for element in project.elements},
        )
    by_element, fixed = _keys(project, mode)
    labels = sorted(set(by_element.values()), key=lambda label: (label.startswith("("), label))
    colors: list[str] = []
    cycle = 0
    for label in labels:
        if label.startswith("("):
            colors.append(default_color)
        elif label in fixed:
            colors.append(fixed[label])
        else:
            colors.append(PALETTE[cycle % len(PALETTE)])
            cycle += 1
    position = {label: k for k, label in enumerate(labels)}
    return Categories(
        labels=labels,
        colors=colors,
        index={element_id: position[label] for element_id, label in by_element.items()},
    )
