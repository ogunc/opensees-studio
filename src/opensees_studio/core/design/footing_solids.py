"""Footings and pedestals as boxes to draw (project units), under the supports.

The 3D view draws every saved footing (isolated and combined) and its pedestals
from these boxes: a pedestal runs from the support down to the top of the
footing, the footing ``thickness`` below that. Pure geometry: no Qt, no VTK.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FootingSolid:
    """A box to draw (project units): a footing or a pedestal."""

    kind: str
    """``footing`` or ``pedestal``."""
    x: tuple[float, float]
    y: tuple[float, float]
    z: tuple[float, float]
    label: str = ""


def footing_solids(project: Any, settings: Any) -> list[FootingSolid]:
    """The saved footings and their pedestals as boxes under the supports."""
    if settings is None:
        return []
    nodes = {n.id: n.coords for n in project.nodes}
    out: list[FootingSolid] = []
    skip = {n for c in settings.combined_footings for n in c.node_ids}
    for d in settings.footings:
        if d.node_id not in nodes or d.node_id in skip:
            continue
        x, y, z = (float(v) for v in nodes[d.node_id][:3])
        top = z - d.pedestal_height
        cx, cy = x - d.offset_x, y - d.offset_y
        out.append(
            FootingSolid(
                "footing",
                (cx - d.length_x / 2.0, cx + d.length_x / 2.0),
                (cy - d.width_y / 2.0, cy + d.width_y / 2.0),
                (top - d.thickness, top),
                f"Node {d.node_id}",
            )
        )
        if d.pedestal_height > 0.0:
            out.append(
                FootingSolid(
                    "pedestal",
                    (x - d.column_x / 2.0, x + d.column_x / 2.0),
                    (y - d.column_y / 2.0, y + d.column_y / 2.0),
                    (top, z),
                )
            )
    for c in settings.combined_footings:
        cols = [col for col in c.columns if col.node_id in nodes]
        if not cols:
            continue
        top = min(float(nodes[col.node_id][2]) - col.pedestal_height for col in cols)
        out.append(
            FootingSolid(
                "footing",
                (c.center_x - c.length_x / 2.0, c.center_x + c.length_x / 2.0),
                (c.center_y - c.width_y / 2.0, c.center_y + c.width_y / 2.0),
                (top - c.thickness, top),
                c.name,
            )
        )
        for col in cols:
            x, y, z = (float(v) for v in nodes[col.node_id][:3])
            if z > top:
                out.append(
                    FootingSolid(
                        "pedestal",
                        (x - col.column_x / 2.0, x + col.column_x / 2.0),
                        (y - col.column_y / 2.0, y + col.column_y / 2.0),
                        (top, z),
                    )
                )
    return out
