"""DrawTrussTool — two-click truss-bar creator.

Mirrors :class:`DrawFrameTool` but produces a :class:`TrussElement`
(pin-ended axial member). Picks an existing ``ElasticUniaxial`` or
``Steel01`` / ``Steel02`` material if one is defined — otherwise
creates a minimal elastic default inside the same undo macro so the
whole "Draw Truss" action is a single undo step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands import (
    AddElementsCommand,
    AddMaterialsCommand,
    AddNodesCommand,
)
from opensees_studio.core import (
    DEFAULT_TRUSS_AREA,
    Node,
    TrussElement,
    find_default_truss_material,
    make_default_truss_material,
)
from opensees_studio.views.tools.base import CanvasTool

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

    from opensees_studio.viewmodels import ProjectViewModel
    from opensees_studio.views.canvas3d import ModelCanvas


_COINCIDENT_TOL = 1e-6


class DrawTrussTool(CanvasTool):
    """Pick two points → create a TrussElement connecting them."""

    name = "Draw Truss"
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
            return "Draw Truss: click the FIRST end (node or grid intersection)."
        return (
            f"Draw Truss: first node = {self._first_node_id}. "
            "Click the SECOND end (Esc to cancel)."
        )

    # ── picks ───────────────────────────────────────────────────────
    def on_node_picked(self, node_id: int) -> None:
        self._resolve_endpoint(node_id)

    def on_empty_clicked(self, x: float, y: float, z: float) -> None:
        project = self._vm.project
        if project is None:
            return
        node_id = self._find_or_create_node_at(x, y, z)
        self._resolve_endpoint(node_id)

    # ── core ────────────────────────────────────────────────────────
    def _resolve_endpoint(self, node_id: int) -> None:
        if self._first_node_id is None:
            self._first_node_id = node_id
            self._canvas.selection.select_node(node_id)
            self.statusChanged.emit(self.prompt())
            return
        if node_id == self._first_node_id:
            return
        first = self._first_node_id
        self._first_node_id = None
        try:
            self._create_truss(first, node_id)
        finally:
            self._canvas.selection.clear()
            self.statusChanged.emit(self.prompt())

    def _find_or_create_node_at(self, x: float, y: float, z: float) -> int:
        project = self._vm.project
        assert project is not None
        for n in project.nodes:
            if (abs(n.coords[0] - x) <= _COINCIDENT_TOL
                    and abs(n.coords[1] - y) <= _COINCIDENT_TOL
                    and abs(n.coords[2] - z) <= _COINCIDENT_TOL):
                return n.id
        nid = project.next_node_id()
        self._vm.apply_command(
            AddNodesCommand(self._vm, [Node(id=nid, coords=(x, y, z))])
        )
        return nid

    def _create_truss(self, n1: int, n2: int) -> None:
        project = self._vm.project
        if project is None:
            return
        self._vm.undo_stack.beginMacro(f"Draw truss {n1}-{n2}")
        try:
            mat_id = self._ensure_default_material()
            element_id = project.next_element_id()
            elem = TrussElement(
                id=element_id,
                nodes=(n1, n2),
                area=DEFAULT_TRUSS_AREA,
                material_id=mat_id,
            )
            self._vm.apply_command(AddElementsCommand(self._vm, [elem]))
        finally:
            self._vm.undo_stack.endMacro()

    def _ensure_default_material(self) -> int:
        """Pick the first ElasticUniaxial in the project, or add one.

        The default-material values live in ``core.defaults`` (shared with the web
        backend); this tool only owns the *undoable* insert.
        """
        project = self._vm.project
        assert project is not None
        existing = find_default_truss_material(project)
        if existing is not None:
            return existing.id
        mat = make_default_truss_material(project.next_material_id())
        self._vm.apply_command(AddMaterialsCommand(self._vm, [mat]))
        return mat.id
