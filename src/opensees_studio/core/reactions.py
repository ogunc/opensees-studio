"""Support reactions, read out of a results object.

The runner stores ``node_reaction`` as ``{node id: array}``. The array is the
node's reaction in the project's DOF order, either one vector for the whole case
or one row per step. This module turns that into the rows the table shows and
the vectors the viewport draws, and it is pure so both are tested without Qt.

2D models keep their DOFs in the global X-Z plane: storage is ``(Ux, Uz, Ry)``,
so a three-wide array maps to ``Fx``, ``Fz`` and ``Mz`` of a 3D-shaped result.
A six-wide array is already ``(Fx, Fy, Fz, Mx, My, Mz)``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from opensees_studio.core.project import Project


@dataclass(frozen=True)
class ReactionRow:
    """One restrained node: what the support takes, in global components."""

    node_id: int
    forces: tuple[float, float, float]
    moments: tuple[float, float, float]

    @property
    def magnitude(self) -> float:
        """Length of the force vector, in project force units."""
        return float(np.linalg.norm(self.forces))

    @property
    def moment_magnitude(self) -> float:
        """Length of the moment vector, in project moment units."""
        return float(np.linalg.norm(self.moments))


def _split(values: object) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """``(forces, moments)`` from a reaction array, or None if it is unusable."""
    array = np.asarray(values, dtype=float)
    if array.ndim > 1:
        # One row per step: the table and the drawing show the final state.
        array = array[-1]
    flat = array.ravel()
    if flat.size >= 6:
        return (
            (float(flat[0]), float(flat[1]), float(flat[2])),
            (float(flat[3]), float(flat[4]), float(flat[5])),
        )
    if flat.size == 3:
        # 2D: (Ux, Uz, Ry) in the global X-Z plane.
        return (
            (float(flat[0]), 0.0, float(flat[1])),
            (0.0, 0.0, float(flat[2])),
        )
    return None


def reaction_rows(project: Project, reactions: object) -> list[ReactionRow]:
    """Every node that carries a reaction, in project order.

    ``reactions`` is the results object's ``node_reaction`` mapping; a node with
    no entry (free joints report none) is skipped rather than shown as a row of
    zeros. The final step is the one read when the array carries a time axis.
    """
    if not isinstance(reactions, dict):
        return []
    rows: list[ReactionRow] = []
    for node in project.nodes:
        values = reactions.get(node.id)
        if values is None:
            continue
        split = _split(values)
        if split is None:
            continue
        rows.append(ReactionRow(node_id=node.id, forces=split[0], moments=split[1]))
    return rows


def largest_force(rows: list[ReactionRow]) -> float:
    """Biggest force magnitude, the number an arrow scale is built from."""
    return max((row.magnitude for row in rows), default=0.0)


def largest_moment(rows: list[ReactionRow]) -> float:
    """Biggest moment magnitude, the number an arc scale is built from."""
    return max((row.moment_magnitude for row in rows), default=0.0)
