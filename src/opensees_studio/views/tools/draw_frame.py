"""DrawFrameTool — SAP2000-style click-click to draw a frame.

Each click (on an existing node or on an empty grid intersection)
resolves to a **node id**:
- Click on an existing node → use it.
- Click on empty space → the point is snapped to the nearest grid
  intersection; if a node already sits within a small tolerance, reuse
  it, otherwise create a new node on the fly.

The first resolved click records the start; the second closes the
frame. Both steps are wrapped in a single QUndoStack macro so the
whole "Draw frame" action is one undoable step.

If no section exists yet, a default elastic section is created with
:class:`AddSectionsCommand` inside the same macro.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node
from opensees_studio.views.tools.base import CanvasTool

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

    from opensees_studio.viewmodels import ProjectViewModel
    from opensees_studio.views.canvas3d import ModelCanvas


# Defaults used only when no section has been defined yet.
_DEFAULT_SECTION = dict(
    name="Default Section",
    E=200e9,
    A=0.01,
    Iz=8.33e-6,
    Iy=8.33e-6,
    G=80e9,
    J=1e-6,
)

# Two world-points within this distance are considered the same node.
_COINCIDENT_TOL = 1e-6


class DrawFrameTool(CanvasTool):
    """Pick two points (nodes or grid intersections) to draw a frame."""

    name = "Draw Frame"
    consumes_picks = True

    def __init__(
        self,
        canvas: "ModelCanvas",
        vm: "ProjectViewModel",
        parent: "QObject | None" = None,
    ) -> None:
        super().__init__(canvas, vm, parent)
        self._first_node_id: int | None = None

    # ── lifecycle ───────────────────────────────────────────────────
    def activate(self) -> None:
        # SAP2000-style: lock the view to XY so clicks snap predictably.
        try:
            self._canvas.view_xy()
        except Exception:
            pass
        self._canvas.set_snap_preview_enabled(True)
        super().activate()

    def deactivate(self) -> None:
        self._canvas.set_snap_preview_enabled(False)
        super().deactivate()

    def reset(self) -> None:
        self._first_node_id = None
        self._canvas.selection.clear()

    def prompt(self) -> str:
        if self._first_node_id is None:
            return "Draw Frame: click the FIRST point (node or grid intersection)."
        return (
            f"Draw Frame: first node = {self._first_node_id}. "
            "Click the SECOND point (Esc to cancel)."
        )

    # ── picks ───────────────────────────────────────────────────────
    def on_node_picked(self, node_id: int) -> None:
        self._resolve_endpoint(node_id)

    def on_empty_clicked(self, x: float, y: float, z: float) -> None:
        """Canvas only fires this signal for valid grid-intersection clicks."""
        project = self._vm.project
        if project is None:
            return
        node_id = self._find_or_create_node_at(x, y, z)
        self._resolve_endpoint(node_id)

    # ── core flow ───────────────────────────────────────────────────
    def _resolve_endpoint(self, node_id: int) -> None:
        if self._first_node_id is None:
            self._first_node_id = node_id
            self._canvas.selection.select_node(node_id)
            self.statusChanged.emit(self.prompt())
            return

        if node_id == self._first_node_id:
            return  # ignore self-pick

        first = self._first_node_id
        self._first_node_id = None
        try:
            self._create_frame(first, node_id)
        finally:
            self._canvas.selection.clear()
            self.statusChanged.emit(self.prompt())

    # ── helpers ─────────────────────────────────────────────────────
    def _find_or_create_node_at(self, x: float, y: float, z: float) -> int:
        """Return an existing node id at (x, y, z) or create one inside a macro."""
        project = self._vm.project
        assert project is not None
        for n in project.nodes:
            nx, ny, nz = n.coords
            if (abs(nx - x) <= _COINCIDENT_TOL
                    and abs(ny - y) <= _COINCIDENT_TOL
                    and abs(nz - z) <= _COINCIDENT_TOL):
                return n.id
        nid = project.next_node_id()
        self._vm.apply_command(
            AddNodesCommand(self._vm, [Node(id=nid, coords=(x, y, z))])
        )
        return nid

    def _create_frame(self, n1: int, n2: int) -> None:
        project = self._vm.project
        if project is None:
            return

        self._vm.undo_stack.beginMacro(f"Draw frame {n1}-{n2}")
        try:
            section_id = self._ensure_default_section()
            element_id = project.next_element_id()
            elem = ElasticBeamColumn(
                id=element_id, nodes=(n1, n2), section_id=section_id,
            )
            self._vm.apply_command(AddElementsCommand(self._vm, [elem]))
        finally:
            self._vm.undo_stack.endMacro()

    def _ensure_default_section(self) -> int:
        """Return the id of an existing ElasticSection or create + push one."""
        for sec in self._vm.project.sections:
            if isinstance(sec, ElasticSection):
                return sec.id
        new_id = self._vm.project.next_section_id()
        section = ElasticSection(id=new_id, **_DEFAULT_SECTION)
        self._vm.apply_command(AddSectionsCommand(self._vm, [section]))
        return new_id
