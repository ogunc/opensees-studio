"""DrawFrameTool — click-click to create an ``ElasticBeamColumn``.

If no section exists yet, the tool macro-pushes an
``AddSectionsCommand`` for a default ``ElasticSection`` so the whole
"draw frame" action shows up as a single undo step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands import AddElementsCommand, AddSectionsCommand
from opensees_studio.core import ElasticBeamColumn, ElasticSection
from opensees_studio.views.tools.base import CanvasTool

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

    from opensees_studio.viewmodels import ProjectViewModel
    from opensees_studio.views.canvas3d import ModelCanvas


# Sensible defaults for an "S420 W-section-ish" steel beam, used only when
# the user hasn't defined any section yet. Phase 5's section library will
# let the user override this before drawing.
_DEFAULT_SECTION = dict(
    name="Default Section",
    E=200e9,
    A=0.01,
    Iz=8.33e-6,
    Iy=8.33e-6,
    G=80e9,
    J=1e-6,
)


class DrawFrameTool(CanvasTool):
    """Pick two nodes to create an elastic beam-column between them."""

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
    def reset(self) -> None:
        self._first_node_id = None
        # Clear any visual indicator left over from the first pick.
        self._canvas.selection.clear()

    def prompt(self) -> str:
        if self._first_node_id is None:
            return "Draw Frame: pick the FIRST node."
        return f"Draw Frame: first node = {self._first_node_id}. Pick the SECOND node (or Esc to cancel)."

    # ── picks ───────────────────────────────────────────────────────
    def on_node_picked(self, node_id: int) -> None:
        if self._first_node_id is None:
            self._first_node_id = node_id
            # Highlight the first node so the user has visual feedback.
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
    def _create_frame(self, n1: int, n2: int) -> None:
        project = self._vm.project
        if project is None:
            return

        self._vm.undo_stack.beginMacro(f"Draw frame {n1}–{n2}")
        try:
            section_id = self._ensure_default_section()
            element_id = project.next_element_id()
            elem = ElasticBeamColumn(id=element_id, nodes=(n1, n2), section_id=section_id)
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
