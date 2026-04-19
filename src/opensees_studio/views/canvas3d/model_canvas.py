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
        self._snap_preview_enabled = False   # toggled by Draw tools
        # SAP2000-style "working plane": when set, snap filters to grid
        # intersections lying on the plane so the user drawing in plan
        # view doesn't accidentally grab a Z=3 intersection from Z=0.
        self._working_plane: tuple[str, float] | None = None
        # Needed so mouseMoveEvent fires without a button pressed.
        self.setMouseTracking(True)

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

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        """Live snap-target preview — hover highlight on the closest grid
        intersection within pixel tolerance. Skipped entirely when the
        default selection tool is active (no need to hint at snap there).
        """
        super().mouseMoveEvent(event)
        if not self._snap_preview_enabled:
            return
        pos = event.position()
        dpr = float(self.devicePixelRatioF()) if hasattr(self, "devicePixelRatioF") else 1.0
        h_logical = self.height()
        cx = pos.x() * dpr
        cy = (h_logical - pos.y()) * dpr
        tol_px = 15.0 * dpr
        target = self._nearest_grid_intersection_px(cx, cy, tol_px)
        self._renderer.set_hover_snap(target)
        self.render()

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
        frame_tol_px = 18.0 * dpr

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

        # ── Otherwise try frames (point-to-segment distance on screen). ──
        frame_pd = self._renderer._frame_pd
        frame_ids = self._renderer._frame_ids_ordered
        if frame_pd is not None and frame_ids:
            pts = np.asarray(frame_pd.points)
            lines = np.asarray(frame_pd.lines).reshape(-1, 3)
            a_world = pts[lines[:, 1]]
            b_world = pts[lines[:, 2]]
            a_screen = self._project_world_to_screen(a_world, renderer)
            b_screen = self._project_world_to_screen(b_world, renderer)
            if (a_screen is not None and b_screen is not None
                    and len(a_screen) and len(b_screen)):
                # Point-to-segment distance in 2D. Clicking anywhere along
                # the rendered line (not just near the midpoint) picks it.
                p = np.array([cx, cy], dtype=float)
                ab = b_screen - a_screen
                ab_sq = (ab ** 2).sum(axis=1)
                ab_sq = np.where(ab_sq == 0, 1.0, ab_sq)  # avoid div/0 on degenerate
                pa = p - a_screen
                t = (pa * ab).sum(axis=1) / ab_sq
                t = np.clip(t, 0.0, 1.0)
                closest = a_screen + t[:, None] * ab
                d2 = ((p - closest) ** 2).sum(axis=1)
                idx = int(np.argmin(d2))
                if _PICK_DEBUG:
                    print(f"[pick] nearest frame id={frame_ids[idx]} "
                          f"d={float(np.sqrt(d2[idx])):.1f}px "
                          f"(threshold {frame_tol_px:.1f})")
                if d2[idx] <= frame_tol_px ** 2:
                    self._dispatch_pick("element", int(frame_ids[idx]))
                    return

        if _PICK_DEBUG:
            print("[pick] no hit within tolerance")

        # ── Empty-click fallback: pixel-space snap to grid intersections. ──
        # SAP2000 behaviour: only an intersection within a small pixel
        # tolerance commits. Clicks anywhere else are silently ignored so
        # users can't accidentally drop nodes in the middle of cells.
        grid_tol_px = 15.0 * dpr
        snapped = self._nearest_grid_intersection_px(cx, cy, grid_tol_px)
        if snapped is not None:
            self.emptyClicked.emit(float(snapped[0]), float(snapped[1]), float(snapped[2]))
        elif _PICK_DEBUG:
            print("[pick] off-grid click — no snap target within tolerance")

    def _grid_intersections_world(self) -> np.ndarray | None:
        """Return an (N, 3) array of every snappable grid intersection.

        If a working plane is active (via set_working_plane), the result
        is filtered to intersections whose perpendicular-axis coordinate
        matches the plane's offset — so a user drawing in plan view at
        Z=0 never accidentally snaps to a Z=3 grid above them.
        """
        project = self._renderer._project
        if project is None:
            return None
        systems = getattr(project, "coord_systems", None) or []
        rows: list[tuple[float, float, float]] = []
        for cs in systems:
            grid = cs.grid
            if not grid.visible or grid.hide_all:
                continue
            xs = grid.x_lines or [0.0]
            ys = grid.y_lines or [0.0]
            zs = grid.z_lines or [0.0]
            if not (grid.x_lines or grid.y_lines or grid.z_lines):
                continue
            for z in zs:
                for x in xs:
                    for y in ys:
                        rows.append(cs.coord.local_to_world((x, y, z)))
        if not rows:
            return None
        pts = np.asarray(rows, dtype=float)

        if self._working_plane is not None:
            plane, offset = self._working_plane
            axis_idx = {"XY": 2, "XZ": 1, "YZ": 0}[plane]
            mask = np.isclose(pts[:, axis_idx], offset, atol=1e-6)
            pts = pts[mask]
            if len(pts) == 0:
                return None
        return pts

    def _nearest_grid_intersection_px(
        self, cx: float, cy: float, tol_px: float,
    ) -> tuple[float, float, float] | None:
        """Return the world-space intersection closest to the click pixel,
        or ``None`` if every intersection is further than ``tol_px``."""
        world_points = self._grid_intersections_world()
        if world_points is None or len(world_points) == 0:
            return None
        screen = self._project_world_to_screen(world_points, self.renderer)
        if screen is None or len(screen) == 0:
            return None
        d2 = (screen[:, 0] - cx) ** 2 + (screen[:, 1] - cy) ** 2
        idx = int(np.argmin(d2))
        if _PICK_DEBUG:
            print(f"[grid-snap] nearest intersection "
                  f"world={world_points[idx]} d={float(np.sqrt(d2[idx])):.1f}px "
                  f"(threshold {tol_px:.1f})")
        if d2[idx] <= tol_px ** 2:
            return tuple(float(v) for v in world_points[idx])  # type: ignore[return-value]
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

    def set_snap_preview_enabled(self, enabled: bool) -> None:
        """Toggle the hover snap-target preview. Draw tools turn it on;
        the Select tool turns it off (and clears any visible marker)."""
        self._snap_preview_enabled = enabled
        if not enabled:
            self._renderer.set_hover_snap(None)
            self.render()

    # ── working-plane state (plan / elevation level) ────────────────
    def set_working_plane(self, plane: str, offset: float) -> None:
        """Set the active plan (XY) / elevation (XZ / YZ) level.

        ``plane`` is ``"XY"``, ``"XZ"``, or ``"YZ"``. ``offset`` is the
        world-space value along the perpendicular axis (z for XY,
        y for XZ, x for YZ). Both the SNAP filter and the grid OVERLAY
        follow this setting: only the current level's grid lines and
        intersections render so the plan view isn't cluttered with
        other floors' geometry. Also reframes the camera on the new
        plane so the user always sees the active grid — without this
        the camera keeps its old bounds and Z=3 can fall out of view.
        """
        if plane not in ("XY", "XZ", "YZ"):
            raise ValueError(f"Unsupported working plane: {plane!r}")
        self._working_plane = (plane, float(offset))
        self._renderer.set_working_plane((plane, float(offset)))
        self.render()

    def clear_working_plane(self) -> None:
        """Return to unfiltered snap (iso / full-3D mode)."""
        self._working_plane = None
        self._renderer.set_working_plane(None)
        self.render()

    def working_plane_type(self) -> str | None:
        """Return the current working-plane axis code, or None if off."""
        return self._working_plane[0] if self._working_plane is not None else None

    def working_plane_offset(self) -> float | None:
        return self._working_plane[1] if self._working_plane is not None else None

    def set_show_section_extrusions(self, enabled: bool) -> None:
        """SAP2000 parity: Show Extruded View — sweep each frame element's
        section bbox along its axis as a semi-transparent box so the user
        can see section orientation and physical footprint."""
        self._renderer.set_show_section_extrusions(enabled)
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
