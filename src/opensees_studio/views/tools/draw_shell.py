"""DrawShellTool — click the corners of a shell.

Each click (an existing node or a grid intersection, as for Draw Frame)
adds a corner. The fourth corner closes a ``ShellMITC4``; after three, a
click on the first corner closes a triangular ``ShellDKGT``. The corners
of a quadrilateral are put in a consistent winding with
:func:`core.geometry.ordering.order_quad_nodes`, so the order of the clicks
does not twist the shell. Esc drops the corners clicked so far.

The shells take :attr:`DrawShellTool.section_id` (the Section box of the
Tools toolbar), or the first plate section when none is chosen; the main
window does not arm the tool in a project without a plate section.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands import AddElementsCommand, AddNodesCommand
from opensees_studio.core import Node, ShellDKGTElement, ShellMITC4Element
from opensees_studio.core.geometry.ordering import QuadOrderError, order_quad_nodes
from opensees_studio.core.sections import SHELL_SECTION_CLASSES
from opensees_studio.views.tools.base import CanvasTool

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

    from opensees_studio.viewmodels import ProjectViewModel
    from opensees_studio.views.canvas3d import ModelCanvas


_COINCIDENT_TOL = 1e-6


def shell_sections(project: object) -> list[tuple[int, str]]:
    """``(id, name)`` of the plate sections a drawn shell can take."""
    return [
        (s.id, s.name or f"Section {s.id}")
        for s in getattr(project, "sections", [])
        if isinstance(s, SHELL_SECTION_CLASSES)
    ]


class DrawShellTool(CanvasTool):
    """Pick three or four corners to draw a shell."""

    name = "Draw Shell"
    consumes_picks = True
    #: A click on a joint reuses it, so the hover marks the joint too.
    wants_node_snap = True
    draws_preview = True
    preview_closed = True

    def __init__(
        self,
        canvas: ModelCanvas,
        vm: ProjectViewModel,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(canvas, vm, parent)
        self._corners: list[int] = []
        #: The plate section of the next shells; None = the first one.
        self.section_id: int | None = None

    # ── lifecycle ───────────────────────────────────────────────────
    def activate(self) -> None:
        self._canvas.set_snap_preview_enabled(True)
        super().activate()

    def deactivate(self) -> None:
        self._canvas.set_snap_reference(None)
        self._canvas.set_snap_preview_enabled(False)
        super().deactivate()

    def reset(self) -> None:
        self._corners = []
        self._canvas.set_snap_reference(None)
        self._canvas.selection.clear()
        self._refresh_draw_preview()

    def preview_points(self) -> list[tuple[float, float, float]]:
        """The corners placed so far; the preview closes through the pointer."""
        points = [self._node_point(node_id) for node_id in self._corners]
        return [point for point in points if point is not None]

    def prompt(self) -> str:
        count = len(self._corners)
        if count == 0:
            return "Draw Shell: click the FIRST corner (node or grid intersection)." + (
                self.grid_hint()
            )
        if count == 3:
            return (
                "Draw Shell: click the FOURTH corner, or the first one again for a "
                "triangle (Esc to cancel)."
            )
        return f"Draw Shell: corner {count} of 4 placed. Click the next one (Esc to cancel)."

    # ── picks ───────────────────────────────────────────────────────
    def on_node_picked(self, node_id: int) -> None:
        self._add_corner(node_id)

    def on_empty_clicked(self, x: float, y: float, z: float, snapped: bool = True) -> None:
        project = self._vm.project
        if project is None:
            return
        if project.ndm == 2:
            y = 0.0  # a 2D model lives in the X-Z plane (core.plane)
        self._add_corner(self._find_or_create_node_at(x, y, z))

    # ── core ────────────────────────────────────────────────────────
    def _add_corner(self, node_id: int) -> None:
        if self._corners and node_id == self._corners[-1]:
            return  # the same corner twice
        if len(self._corners) == 3 and node_id == self._corners[0]:
            self._finish(self._corners)
            return
        if node_id in self._corners:
            self.statusChanged.emit(
                f"Draw Shell: node {node_id} is already a corner of this shell. "
                "Click another point (Esc to cancel)."
            )
            return
        self._corners.append(node_id)
        if len(self._corners) == 4:
            self._finish(self._corners)
            return
        self._set_snap_reference_to_node(node_id)
        self._canvas.selection.set_selection(set(self._corners), set())
        self._refresh_draw_preview()
        self.statusChanged.emit(self.prompt())

    def _finish(self, corners: list[int]) -> None:
        corners = list(corners)
        try:
            message = self._create_shell(corners)
        finally:
            self.reset()
        self.statusChanged.emit(message + " " + self.prompt())

    def _section_id(self) -> int | None:
        project = self._vm.project
        sections = shell_sections(project)
        ids = [sid for sid, _ in sections]
        if self.section_id in ids:
            return self.section_id
        return ids[0] if ids else None

    def _create_shell(self, corners: list[int]) -> str:
        project = self._vm.project
        section_id = self._section_id()
        if project is None or section_id is None:
            return "Draw Shell: the project has no plate section."
        element_id = project.next_element_id()
        if len(corners) == 3:
            tri = (corners[0], corners[1], corners[2])
            element: ShellDKGTElement | ShellMITC4Element = ShellDKGTElement(
                id=element_id, nodes=tri, section_id=section_id
            )
        else:
            coords = {n.id: n.coords for n in project.nodes}
            points = [tuple(float(c) for c in coords[nid]) for nid in corners]
            try:
                order = order_quad_nodes(points)  # type: ignore[arg-type]
            except QuadOrderError as exc:
                return f"Draw Shell: {exc}"
            ordered = [corners[i] for i in order]
            element = ShellMITC4Element(
                id=element_id,
                nodes=(ordered[0], ordered[1], ordered[2], ordered[3]),
                section_id=section_id,
            )
        self._vm.apply_command(
            AddElementsCommand(self._vm, [element], text=f"Draw shell {element_id}")
        )
        return f"Draw Shell: added shell {element_id}."

    def _find_or_create_node_at(self, x: float, y: float, z: float) -> int:
        project = self._vm.project
        assert project is not None
        for n in project.nodes:
            if (
                abs(n.coords[0] - x) <= _COINCIDENT_TOL
                and abs(n.coords[1] - y) <= _COINCIDENT_TOL
                and abs(n.coords[2] - z) <= _COINCIDENT_TOL
            ):
                return n.id
        nid = project.next_node_id()
        self._vm.apply_command(AddNodesCommand(self._vm, [Node(id=nid, coords=(x, y, z))]))
        return nid
