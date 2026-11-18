"""Joint patterns: a number at each node, for loads that vary over a surface.

A joint pattern is what SAP2000 calls one (Define → Joint Patterns, Assign →
Joint Patterns): a named set of dimensionless values, one per node. On its own it
does nothing; a :class:`~opensees_studio.core.loads.SurfaceLoad` that names it
becomes a pressure that varies over the shell — at each corner the load's
``value`` (the *multiplier*) times the pattern's value there — interpolated
between the corners with the shell's own bilinear shape functions. That is how a
hydrostatic pressure on a wall or a tank is modelled: the pattern is the depth
below the water line, the multiplier the water's unit weight.

Values are assigned to selected nodes the two ways SAP2000 offers:

- :func:`plane_values` — ``A·x + B·y + C·z + D`` at each node;
- :func:`hydrostatic_values` — ``w·(Z₀ - z) + q``: zero at the free surface
  ``Z₀``, growing with depth at the unit weight ``w``, plus an optional uniform
  ``q``;

each filtered by :func:`restrict` (all values, negative ones set to zero, or
positive ones set to zero — "zero negative values" is what keeps a hydrostatic
pressure from pulling above the water line) and merged with what the pattern
already holds by :func:`assign` (add, replace or delete).

A node the pattern has no value for counts as zero.

This module is part of ``core``: no Qt, no OpenSees.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal, Protocol

import numpy as np
from pydantic import Field, PositiveInt

from opensees_studio.core._base import Entity

Restriction = Literal["all", "zero_negative", "zero_positive"]
Action = Literal["add", "replace", "delete"]

RESTRICTIONS: tuple[tuple[str, Restriction], ...] = (
    ("Use all values", "all"),
    ("Zero negative values", "zero_negative"),
    ("Zero positive values", "zero_positive"),
)
ACTIONS: tuple[tuple[str, Action], ...] = (
    ("Replace existing values", "replace"),
    ("Add to existing values", "add"),
    ("Delete existing values", "delete"),
)


class JointPattern(Entity):
    """A named, dimensionless value per node (SAP2000 *joint pattern*)."""

    values: dict[PositiveInt, float] = Field(
        default_factory=dict,
        description="Node id → value. A node without an entry has the value zero.",
    )

    def value(self, node_id: int) -> float:
        """The pattern's value at ``node_id`` (zero when unassigned)."""
        return float(self.values.get(node_id, 0.0))


class _ProjectLike(Protocol):
    """What the pattern helpers need of a Project, without importing it back."""

    nodes: Any
    joint_patterns: list[JointPattern]


def plane_values(
    coords: Mapping[int, Iterable[float]], a: float, b: float, c: float, d: float
) -> dict[int, float]:
    """``A·x + B·y + C·z + D`` at each node (A, B, C per length; D and the result unitless)."""
    out: dict[int, float] = {}
    for node_id, xyz in coords.items():
        x, y, z = (float(v) for v in xyz)
        out[node_id] = a * x + b * y + c * z + d
    return out


def hydrostatic_values(
    coords: Mapping[int, Iterable[float]],
    z_zero: float,
    unit_weight: float,
    added: float = 0.0,
) -> dict[int, float]:
    """``w·(Z₀ - z) + q`` at each node: depth below ``z_zero`` times ``w``, plus ``q``.

    With ``w`` the fluid's unit weight (force / length³) and ``q`` a pressure
    (force / area), the values *are* a pressure, and a surface load with a
    multiplier of 1 applies it as it is. Positive below the free surface.
    """
    out: dict[int, float] = {}
    for node_id, xyz in coords.items():
        z = float(list(xyz)[2])
        out[node_id] = unit_weight * (z_zero - z) + added
    return out


def restrict(values: Mapping[int, float], restriction: Restriction) -> dict[int, float]:
    """Keep every value, or set the negative (or the positive) ones to zero."""
    if restriction == "zero_negative":
        return {k: max(v, 0.0) for k, v in values.items()}
    if restriction == "zero_positive":
        return {k: min(v, 0.0) for k, v in values.items()}
    return dict(values)


def assign(pattern: JointPattern, values: Mapping[int, float], action: Action) -> JointPattern:
    """A copy of ``pattern`` with ``values`` added to, replacing, or deleted from its own.

    ``delete`` removes the listed nodes' values whatever ``values`` holds for them.
    A value of exactly zero is not stored: it is what an unassigned node means.
    """
    merged = dict(pattern.values)
    for node_id, value in values.items():
        if action == "delete":
            merged.pop(node_id, None)
            continue
        total = merged.get(node_id, 0.0) + value if action == "add" else value
        if total == 0.0:
            merged.pop(node_id, None)
        else:
            merged[node_id] = float(total)
    return pattern.model_copy(update={"values": dict(sorted(merged.items()))})


def interpolate_on_quad(
    points: np.ndarray, corner_values: Iterable[float], point: np.ndarray
) -> float:
    """Value at ``point`` of the bilinear interpolation of four corner values.

    ``points`` are the quad's corners (4 x 3) in their node order; ``point`` is
    taken to lie on it (or near it: it is projected). The natural coordinates
    are found by Newton's method on the bilinear map, which is exact for a
    parallelogram and converges in a few steps for any convex quad.
    """
    values = np.asarray(list(corner_values), dtype=float)
    corners = ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))
    xi = eta = 0.0
    for _ in range(25):
        n = np.array([0.25 * (1 + a * xi) * (1 + b * eta) for a, b in corners])
        dn_dxi = np.array([0.25 * a * (1 + b * eta) for a, b in corners])
        dn_deta = np.array([0.25 * b * (1 + a * xi) for a, b in corners])
        residual = point - n @ points
        jac = np.column_stack((dn_dxi @ points, dn_deta @ points))  # 3 x 2
        step, *_ = np.linalg.lstsq(jac, residual, rcond=None)
        xi, eta = xi + float(step[0]), eta + float(step[1])
        if float(np.linalg.norm(step)) < 1e-12:
            break
    xi, eta = min(max(xi, -1.0), 1.0), min(max(eta, -1.0), 1.0)
    n = np.array([0.25 * (1 + a * xi) * (1 + b * eta) for a, b in corners])
    return float(n @ values)


# ──────────────────────────── keeping patterns in step with the nodes ────────────────────────────
def prune_joint_patterns(project: _ProjectLike) -> bool:
    """Drop the values of nodes the model no longer has; ``True`` when one went.

    A stale value would otherwise be inherited by the next node given the same id.
    """
    present = {node.id for node in project.nodes}
    changed = False
    for k, pattern in enumerate(project.joint_patterns):
        kept = {n: v for n, v in pattern.values.items() if n in present}
        if len(kept) != len(pattern.values):
            project.joint_patterns[k] = pattern.model_copy(update={"values": kept})
            changed = True
    return changed


def follow_merged_nodes(project: _ProjectLike, mapping: Mapping[int, int]) -> None:
    """After a merge (removed id → keeper id): a keeper without a value takes its duplicate's."""
    for k, pattern in enumerate(project.joint_patterns):
        values = dict(pattern.values)
        for removed, keeper in mapping.items():
            if removed in values:
                moved = values.pop(removed)
                values.setdefault(keeper, moved)
        project.joint_patterns[k] = pattern.model_copy(update={"values": values})


def copy_to_new_nodes(project: _ProjectLike, mapping: Mapping[int, int]) -> None:
    """Give each copied node (source id → copy id) its source's value in every pattern."""
    for k, pattern in enumerate(project.joint_patterns):
        added = {new: pattern.values[old] for old, new in mapping.items() if old in pattern.values}
        if added:
            project.joint_patterns[k] = pattern.model_copy(
                update={"values": {**pattern.values, **added}}
            )


def interpolate_new_nodes(
    project: _ProjectLike,
    parents: Mapping[int, tuple[np.ndarray, tuple[int, int, int, int]]],
    new_nodes: Mapping[int, np.ndarray],
) -> int:
    """Give the nodes a mesh created inside a shell the pattern values interpolated there.

    ``parents`` maps each new node to the corners (4 x 3) and node ids of the
    shell it was created on; ``new_nodes`` gives the new nodes' positions. Only
    patterns that have a value at one of the parent's corners are touched.
    Returns how many values were added.
    """
    added = 0
    for k, pattern in enumerate(project.joint_patterns):
        values = dict(pattern.values)
        for node_id, (corners, corner_ids) in parents.items():
            if node_id in values or not any(c in values for c in corner_ids):
                continue
            corner_values = [values.get(c, 0.0) for c in corner_ids]
            value = interpolate_on_quad(corners, corner_values, new_nodes[node_id])
            if value != 0.0:
                values[node_id] = value
                added += 1
        project.joint_patterns[k] = pattern.model_copy(update={"values": values})
    return added
