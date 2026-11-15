"""Join frame members that continue each other into one member.

Two frames join at a joint when nothing else is there to keep: they are the
only elements at the joint, they run in a straight line through it, they are
the same element with the same properties (type, section, transformation,
modifiers, local-axis angle), neither has end releases, offsets or an
insertion point that the joint would lose, and the joint carries no
restraint, mass, nodal load or constraint. Their uniform loads must match
pattern by pattern (the joined member takes one copy); any other element
load keeps the joint.

The joined member keeps the id of the first piece and runs from that
piece's far end to the other's; the joint between them is removed. A chain
of collinear pieces is joined into one member.

No Qt.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from opensees_studio.core.geometry.elements import FRAME_ELEMENT_CLASSES
from opensees_studio.core.loads import PlainLoadPattern

#: Sine of the largest angle between two pieces still called a straight line.
COLLINEAR_SINE = 1e-6

#: Fields that differ between the pieces of one member without mattering.
_IDENTITY = {"id", "nodes", "name"}

#: Options that belong to one end of a member: a joint carrying one cannot go.
_END_OPTIONS = ("releases", "end_offsets", "insertion")


@dataclass
class JoinReport:
    """What :func:`join_frames` did."""

    joined: int = 0
    """Joints removed (each one joined two pieces)."""
    removed_elements: list[int] = field(default_factory=list)
    removed_nodes: list[int] = field(default_factory=list)
    kept: dict[int, str] = field(default_factory=dict)
    """Joints between selected members that were kept, with the reason."""

    def summary(self) -> str:
        if not self.joined:
            return "Nothing joined." + (f" {len(self.kept)} joint(s) kept." if self.kept else "")
        text = f"Removed {self.joined} joint(s) between the selected members."
        if self.kept:
            text += f" {len(self.kept)} joint(s) kept."
        return text


def _uniform_loads(project: Any, element_id: int) -> dict[int, Counter[tuple[float, ...]]]:
    out: dict[int, Counter[tuple[float, ...]]] = {}
    for pattern in project.load_patterns:
        if isinstance(pattern, PlainLoadPattern):
            loads = [
                (x.wx, x.wy, x.wz) for x in pattern.element_loads if x.element_id == element_id
            ]
            if loads:
                out[pattern.id] = Counter(loads)
    return out


def _other_loads(project: Any, element_id: int) -> bool:
    for pattern in project.load_patterns:
        if not isinstance(pattern, PlainLoadPattern):
            continue
        for name in ("point_loads", "distributed_loads", "temperature_loads"):
            if any(x.element_id == element_id for x in getattr(pattern, name)):
                return True
    return False


def _joint_is_free(project: Any, node: Any) -> str:
    """Why the joint must stay, or ""."""
    if any(node.restraint):
        return "it is restrained"
    if any(abs(m) > 0.0 for m in node.mass):
        return "it has a mass"
    for pattern in project.load_patterns:
        if isinstance(pattern, PlainLoadPattern) and any(
            x.node_id == node.id for x in pattern.nodal_loads
        ):
            return "it has a nodal load"
    for name in ("mp_constraints", "rigid_links", "diaphragms"):
        for constraint in getattr(project, name, []):
            for key, value in constraint.model_dump().items():
                if "node" not in key:
                    continue
                ids = value if isinstance(value, list | tuple) else [value]
                if node.id in ids:
                    return "it is in a constraint"
    return ""


def _why_not(project: Any, node: Any, a: Any, b: Any, coords: dict[int, np.ndarray]) -> str:
    """Why ``a`` and ``b`` cannot be joined at ``node``, or ""."""
    if type(a) is not type(b):
        return "the members are different element types"
    left = a.model_dump(exclude=_IDENTITY)
    right = b.model_dump(exclude=_IDENTITY)
    for piece in (a, b):
        defaults = type(piece).model_fields
        for option in _END_OPTIONS:
            if getattr(piece, option) != defaults[option].get_default(call_default_factory=True):
                return f"a member has an end option ({option.replace('_', ' ')})"
    if left != right:
        return "the members have different properties"
    reason = _joint_is_free(project, node)
    if reason:
        return reason
    far_a = a.nodes[0] if a.nodes[1] == node.id else a.nodes[1]
    far_b = b.nodes[0] if b.nodes[1] == node.id else b.nodes[1]
    u = coords[node.id] - coords[far_a]
    v = coords[far_b] - coords[node.id]
    nu, nv = np.linalg.norm(u), np.linalg.norm(v)
    if nu == 0.0 or nv == 0.0:
        return "a member has zero length"
    if np.dot(u, v) <= 0.0 or np.linalg.norm(np.cross(u / nu, v / nv)) > COLLINEAR_SINE:
        return "the members are not in a straight line"
    if _other_loads(project, a.id) or _other_loads(project, b.id):
        return "a member has a point, trapezoidal or temperature load"
    if _uniform_loads(project, a.id) != _uniform_loads(project, b.id):
        return "the members have different uniform loads"
    return ""


def join_frames(project: Any, element_ids: set[int]) -> JoinReport:
    """Join the selected frames that continue each other, in place."""
    report = JoinReport()
    selected = set(element_ids)
    while True:
        coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
        at_node: dict[int, list[Any]] = {}
        for element in project.elements:
            for node_id in element.nodes:
                at_node.setdefault(int(node_id), []).append(element)
        candidate = None
        for node in sorted(project.nodes, key=lambda n: n.id):
            members = at_node.get(node.id, [])
            if len(members) != 2 or not all(m.id in selected for m in members):
                continue
            if not all(isinstance(m, FRAME_ELEMENT_CLASSES) and len(m.nodes) == 2 for m in members):
                continue
            a, b = sorted(members, key=lambda m: m.id)
            reason = _why_not(project, node, a, b, coords)
            if reason:
                report.kept[node.id] = reason
                continue
            candidate = (node, a, b)
            break
        if candidate is None:
            break
        node, a, b = candidate
        far_a = a.nodes[0] if a.nodes[1] == node.id else a.nodes[1]
        far_b = b.nodes[0] if b.nodes[1] == node.id else b.nodes[1]
        # Keep a's direction: it ran towards the joint, so it now runs to b's far end.
        nodes = (far_a, far_b) if a.nodes[1] == node.id else (far_b, far_a)
        joined = a.model_copy(update={"nodes": nodes})
        project.elements[:] = [
            joined if e.id == a.id else e for e in project.elements if e.id != b.id
        ]
        project.nodes[:] = [n for n in project.nodes if n.id != node.id]
        for pattern in project.load_patterns:
            if isinstance(pattern, PlainLoadPattern):
                pattern.element_loads[:] = [
                    x for x in pattern.element_loads if x.element_id != b.id
                ]
        for group in getattr(project, "groups", []):
            if hasattr(group, "element_ids") and b.id in group.element_ids:
                group.element_ids = [i for i in group.element_ids if i != b.id]
            if hasattr(group, "node_ids") and node.id in group.node_ids:
                group.node_ids = [i for i in group.node_ids if i != node.id]
        selected.discard(b.id)
        report.joined += 1
        report.removed_elements.append(b.id)
        report.removed_nodes.append(node.id)
        report.kept.pop(node.id, None)
    return report
