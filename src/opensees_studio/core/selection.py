"""Selection queries: which nodes and elements match a property.

The Select menu adds these to (or inverts) the current selection; the queries
themselves are pure and read only the project, so they are tested without Qt.

Materials are found wherever an element can reach them: its own material fields
(``material_id``, ``material_ids``, a bearing's ``p_material_id`` …) and those of
every section it references, followed through an aggregator's base section, so
"select by material" picks a frame whose fiber section has a fibre of it.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from opensees_studio.core.loads import PlainLoadPattern
from opensees_studio.core.project import Project
from opensees_studio.core.self_weight import is_weighted


def _ids_in(data: Any, suffix: str) -> Iterator[int]:
    """Every int stored under a key ending in ``suffix`` or ``suffix + 's'``, at any depth."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key.endswith(suffix) and isinstance(value, int):
                yield value
            elif key.endswith(suffix + "s") and isinstance(value, list | tuple):
                yield from (v for v in value if isinstance(v, int))
            else:
                yield from _ids_in(value, suffix)
    elif isinstance(data, list | tuple):
        for item in data:
            yield from _ids_in(item, suffix)


def element_section_ids(element: Any) -> set[int]:
    """Ids of the sections an element references (``section_id``, ``section_i_id`` …)."""
    return {
        value
        for key, value in element.model_dump().items()
        if key.startswith("section") and key.endswith("id") and isinstance(value, int)
    }


def _section_material_ids(project: Project, section_id: int, seen: set[int]) -> set[int]:
    if section_id in seen:
        return set()
    seen.add(section_id)
    section = next((s for s in project.sections if s.id == section_id), None)
    if section is None:
        return set()
    data = section.model_dump()
    found = set(_ids_in(data, "material_id"))
    base = data.get("section_id")
    if isinstance(base, int):
        found |= _section_material_ids(project, base, seen)
    return found


def element_material_ids(project: Project, element: Any) -> set[int]:
    """Ids of every material an element uses, directly or through its sections."""
    found = set(_ids_in(element.model_dump(), "material_id"))
    seen: set[int] = set()
    for section_id in element_section_ids(element):
        found |= _section_material_ids(project, section_id, seen)
    return found


# ──────────────────────────── element queries ────────────────────────────
def element_types(project: Project) -> list[str]:
    """The element types present in the model, sorted."""
    return sorted({element.type for element in project.elements})


def elements_of_type(project: Project, element_type: str) -> set[int]:
    return {element.id for element in project.elements if element.type == element_type}


def sections_in_use(project: Project) -> list[Any]:
    """The sections that at least one element references, in project order."""
    used: set[int] = set()
    for element in project.elements:
        used |= element_section_ids(element)
    return [section for section in project.sections if section.id in used]


def elements_with_section(project: Project, section_id: int) -> set[int]:
    return {
        element.id for element in project.elements if section_id in element_section_ids(element)
    }


def materials_in_use(project: Project) -> list[Any]:
    """The materials that at least one element uses, in project order."""
    used: set[int] = set()
    for element in project.elements:
        used |= element_material_ids(project, element)
    return [material for material in project.materials if material.id in used]


def elements_with_material(project: Project, material_id: int) -> set[int]:
    return {
        element.id
        for element in project.elements
        if material_id in element_material_ids(project, element)
    }


def weighted_elements(project: Project) -> set[int]:
    """The frames and shells that carry a self weight (section with a unit weight)."""
    return {element.id for element in project.elements if is_weighted(project, element)}


# ──────────────────────────── node queries ────────────────────────────
def restrained_nodes(project: Project) -> set[int]:
    """Nodes with at least one restrained DOF (the supports)."""
    return {node.id for node in project.nodes if any(node.restraint)}


def nodes_with_mass(project: Project) -> set[int]:
    return {node.id for node in project.nodes if any(node.mass)}


def nodes_of_elements(project: Project, element_ids: Iterable[int]) -> set[int]:
    """Every node of the given elements."""
    wanted = set(element_ids)
    return {
        node_id for element in project.elements if element.id in wanted for node_id in element.nodes
    }


def elements_within_nodes(project: Project, node_ids: Iterable[int]) -> set[int]:
    """Elements whose every node is in ``node_ids`` (the members a node window encloses)."""
    nodes = set(node_ids)
    return {element.id for element in project.elements if all(n in nodes for n in element.nodes)}


# ──────────────────────────── load queries ────────────────────────────
def loaded_by_pattern(project: Project, pattern_id: int) -> tuple[set[int], set[int]]:
    """``(node ids, element ids)`` that a plain pattern loads.

    A self-weight pattern loads every weighted frame and shell; a support-motion pattern
    the nodes it drives.
    """
    pattern = next((p for p in project.load_patterns if p.id == pattern_id), None)
    if pattern is None:
        return set(), set()
    if not isinstance(pattern, PlainLoadPattern):
        return set(getattr(pattern, "node_ids", ())), set()
    nodes = {load.node_id for load in pattern.nodal_loads}
    elements = {load.element_id for load in pattern.element_loads}
    elements |= {load.element_id for load in pattern.point_loads}
    elements |= {load.element_id for load in pattern.distributed_loads}
    elements |= {load.element_id for load in pattern.surface_loads}
    elements |= {load.element_id for load in pattern.temperature_loads}
    nodes |= {load.node_id for load in pattern.imposed_displacements}
    for floor in pattern.floor_loads:
        nodes |= set(floor.nodes)
    if pattern.self_weight:
        elements |= weighted_elements(project)
    return nodes, elements


def invert(
    project: Project, nodes: Iterable[int], elements: Iterable[int]
) -> tuple[set[int], set[int]]:
    """Everything that is not selected, and nothing that is."""
    return (
        {node.id for node in project.nodes} - set(nodes),
        {element.id for element in project.elements} - set(elements),
    )


def implied_node_ids(
    project: Project,
    node_ids: Iterable[int],
    element_ids: Iterable[int],
) -> set[int]:
    """Selected nodes plus the joints of every selected element.

    A frame is defined by its joints, so moving, copying or mirroring a member
    means acting on those joints and the user should not have to pick the nodes
    first. A joint shared with an element that is not selected still moves:
    that is how a joint edit behaves in a frame program, the connected member
    follows its joint.
    """
    nodes = set(node_ids)
    wanted = set(element_ids)
    if not wanted:
        return nodes
    for element in project.elements:
        if element.id in wanted:
            nodes.update(element.nodes)
    return nodes


def elements_with_nodes_inside(project: Project, node_ids: Iterable[int]) -> set[int]:
    """Elements whose every joint is in ``node_ids``.

    The rule for a box selection: a member counts only when both of its ends
    are inside, so a member that merely crosses the rectangle is left out.
    """
    inside = set(node_ids)
    return {
        element.id
        for element in project.elements
        if element.nodes and all(nid in inside for nid in element.nodes)
    }


def _segment_hits_rect(
    a: tuple[float, float],
    b: tuple[float, float],
    rect: tuple[float, float, float, float],
) -> bool:
    """True when the segment ``a-b`` enters the rectangle (Liang-Barsky)."""
    xmin, xmax, ymin, ymax = rect
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in (
        (-dx, a[0] - xmin),
        (dx, xmax - a[0]),
        (-dy, a[1] - ymin),
        (dy, ymax - a[1]),
    ):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def box_selection(
    project: Project,
    display: dict[int, tuple[float, float]],
    rect: tuple[float, float, float, float],
    *,
    crossing: bool,
    hidden_nodes: Iterable[int] = (),
    hidden_elements: Iterable[int] = (),
) -> tuple[set[int], set[int]]:
    """Select what a rubber-band rectangle encloses.

    ``display`` maps node id to its screen position; ``rect`` is
    ``(xmin, xmax, ymin, ymax)`` in the same space. A node is selected when it
    falls inside. An element is selected when every one of its joints is inside,
    and — when ``crossing`` is true — also when one of its edges merely crosses
    the rectangle, which is what the "select what it touches" drag does.

    ``hidden_nodes`` and ``hidden_elements`` are the viewport's hidden ids. They
    are never returned, so a box cannot select something that is not drawn.
    Hidden nodes still contribute their projected geometry to a visible member,
    which is what the renderer draws for that member.
    """
    xmin, xmax, ymin, ymax = rect
    hidden_node_ids = set(hidden_nodes)
    hidden_element_ids = set(hidden_elements)

    def inside(node_id: int) -> bool:
        point = display.get(node_id)
        if point is None:
            return False
        return xmin <= point[0] <= xmax and ymin <= point[1] <= ymax

    nodes = {node_id for node_id in display if node_id not in hidden_node_ids and inside(node_id)}
    elements: set[int] = set()
    for element in project.elements:
        if element.id in hidden_element_ids:
            continue
        joints = [node_id for node_id in element.nodes if node_id in display]
        if not joints:
            continue
        if all(inside(node_id) for node_id in element.nodes):
            elements.add(element.id)
            continue
        if not crossing:
            continue
        if any(inside(node_id) for node_id in joints):
            elements.add(element.id)
            continue
        points = [display[node_id] for node_id in joints]
        if any(_segment_hits_rect(points[k], points[k + 1], rect) for k in range(len(points) - 1)):
            elements.add(element.id)
    return nodes, elements
