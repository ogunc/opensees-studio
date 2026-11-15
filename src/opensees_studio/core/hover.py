"""What the viewport says about the joint or element under the pointer.

A few lines for a tooltip: the object's id and kind, where it is, what is
assigned to it (section, restraint, mass) and the loads it carries in each
pattern. The point is to read the model by hovering it instead of selecting
every object and opening its Properties.

No Qt.
"""

from __future__ import annotations

import math
from typing import Any

from opensees_studio.core.loads import PlainLoadPattern
from opensees_studio.core.units import labels_for

#: Restraint patterns with a name (Ux, Uy, Uz, Rx, Ry, Rz).
_RESTRAINT_NAMES: dict[tuple[bool, ...], str] = {
    (True,) * 6: "fixed",
    (True, True, True, False, False, False): "pinned",
    (False, False, True, False, False, False): "roller (Z)",
}
_DOFS = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")

#: At most this many load lines; the rest is counted.
MAX_LOAD_LINES = 6


def _fmt(value: float) -> str:
    return f"{value:.4g}"


def _units(project: Any) -> tuple[str, str]:
    try:
        labels = labels_for(project.meta.units)
    except Exception:
        return "", ""
    return labels.length, labels.force


def _restraint_text(restraint: tuple[bool, ...]) -> str:
    if not any(restraint):
        return ""
    named = _RESTRAINT_NAMES.get(tuple(restraint))
    fixed = ", ".join(d for d, on in zip(_DOFS, restraint, strict=False) if on)
    return f"Restraint: {named} ({fixed})" if named else f"Restraint: {fixed}"


def _load_lines(entries: list[str]) -> list[str]:
    if len(entries) <= MAX_LOAD_LINES:
        return entries
    return [*entries[:MAX_LOAD_LINES], f"… and {len(entries) - MAX_LOAD_LINES} more load(s)"]


def node_summary(project: Any, node_id: int) -> str | None:
    """Tooltip text of joint ``node_id``, or None when there is no such joint."""
    node = next((n for n in project.nodes if n.id == node_id), None)
    if node is None:
        return None
    length, force = _units(project)
    x, y, z = node.coords
    where = f"({_fmt(x)}, {_fmt(z)})" if project.ndm == 2 else f"({_fmt(x)}, {_fmt(y)}, {_fmt(z)})"
    lines = [f"Joint {node.id}{' ' + repr(node.name) if node.name else ''}  {where} {length}"]
    restraint = _restraint_text(tuple(node.restraint))
    if restraint:
        lines.append(restraint)
    if any(abs(m) > 0.0 for m in node.mass):
        lines.append("Mass: " + ", ".join(_fmt(m) for m in node.mass))
    members = [e.id for e in project.elements if node_id in e.nodes]
    lines.append(f"Elements: {', '.join(map(str, members))}" if members else "No element (loose)")
    loads = []
    for pattern in project.load_patterns:
        if not isinstance(pattern, PlainLoadPattern):
            continue
        for load in pattern.nodal_loads:
            if load.node_id == node_id:
                parts = [
                    f"{name} {_fmt(v)}"
                    for name, v in zip(
                        ("Fx", "Fy", "Fz", "Mx", "My", "Mz"), load.forces, strict=False
                    )
                    if v
                ]
                loads.append(f"{pattern.name or pattern.id}: {', '.join(parts) or '0'} {force}")
    return "\n".join(lines + _load_lines(loads))


def element_summary(project: Any, element_id: int) -> str | None:
    """Tooltip text of element ``element_id``, or None when there is no such element."""
    element = next((e for e in project.elements if e.id == element_id), None)
    if element is None:
        return None
    length, force = _units(project)
    nodes = "-".join(str(n) for n in element.nodes)
    lines = [f"{element.type} {element.id}{' ' + repr(element.name) if element.name else ''}"]
    coords = {n.id: n.coords for n in project.nodes}
    if len(element.nodes) == 2 and all(n in coords for n in element.nodes):
        span = math.dist(coords[element.nodes[0]], coords[element.nodes[1]])
        lines.append(f"Joints {nodes}, L = {_fmt(span)} {length}")
    else:
        lines.append(f"Joints {nodes}")
    section_id = getattr(element, "section_id", None)
    if section_id is not None:
        section = next((s for s in project.sections if s.id == section_id), None)
        name = (section.name or section.type) if section is not None else "missing"
        lines.append(f"Section {section_id}: {name}")
    material_id = getattr(element, "material_id", None)
    if material_id is not None:
        material = next((m for m in project.materials if m.id == material_id), None)
        name = (material.name or material.type) if material is not None else "missing"
        lines.append(f"Material {material_id}: {name}")
    loads = []
    per_length = f"{force}/{length}" if force and length else ""
    for pattern in project.load_patterns:
        if not isinstance(pattern, PlainLoadPattern):
            continue
        label = pattern.name or str(pattern.id)
        for load in pattern.element_loads:
            if load.element_id == element_id:
                parts = [
                    f"{n} {_fmt(v)}"
                    for n, v in (("wx", load.wx), ("wy", load.wy), ("wz", load.wz))
                    if v
                ]
                loads.append(f"{label}: uniform {', '.join(parts) or '0'} {per_length} (local)")
        for kind, items in (
            ("point load", pattern.point_loads),
            ("trapezoidal load", pattern.distributed_loads),
            ("temperature load", pattern.temperature_loads),
            ("surface load", pattern.surface_loads),
        ):
            count = sum(1 for x in items if x.element_id == element_id)
            if count:
                loads.append(f"{label}: {count} {kind}(s)")
    return "\n".join(lines + _load_lines(loads))
