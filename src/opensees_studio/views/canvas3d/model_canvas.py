"""3D model viewport (Qt-embeddable PyVista interactor).

This is the central widget. It owns:
- a ``ModelRenderer`` (does the painting)
- a ``SelectionState`` (shared with the rest of the UI)
- picking wiring that translates clicks into selection-state updates
- the standard scene furniture (axes, grid)

It exposes signals that other widgets can subscribe to without
needing a reference to the renderer.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QWidget
from pyvistaqt import QtInteractor

from opensees_studio.core import Project
from opensees_studio.views.canvas3d.model_renderer import ModelRenderer
from opensees_studio.views.canvas3d.selection import SelectionState
from opensees_studio.views.canvas3d.style import RenderStyle

_PICK_DEBUG = os.environ.get("OSS_PICK_DEBUG") == "1"


class ModelCanvas(QtInteractor):  # type: ignore[misc]
    """The central 3D viewport widget."""

    # Convenience signals re-emitted from SelectionState.
    nodePicked = Signal(int)
    elementPicked = Signal(int)
    #: Emitted when the user clicks an empty area of the viewport.
    #: Payload: world-space (x, y, z) obtained by unprojecting the click
    #: onto the Z=0 plane. Tools use this to place new geometry.
    emptyClicked = Signal(float, float, float)

    def __init__(
        self,
        parent: QWidget | None = None,
        style: RenderStyle | None = None,
        selection: SelectionState | None = None,
    ) -> None:
        super().__init__(parent)
        self._style = style or RenderStyle()
        self.selection = selection or SelectionState(self)
        self._renderer = ModelRenderer(self, self._style)
        self._default_selection_enabled = True

        self._build_scene_furniture()
        # No track_click_position — we use Qt's mousePressEvent directly.

        # Re-render on selection change so highlighting updates.
        self.selection.selectionChanged.connect(self._renderer.update_selection)

    # ── Qt event override: this is the actual entry point for picking. ──
    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        """Catch left-clicks for picking; let everything else pass through.

        We deliberately override at the Qt level rather than going through
        PyVista's track_click_position / enable_mesh_picking. Those layers
        proved unreliable in this scene (vtkHardwareSelector overflows on
        glyph meshes, picker references aren't always exposed). Qt's mouse
        event is the lowest-level guaranteed signal.

        The base ``super().mousePressEvent`` MUST still be called so VTK
        rotate/pan/zoom keep working.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            # Remember the press position. We only commit a pick if the user
            # didn't drag (drags are camera rotation).
            self._press_pos = event.position()
            self._press_modifiers = event.modifiers()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            release_pos = event.position()
            press = getattr(self, "_press_pos", None)
            if press is not None:
                dx = release_pos.x() - press.x()
                dy = release_pos.y() - press.y()
                if dx * dx + dy * dy <= 9.0:        # ≤ 3 px movement → click
                    self._handle_click(release_pos.x(), release_pos.y())
        super().mouseReleaseEvent(event)

    def _handle_click(self, qt_x: float, qt_y: float) -> None:
        """Run our screen-space picking from Qt-coordinate (top-left origin).

        Qt gives us *logical* pixels (DPI-aware). VTK works in *device*
        pixels (physical). On HiDPI displays (typical Windows scaling
        125-200%) these differ — we must scale by devicePixelRatio.
        """
        dpr = float(self.devicePixelRatioF()) if hasattr(self, "devicePixelRatioF") else 1.0
        # Qt's Y axis is top-down; VTK display coords are bottom-up.
        h_logical = self.height()
        cx = qt_x * dpr
        cy = (h_logical - qt_y) * dpr

        if _PICK_DEBUG:
            print(f"[pick] click qt=({qt_x:.0f},{qt_y:.0f}) → vtk=({cx:.0f},{cy:.0f}) "
                  f"viewport_logical=({self.width()}x{h_logical}) dpr={dpr}")

        renderer = self.renderer

        # Tolerances are in *device* pixels — scale them with DPR so the
        # click-target stays the same physical size on screen.
        node_tol_px = 18.0 * dpr
        frame_tol_px = 12.0 * dpr

        # ── Try nodes first (smaller targets). ──
        node_pd = self._renderer._node_pd
        node_ids = self._renderer._node_ids_ordered
        if node_pd is not None and node_ids:
            node_screen = self._project_world_to_screen(
                np.asarray(node_pd.points), renderer
            )
            if node_screen is not None and len(node_screen):
                d2 = (node_screen[:, 0] - cx) ** 2 + (node_screen[:, 1] - cy) ** 2
                idx = int(np.argmin(d2))
                if _PICK_DEBUG:
                    print(f"[pick] nearest node id={node_ids[idx]} "
                          f"screen={node_screen[idx]} d={np.sqrt(d2[idx]):.1f}px "
                          f"(threshold {node_tol_px:.1f})")
                if d2[idx] <= node_tol_px ** 2:
                    self._dispatch_pick("node", int(node_ids[idx]))
                    return

        # ── Otherwise try frames. ──
        frame_pd = self._renderer._frame_pd
        frame_ids = self._renderer._frame_ids_ordered
        if frame_pd is not None and frame_ids:
            pts = np.asarray(frame_pd.points)
            lines = np.asarray(frame_pd.lines).reshape(-1, 3)
            midpoints = (pts[lines[:, 1]] + pts[lines[:, 2]]) * 0.5
            mid_screen = self._project_world_to_screen(midpoints, renderer)
            if mid_screen is not None and len(mid_screen):
                d2 = (mid_screen[:, 0] - cx) ** 2 + (mid_screen[:, 1] - cy) ** 2
                idx = int(np.argmin(d2))
                if _PICK_DEBUG:
                    print(f"[pick] nearest frame id={frame_ids[idx]} d={np.sqrt(d2[idx]):.1f}px")
                if d2[idx] <= frame_tol_px ** 2:
                    self._dispatch_pick("element", int(frame_ids[idx]))
                    return

        if _PICK_DEBUG:
            print("[pick] no hit within tolerance")
        # ── Empty-click fallback: unproject to Z=0 and emit. ──
        world = self._world_point_at_z_plane(cx, cy, z_plane=0.0)
        if world is not None:
            self.emptyClicked.emit(float(world[0]), float(world[1]), float(world[2]))

    def _world_point_at_z_plane(
        self, vtk_cx: float, vtk_cy: float, z_plane: float = 0.0,
    ) -> tuple[float, float, float] | None:
        """Unproject a viewport pixel to a world point on a horizontal plane.

        Works by taking two points along the eye-ray (near + far planes in
        display coords), turning them into world coords via VTK, then
        intersecting the resulting line with ``z = z_plane``. Returns
        ``None`` if the ray is parallel to the plane.
        """
        try:
            import vtk
            renderer = self.renderer
            coord = vtk.vtkCoordinate()
            coord.SetCoordinateSystemToDisplay()
            coord.SetValue(float(vtk_cx), float(vtk_cy), 0.0)
            near = coord.GetComputedWorldValue(renderer)
            coord.SetValue(float(vtk_cx), float(vtk_cy), 1.0)
            far = coord.GetComputedWorldValue(renderer)
            dz = far[2] - near[2]
            if abs(dz) < 1e-12:
                return None
            t = (z_plane - near[2]) / dz
            x = near[0] + t * (far[0] - near[0])
            y = near[1] + t * (far[1] - near[1])
            return (x, y, z_plane)
        except Exception:
            return None

    # ── public API ──────────────────────────────────────────────────
    def show_project(self, project: Project | None) -> None:
        """Render (or clear) the given project. Frames the camera afterward."""
        self._renderer.render(project)
        if project is not None and project.nodes:
            self.reset_camera()
        self.render()

    def clear_model(self) -> None:
        """Remove the current model but keep the grid/axes furniture."""
        self.selection.clear()
        self._renderer.render(None)
        self.render()

    def set_default_selection_enabled(self, enabled: bool) -> None:
        """When False, picks fire ``nodePicked``/``elementPicked`` but the
        canvas does NOT auto-update :attr:`selection`. Tools toggle this
        off so they can interpret picks themselves.
        """
        self._default_selection_enabled = enabled

    # ── internals ───────────────────────────────────────────────────
    def _build_scene_furniture(self) -> None:
        # SAP2000 parity: no default bounding-box grid / axis-label furniture.
        # The user's own GridSystem is the only reference overlay shown; the
        # small corner orientation triad is kept because SAP also has one.
        self.set_background(self._style.background_bottom, top=self._style.background_top)
        self.view_isometric()

    def _project_world_to_screen(
        self, points: np.ndarray, renderer: Any,
    ) -> np.ndarray | None:
        """Project Nx3 world points to Nx2 viewport pixel coordinates.

        Uses VTK's coordinate transform — the same one the renderer uses
        to put pixels on the screen, so it accounts for current camera,
        zoom, pan, viewport size, and HiDPI scaling.
        """
        if points.size == 0:
            return None
        try:
            import vtk
            coord = vtk.vtkCoordinate()
            coord.SetCoordinateSystemToWorld()
            out = np.empty((points.shape[0], 2), dtype=float)
            for i, p in enumerate(points):
                coord.SetValue(float(p[0]), float(p[1]), float(p[2]))
                px = coord.GetComputedDisplayValue(renderer)
                out[i, 0] = float(px[0])
                out[i, 1] = float(px[1])
            return out
        except Exception:
            return None

    def _dispatch_pick(self, kind: str, entity_id: int) -> None:
        additive = self._is_additive_modifier()
        if kind == "node":
            if self._default_selection_enabled:
                if additive:
                    self.selection.toggle_node(entity_id)
                else:
                    self.selection.select_node(entity_id)
            self.nodePicked.emit(entity_id)
        elif kind == "element":
            if self._default_selection_enabled:
                if additive:
                    self.selection.toggle_element(entity_id)
                else:
                    self.selection.select_element(entity_id)
            self.elementPicked.emit(entity_id)

    def _is_additive_modifier(self) -> bool:
        """True if Ctrl or Shift was held during the most recent left-click."""
        mods = getattr(self, "_press_modifiers", Qt.KeyboardModifier.NoModifier)
        return bool(mods & (Qt.KeyboardModifier.ControlModifier
                            | Qt.KeyboardModifier.ShiftModifier))
