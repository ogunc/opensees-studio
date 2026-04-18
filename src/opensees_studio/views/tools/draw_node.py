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

    Returns the original point if no visible system has any grid lines.
    For off-grid rejection logic, prefer :func:`_snap_with_distance`.
    """
    snapped, _ = _snap_with_distance(world, systems)
    return snapped if snapped is not None else world


def _snap_with_distance(
    world: tuple[float, float, float],
    systems: list[CoordinateGridSystem],
) -> tuple[tuple[float, float, float] | None, float]:
    """Return (snapped_world_point, distance_in_world_units).

    ``None`` in the first slot means **no visible grid with any lines** —
    caller should reject the click. Otherwise the distance lets callers
    decide whether the click was close enough to commit.
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
    return best, (best_d2 ** 0.5) if best is not None else float("inf")


def _min_grid_spacing(systems: list[CoordinateGridSystem]) -> float | None:
    """Return the smallest gap between adjacent grid lines across all
    visible systems, or ``None`` if no visible grid is defined. Used as
    the yardstick for the snap-rejection tolerance (half the smallest
    spacing — so clicks in a grid cell's dead-centre get no action)."""
    smallest: float | None = None
    for cs in systems:
        grid = cs.grid
        if not grid.visible:
            continue
        for lines in (grid.x_lines, grid.y_lines, grid.z_lines):
            for i in range(1, len(lines)):
                d = abs(lines[i] - lines[i - 1])
                if d > 0 and (smallest is None or d < smallest):
                    smallest = d
    return smallest


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
        if not systems:
            self.statusChanged.emit(
                "Draw Node: no grid defined — open Define → Coordinate Systems/Grids first."
            )
            return

        snapped, distance = _snap_with_distance((x, y, z), systems)
        if snapped is None:
            self.statusChanged.emit(
                "Draw Node: no visible grid lines — nothing to snap to."
            )
            return

        # Off-grid rejection: require the click to land within half the
        # smallest grid spacing of the nearest intersection. This is the
        # SAP2000 behaviour — clicks in a grid cell's dead centre create
        # nothing, only clicks "near" an intersection commit.
        spacing = _min_grid_spacing(systems)
        if spacing is not None and distance > 0.5 * spacing:
            self.statusChanged.emit(
                f"Draw Node: click too far from any grid intersection "
                f"(distance {distance:.3g} > tolerance {0.5 * spacing:.3g})."
            )
            return

        x, y, z = snapped
        # Avoid creating a duplicate node at an existing grid intersection.
        for n in project.nodes:
            if (abs(n.coords[0] - x) <= 1e-6
                    and abs(n.coords[1] - y) <= 1e-6
                    and abs(n.coords[2] - z) <= 1e-6):
                self.statusChanged.emit(
                    f"Draw Node: node {n.id} already exists at that intersection."
                )
                return

        nid = project.next_node_id()
        node = Node(id=nid, coords=(x, y, z))
        self._vm.apply_command(
            AddNodesCommand(self._vm, [node], text=f"Add node {nid}")
        )
        self.statusChanged.emit(
            f"Draw Node: added node {nid} at ({x:g}, {y:g}, {z:g}). "
            "Click again for another."
        )
