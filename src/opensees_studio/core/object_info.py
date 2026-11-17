"""Everything the model says about one joint or one element, tab by tab.

The right-click *Object Information* window (as SAP2000's *Object Model*
window): **Location** (where it is, what it connects), **Assignments**
(section, material, releases, restraints, mass, groups) and **Loads** (every
load on it, pattern by pattern, with its value). Where the hover tooltip
(:mod:`opensees_studio.core.hover`) gives a few lines and counts the rest, this
lists everything. Values are written in the display units.

No Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.load_display import format_force, format_line_load, format_pressure
from opensees_studio.core.loads import PlainLoadPattern
from opensees_studio.core.units import UnitConverter

_DOFS = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")
_FORCES = ("Fx", "Fy", "Fz", "Mx", "My", "Mz")


@dataclass(frozen=True)
class InfoTab:
    """One tab: a title and its ``(label, value)`` rows."""

    title: str
    rows: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ObjectInfo:
    """The window's title and its tabs."""

    title: str
    tabs: list[InfoTab]


def _num(value: float) -> str:
    return f"{value:.6g}"


def _length(value: float, units: UnitConverter) -> str:
    return f"{_num(value * units.length)} {units.labels.length}"


def _moment(value: float, units: UnitConverter) -> str:
    return f"{_num(value * units.moment)} {units.labels.moment}"


def _point(coords: Any, ndm: int, units: UnitConverter) -> str:
    x, y, z = (float(c) * units.length for c in coords)
    inner = f"{_num(x)}, {_num(z)}" if ndm == 2 else f"{_num(x)}, {_num(y)}, {_num(z)}"
    return f"({inner}) {units.labels.length}"


def _vector(vector: Any) -> str:
    # Rounded first, and + 0.0, so a -1e-17 component reads 0.0000, not -0.0000.
    return "(" + ", ".join(f"{round(float(v), 4) + 0.0:.4f}" for v in vector) + ")"


def _groups(project: Any, *, node_id: int | None = None, element_id: int | None = None) -> str:
    names = [
        g.name or f"Group {g.id}"
        for g in getattr(project, "groups", [])
        if (node_id is not None and node_id in g.node_ids)
        or (element_id is not None and element_id in g.element_ids)
    ]
    return ", ".join(names) or "none"


def _named(items: Any, item_id: int | None) -> str | None:
    """``"3: W14X30"`` for the item with ``item_id``; None when the element has none."""
    if item_id is None:
        return None
    item = next((x for x in items if x.id == item_id), None)
    if item is None:
        return f"{item_id}: missing"
    return f"{item_id}: {item.name or item.type}"


def _patterns(project: Any) -> list[Any]:
    return [p for p in project.load_patterns if isinstance(p, PlainLoadPattern)]


def _components(names: tuple[str, ...], values: Any, fmt: Any) -> str:
    return ", ".join(f"{n} {fmt(v)}" for n, v in zip(names, values, strict=False) if v) or "0"


# ─────────────────────────────── joints ───────────────────────────────
def node_info(project: Any, node_id: int) -> ObjectInfo | None:
    """The information of joint ``node_id``, or None when there is no such joint."""
    node = next((n for n in project.nodes if n.id == node_id), None)
    if node is None:
        return None
    units = UnitConverter.of(project.meta)
    members = [e for e in project.elements if node_id in e.nodes]
    location = [
        ("Joint", f"{node.id}" + (f"  {node.name}" if node.name else "")),
        ("Coordinates", _point(node.coords, project.ndm, units)),
        (
            "Connected elements",
            ", ".join(f"{e.id} ({e.type})" for e in members) or "none (loose joint)",
        ),
    ]
    fixed = [d for d, on in zip(_DOFS, node.restraint, strict=False) if on]
    assignments = [
        ("Restraints", ", ".join(fixed) or "none (free)"),
        ("Mass", ", ".join(_num(m) for m in node.mass) if any(node.mass) else "none"),
        ("Groups", _groups(project, node_id=node_id)),
    ]
    loads: list[tuple[str, str]] = []
    for pattern in _patterns(project):
        label = pattern.name or f"Pattern {pattern.id}"
        for load in pattern.nodal_loads:
            if load.node_id != node_id:
                continue
            forces = _components(_FORCES[:3], load.forces[:3], lambda v: format_force(v, units))
            moments = _components(_FORCES[3:], load.forces[3:], lambda v: _moment(v, units))
            parts = [text for text in (forces, moments) if text != "0"]
            loads.append((label, "Joint load: " + ("; ".join(parts) or "0")))
    return ObjectInfo(
        title=f"Joint {node.id}",
        tabs=[
            InfoTab("Location", location),
            InfoTab("Assignments", assignments),
            InfoTab("Loads", loads or [("Loads", "none")]),
        ],
    )


# ────────────────────────────── elements ──────────────────────────────
def _release_text(end: Any) -> str:
    released = list(getattr(end, "released", ()))
    if not released:
        return "none"
    springs = getattr(end, "springs", {}) or {}
    return ", ".join(
        f"{dof} (spring {_num(springs[dof])})" if dof in springs else dof for dof in released
    )


def _element_loads(
    project: Any, element_id: int, span: float | None, units: UnitConverter
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for pattern in _patterns(project):
        label = pattern.name or f"Pattern {pattern.id}"
        for load in pattern.element_loads:
            if load.element_id == element_id:
                parts = _components(
                    ("wx", "wy", "wz"),
                    (load.wx, load.wy, load.wz),
                    lambda v: format_line_load(v, None, units),
                )
                rows.append((label, f"Uniform, local: {parts}"))
        for load in pattern.point_loads:
            if load.element_id == element_id:
                parts = _components(
                    ("px", "py", "pz"),
                    (load.px, load.py, load.pz),
                    lambda v: format_force(v, units),
                )
                where = f"x/L = {_num(load.x)}"
                if span is not None:
                    where += f" ({_length(load.x * span, units)} from end i)"
                rows.append((label, f"Point, local: {parts} at {where}"))
        for load in pattern.distributed_loads:
            if load.element_id == element_id:
                start, end = load.start(), load.end()
                parts = ", ".join(
                    f"{name} {format_line_load(a, b, units)}"
                    for name, a, b in zip(("wx", "wy", "wz"), start, end, strict=True)
                    if a or b
                )
                rows.append(
                    (
                        label,
                        f"Distributed, local: {parts or '0'} from x/L = {_num(load.x_start)} "
                        f"to {_num(load.x_end)}",
                    )
                )
        for load in pattern.surface_loads:
            if load.element_id == element_id:
                by = (
                    f", by joint pattern {load.joint_pattern}"
                    if getattr(load, "joint_pattern", None)
                    else ""
                )
                rows.append(
                    (
                        label,
                        f"Surface: {format_pressure(load.value, units)}, direction {load.direction}{by}",
                    )
                )
        count = sum(1 for load in pattern.temperature_loads if load.element_id == element_id)
        if count:
            rows.append((label, f"Temperature: {count} load(s)"))
    return rows


def element_info(project: Any, element_id: int) -> ObjectInfo | None:
    """The information of element ``element_id``, or None when there is no such element."""
    element = next((e for e in project.elements if e.id == element_id), None)
    if element is None:
        return None
    units = UnitConverter.of(project.meta)
    coords = {n.id: n.coords for n in project.nodes}
    location = [
        ("Element", f"{element.id}" + (f"  {element.name}" if element.name else "")),
        ("Type", element.type),
    ]
    for index, node_id in enumerate(element.nodes):
        end = ("i", "j")[index] if len(element.nodes) == 2 else str(index + 1)
        where = _point(coords[node_id], project.ndm, units) if node_id in coords else "missing"
        location.append((f"Joint {end}", f"{node_id}  {where}"))
    span: float | None = None
    if len(element.nodes) == 2 and all(n in coords for n in element.nodes):
        pi, pj = coords[element.nodes[0]], coords[element.nodes[1]]
        span = math.dist(pi, pj)
        location.append(("Length", _length(span, units)))
        angle = float(getattr(element, "local_axis_angle", 0.0) or 0.0)
        axes = frame_local_axes(project.ndm, pi, pj, angle)
        if axes is not None:
            for name, axis in zip(("Local x", "Local y", "Local z"), axes, strict=True):
                location.append((name, _vector(axis)))

    assignments: list[tuple[str, str]] = []
    section = _named(project.sections, getattr(element, "section_id", None))
    if section is not None:
        assignments.append(("Section", section))
    material = _named(project.materials, getattr(element, "material_id", None))
    if material is not None:
        assignments.append(("Material", material))
    if hasattr(element, "local_axis_angle"):
        assignments.append(("Local axis angle", f"{_num(float(element.local_axis_angle or 0.0))}°"))
    releases = getattr(element, "releases", None)
    if releases is not None:
        assignments.append(("Releases, end i", _release_text(releases.i)))
        assignments.append(("Releases, end j", _release_text(releases.j)))
    assignments.append(("Groups", _groups(project, element_id=element_id)))

    loads = _element_loads(project, element_id, span, units)
    return ObjectInfo(
        title=f"{element.type} {element.id}",
        tabs=[
            InfoTab("Location", location),
            InfoTab("Assignments", assignments),
            InfoTab("Loads", loads or [("Loads", "none")]),
        ],
    )
