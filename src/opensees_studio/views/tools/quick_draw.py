"""Quick Draw Frame: one click on a grid line draws the member between two crossings.

The SAP2000 way to lay out a regular frame: instead of clicking both ends,
click a grid line anywhere between two crossings and the member between them
is drawn, with the section of the Tools toolbar's Section box (as for Draw
Frame). The click is read where it meets the working plane, before any snap,
so it lands on the line it was meant for.
"""

from __future__ import annotations

from itertools import pairwise

from opensees_studio.core.geometry.grid_quick import PLANE_AXES, grid_ordinates, grid_segment
from opensees_studio.views.tools.draw_frame import DrawFrameTool

#: How close to a grid line a click counts as on it, as a fraction of the
#: smallest grid spacing in the plane.
LINE_TOLERANCE = 0.25


def _working_plane(canvas: object) -> tuple[str, float]:
    """The canvas' working plane and its offset; the plan at Z = 0 when none is set."""
    plane = getattr(canvas, "working_plane_type", lambda: None)()
    offset = getattr(canvas, "working_plane_offset", lambda: None)()
    return (plane or "XY", float(offset or 0.0))


def _tolerance(project: object, plane: str) -> float:
    ordinates = grid_ordinates(project)
    a, b, _ = PLANE_AXES[plane]
    gaps = [
        hi - lo for values in (ordinates[a], ordinates[b]) for lo, hi in pairwise(values) if hi > lo
    ]
    return LINE_TOLERANCE * min(gaps) if gaps else 0.0


class QuickDrawFrameTool(DrawFrameTool):
    """Click a grid line: the member between the two crossings around the click."""

    name = "Quick Draw Frame"

    def prompt(self) -> str:
        return (
            "Quick Draw Frame: click a grid line between two crossings to draw the "
            "member there." + self.grid_hint()
        )

    def on_plane_point(self, point: tuple[float, float, float]) -> bool:
        project = self._vm.project
        if project is None:
            return False
        plane, offset = _working_plane(self._canvas)
        segment = grid_segment(project, plane, offset, point, tolerance=_tolerance(project, plane))
        if segment is None:
            self.statusChanged.emit(
                "Quick Draw Frame: that is not on a grid line between two crossings. "
                + self.prompt()
            )
            return True
        start, end = segment
        n1 = self._find_or_create_node_at(*start)
        n2 = self._find_or_create_node_at(*end)
        if any(n1 in e.nodes and n2 in e.nodes for e in project.elements):
            self.statusChanged.emit(f"Quick Draw Frame: joints {n1} and {n2} are already joined.")
            return True
        self._create_frame(n1, n2)
        self.statusChanged.emit(f"Quick Draw Frame: drew the member {n1}-{n2}. " + self.prompt())
        return True

    def on_node_picked(self, node_id: int) -> None:
        self.statusChanged.emit(self.prompt())  # a joint is not a grid line

    def on_empty_clicked(self, x: float, y: float, z: float, snapped: bool = True) -> None:
        self.statusChanged.emit(self.prompt())
