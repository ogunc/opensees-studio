"""Edit → Delete Loads: remove loads by type, pattern and selection.

Pure (no Qt): :func:`count_loads` says how many of each type a choice would
remove, :func:`remove_loads` removes them from the project's plain patterns, and
the command undoes it by putting the patterns back.

A load belongs to a selection through what it acts on: a joint load through its
joint, a frame or shell load through its element, a floor load when all four of
its corner joints are selected. The self weight is a pattern's multiplier, not a
load on anything, so it is only removed (set to 0) on the entire model.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from opensees_studio.core.loads import PlainLoadPattern
from opensees_studio.core.project import Project

Target = Literal["node", "element", "panel", "pattern"]


@dataclass(frozen=True)
class LoadKind:
    key: str
    label: str
    field: str  # the PlainLoadPattern attribute
    target: Target


#: Every load type a plain pattern carries, in the order the dialog lists them.
LOAD_KINDS: tuple[LoadKind, ...] = (
    LoadKind("nodal", "Joint forces and moments", "nodal_loads", "node"),
    LoadKind("imposed", "Imposed joint displacements", "imposed_displacements", "node"),
    LoadKind("uniform", "Uniform frame loads", "element_loads", "element"),
    LoadKind("trapezoidal", "Trapezoidal frame loads", "distributed_loads", "element"),
    LoadKind("point", "Frame point loads", "point_loads", "element"),
    LoadKind("temperature", "Frame temperature loads", "temperature_loads", "element"),
    LoadKind("surface", "Shell pressures", "surface_loads", "element"),
    LoadKind("floor", "Floor loads", "floor_loads", "panel"),
    LoadKind("self_weight", "Self weight (multiplier set to 0)", "self_weight", "pattern"),
)
KINDS_BY_KEY = {kind.key: kind for kind in LOAD_KINDS}


@dataclass(frozen=True)
class Scope:
    """What to remove from: patterns (None = all), and a selection (None = the whole model)."""

    pattern_ids: frozenset[int] | None = None
    node_ids: frozenset[int] | None = None
    element_ids: frozenset[int] | None = None

    @property
    def whole_model(self) -> bool:
        return self.node_ids is None and self.element_ids is None


def _patterns(project: Project, scope: Scope) -> list[PlainLoadPattern]:
    return [
        p
        for p in project.load_patterns
        if isinstance(p, PlainLoadPattern)
        and (scope.pattern_ids is None or p.id in scope.pattern_ids)
    ]


def _hit(kind: LoadKind, load: Any, scope: Scope) -> bool:
    """Whether ``load`` (of ``kind``) falls inside the selection of ``scope``."""
    if scope.whole_model:
        return True
    nodes = scope.node_ids or frozenset()
    elements = scope.element_ids or frozenset()
    if kind.target == "node":
        return load.node_id in nodes
    if kind.target == "element":
        return load.element_id in elements
    if kind.target == "panel":
        return all(n in nodes for n in load.nodes)
    return False  # the self weight belongs to no joint or element


def count_loads(project: Project, kinds: Iterable[str], scope: Scope) -> dict[str, int]:
    """How many loads of each kind :func:`remove_loads` would remove."""
    counts: dict[str, int] = {}
    for key in kinds:
        kind = KINDS_BY_KEY[key]
        total = 0
        for pattern in _patterns(project, scope):
            if kind.target == "pattern":
                total += int(scope.whole_model and pattern.self_weight != 0.0)
            else:
                total += sum(1 for load in getattr(pattern, kind.field) if _hit(kind, load, scope))
        counts[key] = total
    return counts


def remove_loads(project: Project, kinds: Iterable[str], scope: Scope) -> dict[str, int]:
    """Remove the chosen loads in place; return how many of each kind went."""
    removed = count_loads(project, list(kinds), scope)
    for key, n in removed.items():
        if not n:
            continue
        kind = KINDS_BY_KEY[key]
        for pattern in _patterns(project, scope):
            if kind.target == "pattern":
                pattern.self_weight = 0.0
            else:
                loads = getattr(pattern, kind.field)
                loads[:] = [load for load in loads if not _hit(kind, load, scope)]
    return removed
