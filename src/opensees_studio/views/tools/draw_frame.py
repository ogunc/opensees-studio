"""DrawFrameTool — SAP2000-style chained clicks to draw frames.

Each click (on an existing node or on an empty grid intersection)
resolves to a **node id**:
- Click on an existing node → use it.
- Click on empty space → the point is snapped to the nearest grid
  intersection; if a node already sits within a small tolerance, reuse
  it, otherwise create a new node on the fly.

The first resolved click records the start; every next click closes a
frame and starts the following one at the same point, so a beam line or
a column stack is drawn without lifting the pen. Esc, or a second click
on the last point, ends the chain. Each frame is one QUndoStack macro.

The frames take :attr:`DrawFrameTool.section_id` (the Section box of the
Tools toolbar). With none chosen, the first elastic section is used, and a
default one is created with :class:`AddSectionsCommand` inside the same
macro when the project has none.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands import (
    AddElementsCommand,
    AddNodesCommand,
    AddSectionsCommand,
    AssignSectionCommand,
)
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    FiberSection,
    ForceBeamColumn,
    Node,
    SectionAggregator,
    find_default_section,
    make_default_section,
)
from opensees_studio.core.sections import SHELL_SECTION_CLASSES
from opensees_studio.views.tools.base import CanvasTool

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

    from opensees_studio.viewmodels import ProjectViewModel
    from opensees_studio.views.canvas3d import ModelCanvas


# Two world-points within this distance are considered the same node.
_COINCIDENT_TOL = 1e-6


def frame_sections(project: object) -> list[tuple[int, str]]:
    """``(id, name)`` of the sections a drawn frame can take (not the shell ones)."""
    return [
        (s.id, s.name or f"Section {s.id}")
        for s in getattr(project, "sections", [])
        if not isinstance(s, SHELL_SECTION_CLASSES)
    ]


class DrawFrameTool(CanvasTool):
    """Pick points (nodes or grid intersections) to draw a chain of frames."""

    name = "Draw Frame"
    consumes_picks = True
    #: A click on a joint reuses it, so the hover marks the joint too.
    wants_node_snap = True
    draws_preview = True

    def __init__(
        self,
        canvas: ModelCanvas,
        vm: ProjectViewModel,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(canvas, vm, parent)
        self._first_node_id: int | None = None
        #: The section of the next frames; None = the first elastic one (or a default).
        self.section_id: int | None = None

    # ── lifecycle ───────────────────────────────────────────────────
    def activate(self) -> None:
        # The camera stays where the user left it: a tool that moves the view
        # makes every click land somewhere unexpected. Clicks are resolved in
        # screen space, so this works in plan, elevation and isometric alike.
        self._canvas.set_snap_preview_enabled(True)
        super().activate()

    def deactivate(self) -> None:
        self._canvas.set_snap_reference(None)
        self._canvas.set_snap_preview_enabled(False)
        super().deactivate()

    def reset(self) -> None:
        self._first_node_id = None
        self._canvas.set_snap_reference(None)
        self._canvas.selection.clear()
        self._refresh_draw_preview()

    def preview_points(self) -> list[tuple[float, float, float]]:
        """The start of the next member; the preview runs to the pointer."""
        if self._first_node_id is None:
            return []
        point = self._node_point(self._first_node_id)
        return [] if point is None else [point]

    def prompt(self) -> str:
        if self._first_node_id is None:
            return (
                "Draw Frame: click the FIRST point (node or grid intersection)." + self.grid_hint()
            )
        return (
            f"Draw Frame: from node {self._first_node_id}, click the NEXT point "
            "(Esc or a second click here ends the chain)." + self.grid_hint()
        )

    # ── picks ───────────────────────────────────────────────────────
    def on_node_picked(self, node_id: int) -> None:
        self._resolve_endpoint(node_id)

    def on_empty_clicked(self, x: float, y: float, z: float, snapped: bool = True) -> None:
        """A resolved point: a grid intersection, or the working plane."""
        project = self._vm.project
        if project is None:
            return
        if project.ndm == 2:
            y = 0.0  # a 2D model lives in the X-Z plane (core.plane)
        node_id = self._find_or_create_node_at(x, y, z)
        self._resolve_endpoint(node_id)

    # ── core flow ───────────────────────────────────────────────────
    def _resolve_endpoint(self, node_id: int) -> None:
        if self._first_node_id is None:
            self._first_node_id = node_id
            self._set_snap_reference_to_node(node_id)
            self._canvas.selection.select_node(node_id)
            self._refresh_draw_preview()
            self.statusChanged.emit(self.prompt())
            return

        if node_id == self._first_node_id:
            # A second click on the last point ends the chain.
            self.reset()
            self.statusChanged.emit(self.prompt())
            return

        first = self._first_node_id
        try:
            self._create_frame(first, node_id)
        except Exception:
            self.reset()
            self.statusChanged.emit(self.prompt())
            raise
        # The end of this frame is the start of the next one.
        self._first_node_id = node_id
        self._set_snap_reference_to_node(node_id)
        self._canvas.selection.clear()
        self._canvas.selection.select_node(node_id)
        self._refresh_draw_preview()
        self.statusChanged.emit(self.prompt())

    # ── helpers ─────────────────────────────────────────────────────
    def _find_or_create_node_at(self, x: float, y: float, z: float) -> int:
        """Return an existing node id at (x, y, z) or create one inside a macro."""
        project = self._vm.project
        assert project is not None
        for n in project.nodes:
            nx, ny, nz = n.coords
            if (
                abs(nx - x) <= _COINCIDENT_TOL
                and abs(ny - y) <= _COINCIDENT_TOL
                and abs(nz - z) <= _COINCIDENT_TOL
            ):
                return n.id
        nid = project.next_node_id()
        self._vm.apply_command(AddNodesCommand(self._vm, [Node(id=nid, coords=(x, y, z))]))
        return nid

    def _create_frame(self, n1: int, n2: int) -> None:
        project = self._vm.project
        if project is None:
            return

        chosen = next((s for s in project.sections if s.id == self.section_id), None)
        self._vm.undo_stack.beginMacro(f"Draw frame {n1}-{n2}")
        try:
            element_id = project.next_element_id()
            if isinstance(chosen, FiberSection | SectionAggregator):
                # A nonlinear section: the element that integrates it.
                elem: ElasticBeamColumn | ForceBeamColumn = ForceBeamColumn(
                    id=element_id, nodes=(n1, n2), section_id=chosen.id
                )
            else:
                elastic = chosen.id if isinstance(chosen, ElasticSection) else None
                elem = ElasticBeamColumn(
                    id=element_id,
                    nodes=(n1, n2),
                    section_id=elastic or self._ensure_default_section(),
                )
            self._vm.apply_command(AddElementsCommand(self._vm, [elem]))
            if chosen is not None and not isinstance(
                chosen, ElasticSection | FiberSection | SectionAggregator
            ):
                # A nonprismatic section subdivides the member as it is assigned.
                self._vm.apply_command(AssignSectionCommand(self._vm, {element_id}, chosen.id))
        finally:
            self._vm.undo_stack.endMacro()

    def _ensure_default_section(self) -> int:
        """Return the id of an existing ElasticSection or create + push one.

        The default-section values live in ``core.defaults`` (shared with the web
        backend); this tool only owns the *undoable* insert.
        """
        project = self._vm.project
        assert project is not None
        existing = find_default_section(project)
        if existing is not None:
            return existing.id
        section = make_default_section(project.next_section_id(), project)
        self._vm.apply_command(AddSectionsCommand(self._vm, [section]))
        return section.id
