"""Global ↔ local conversion for loads on frame elements.

OpenSees takes ``-beamUniform`` / ``-beamPoint`` components in the element's
own axes. Engineers usually think in global X/Y/Z, so the dialogs default to
global values and the commands convert them with the same axes the analysis
uses (``core.geometry.local_axes``). The local checkbox on the dialog keeps the
old, direct route available.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from opensees_studio.core.geometry.local_axes import frame_local_axes

if TYPE_CHECKING:
    from opensees_studio.core.project import Project


def element_axes(
    project: Project, element_id: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Unit local ``(x, y, z)`` of a two-node frame element, or None."""
    element = next((item for item in project.elements if item.id == element_id), None)
    if element is None or len(element.nodes) != 2:
        return None
    nodes = {node.id: node for node in project.nodes}
    node_i = nodes.get(element.nodes[0])
    node_j = nodes.get(element.nodes[1])
    if node_i is None or node_j is None:
        return None
    angle = float(getattr(element, "local_axis_angle", 0.0) or 0.0)
    return frame_local_axes(project.ndm, node_i.coords, node_j.coords, angle)


def global_to_local(
    project: Project, element_id: int, vector: Sequence[float]
) -> tuple[float, float, float]:
    """Project a global load vector onto one member's local axes.

    Returns ``(wx, wy, wz)``, the order OpenSees uses for the load components.
    A 2D model has no out-of-plane member load, so a global Y component is
    refused there rather than silently dropped.
    """
    axes = element_axes(project, element_id)
    if axes is None:
        raise ValueError(f"Element {element_id} is not a two-node frame element.")
    value = np.asarray(vector, dtype=float)
    wx, wy, wz = (float(np.dot(value, axis)) for axis in axes)
    if project.ndm == 2 and abs(wz) > 1e-9:
        raise ValueError(
            f"Element {element_id} is in a 2D model (X-Z plane); a global Y load "
            "is out of plane and cannot be applied."
        )
    return wx, wy, wz
