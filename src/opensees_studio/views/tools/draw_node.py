"""DrawNodeTool — click on the canvas to create a node.

Each empty-space click is unprojected onto the Z=0 plane by the canvas
and forwarded here. If the project has a :class:`GridSystem`, the
world point is snapped to the nearest grid intersection before the
node is created; otherwise the raw point is used.

Picking an existing node deactivates the tool and reports its id (so
the user doesn't accidentally create an overlapping duplicate).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands import AddNodesCommand
from opensees_studio.core import Node
from opensees_studio.core.geometry import CoordinateGridSystem
from opensees_studio.views.tools.base import CanvasTool

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

    from opensees_studio.viewmodels import ProjectViewModel
    from opensees_studio.views.canvas3d import ModelCanvas


def _snap_to_grid(
    x: float, y: float, z: float,
    x_lines: list[float], y_lines: list[float], z_lines: list[float],
) -> tuple[float, float, float]:
    """Snap each coordinate to its closest grid line (identity on empty axes)."""
    def nearest(v: float, lines: list[float]) -> float:
        if not lines:
            return v
        return min(lines, key=lambda c: abs(c - v))
    return nearest(x, x_lines), nearest(y, y_lines), nearest(z, z_lines)


def _snap_across_systems(
    world: tuple[float, float, float],
    systems: list[CoordinateGridSystem],
) -> tuple[float, float, float]:
    """Return the world point closest to ``world`` across all visible grids.

    For each visible :class:`CoordinateGridSystem` we transform the world
    click into that system's local frame, snap in local coordinates, then
    transform back. The candidate nearest to the original world click is
    returned. If no visible system has any grid lines, the point is
    returned unchanged (no snap).
    """
    best: tuple[float, float, float] | None = None
    best_d2 = float("inf")
    for cs in systems:
        grid = cs.grid
        if not grid.visible:
            continue
        if not (grid.x_lines or grid.y_lines or grid.z_lines):
            continue
        lx, ly, lz = cs.coord.world_to_local(world)
        sl = _snap_to_grid(lx, ly, lz,
                            grid.x_lines, grid.y_lines, grid.z_lines)
        candidate = cs.coord.local_to_world(sl)
        d2 = ((candidate[0] - world[0]) ** 2
              + (candidate[1] - world[1]) ** 2
              + (candidate[2] - world[2]) ** 2)
        if d2 < best_d2:
            best = candidate
            best_d2 = d2
    return best if best is not None else world


class DrawNodeTool(CanvasTool):
    """Left-click anywhere on the canvas to create a node."""

    name = "Draw Node"
    consumes_picks = True

    def __init__(
        self,
        canvas: "ModelCanvas",
        vm: "ProjectViewModel",
        parent: "QObject | None" = None,
    ) -> None:
        super().__init__(canvas, vm, parent)

    def activate(self) -> None:
        # Lock the camera to top (XY) view so clicks map 1:1 to world points
        # on the Z=0 plane — same affordance as SAP2000's default workspace.
        try:
            self._canvas.view_xy()
        except Exception:
            pass
        super().activate()

    def prompt(self) -> str:
        return ("Draw Node: top-down view locked. Click a grid intersection "
                "to place a node. Switch to Select tool to finish.")

    def on_node_picked(self, node_id: int) -> None:
        self.statusChanged.emit(
            f"Draw Node: node {node_id} already exists at that spot."
        )

    def on_empty_clicked(self, x: float, y: float, z: float) -> None:
        project = self._vm.project
        if project is None:
            return
        systems = getattr(project, "coord_systems", None) or []
        if systems:
            x, y, z = _snap_across_systems((x, y, z), systems)
        nid = project.next_node_id()
        node = Node(id=nid, coords=(x, y, z))
        self._vm.apply_command(
            AddNodesCommand(self._vm, [node], text=f"Add node {nid}")
        )
        self.statusChanged.emit(
            f"Draw Node: added node {nid} at ({x:g}, {y:g}, {z:g}). "
            "Click again for another."
        )
