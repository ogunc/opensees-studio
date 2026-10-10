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
from collections.abc import Callable
from typing import Any

import numpy as np
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QToolTip, QWidget
from pyvistaqt import QtInteractor

from opensees_studio.core import Project
from opensees_studio.views.canvas3d.model_renderer import ModelRenderer
from opensees_studio.views.canvas3d.selection import SelectionState
from opensees_studio.views.canvas3d.style import RenderStyle

_PICK_DEBUG = os.environ.get("OSS_PICK_DEBUG") == "1"

#: How far the pointer may travel between press and release and still count as a
#: click. The old bound was 3 px, and a hand that drifts more than that — a
#: trackpad, a fast mouse, a trembling one, a remote desktop that quantises
#: motion — had every click swallowed as a bogus camera drag: "no se puede
#: dibujar". A deliberate orbit travels much further, and the camera is put back
#: where it was whenever a click is accepted, so drift leaves no trace.
CLICK_MAX_DRIFT_PX = 20.0

#: How much the *view* must turn before a gesture is called an orbit. Pixels are
#: a proxy — a trembling hand or a tap-and-move on a trackpad drifts tens of
#: pixels while barely turning the camera, and rejecting those made drawing feel
#: broken. Three degrees is visible; jitter is two orders of magnitude below it.
CAMERA_DRAG_ANGLE_DEG = 3.0

#: A pan does not turn the camera, so it is measured on the focal point: moving
#: it more than this share of the viewing distance is a deliberate pan.
CAMERA_DRAG_PAN_FRACTION = 0.05


class ModelCanvas(QtInteractor):  # type: ignore[misc]
    """The central 3D viewport widget."""

    # Convenience signals re-emitted from SelectionState.
    nodePicked = Signal(int)
    elementPicked = Signal(int)
    #: Emitted when a press/release moved too far to be a click while a
    #: pick-consuming tool was armed, so the user learns why nothing happened.
    dragNotAClick = Signal()
    #: Emitted when the user clicks an empty area of the viewport.
    #: Payload: world-space (x, y, z) obtained by unprojecting the click
    #: onto the Z=0 plane. Tools use this to place new geometry.
    emptyClicked = Signal(float, float, float, bool)
    """Empty-space click: world x, y, z, and whether it snapped to a grid
    intersection (False = it landed on the working plane where the ray crossed
    it)."""

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
        self._snap_preview_enabled = False  # toggled by Draw tools
        #: Optional provider of hover text per element id (set by the main
        #: window); elements it returns None for show no tooltip.
        self.element_tooltip: Callable[[int], str | None] | None = None
        self._tooltip_element: int | None = None
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
            # Remember where the press started and what the camera looked like:
            # whether this becomes a click or a drag depends on how far the
            # pointer travels (see CLICK_MAX_DRIFT_PX), and an accepted click
            # restores the camera VTK turned during the drift.
            self._press_pos = event.position()
            self._press_modifiers = event.modifiers()
            self._press_camera = self._camera_state()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        # VTK finishes its interaction inside `super()` and may still apply the
        # rotation as the button goes up, so the pick is handled afterwards:
        # anything restored before that would be overwritten.
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            release_pos = event.position()
            press = getattr(self, "_press_pos", None)
            if press is not None:
                dx = release_pos.x() - press.x()
                dy = release_pos.y() - press.y()
                drift = (dx * dx + dy * dy) ** 0.5
                if self._default_selection_enabled:
                    # Selecting: the tighter budget, and a camera that did not
                    # move at all also counts as a click.
                    clicked = drift <= CLICK_MAX_DRIFT_PX or not self._camera_moved_since_press()
                else:
                    # A tool is armed and the user meant to place something. The
                    # only alternative a gesture has is orbiting, so the question
                    # is exactly "did the view move?" — pixels are a poor proxy, a
                    # trackpad tap drifts a lot while turning the camera almost
                    # not at all, and a fast flick turns it without drifting far.
                    clicked = not self._camera_moved_visibly()
                if clicked:
                    # A click: undo the sub-threshold rotation VTK applied while
                    # the pointer drifted, so the view does not creep.
                    self._restore_camera(getattr(self, "_press_camera", None))
                    self._handle_click(release_pos.x(), release_pos.y())
                else:
                    if _PICK_DEBUG:
                        print(
                            f"[pick] press/release treated as a drag "
                            f"(drift {drift:.1f}px, view turned or panned)",
                        )
                    if not self._default_selection_enabled:
                        # A tool is armed and the user expected a pick: say so
                        # instead of leaving them clicking at a dead canvas.
                        self.dragNotAClick.emit()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        """Live snap-target preview — hover highlight on the closest grid
        intersection within pixel tolerance. Skipped entirely when the
        default selection tool is active (no need to hint at snap there).
        """
        super().mouseMoveEvent(event)
        if self.element_tooltip is not None:
            self._update_element_tooltip(event.position().x(), event.position().y())
        if not self._snap_preview_enabled:
            return
        pos = event.position()
        dpr = float(self.devicePixelRatioF()) if hasattr(self, "devicePixelRatioF") else 1.0
        h_logical = self.height()
        cx = pos.x() * dpr
        cy = (h_logical - pos.y()) * dpr
        tol_px = 15.0 * dpr
        target = self._nearest_grid_intersection_px(cx, cy, tol_px)
        if target is None:
            # Off the intersection: preview where the click would actually land
            # — the nearest grid crossing, or the working plane without a grid.
            free = self.world_on_working_plane(cx, cy)
            target = self._nearest_grid_crossing(free) if free is not None else None
        self._renderer.set_hover_snap(target)
        self.render()

    def _to_device(self, qt_x: float, qt_y: float) -> tuple[float, float, float]:
        """Qt logical (top-left) position to VTK device pixels (bottom-up) plus the DPR."""
        dpr = float(self.devicePixelRatioF()) if hasattr(self, "devicePixelRatioF") else 1.0
        return qt_x * dpr, (self.height() - qt_y) * dpr, dpr

    def frame_element_at(
        self, qt_x: float, qt_y: float, tol_logical_px: float = 18.0
    ) -> int | None:
        """Id of the frame-style element whose screen segment is within tolerance, else None."""
        cx, cy, dpr = self._to_device(qt_x, qt_y)
        frame_pd = self._renderer._frame_pd
        frame_ids = self._renderer._frame_ids_ordered
        if frame_pd is None or not frame_ids:
            return None
        pts = np.asarray(frame_pd.points)
        lines = np.asarray(frame_pd.lines).reshape(-1, 3)
        a_screen = self._project_world_to_screen(pts[lines[:, 1]], self.renderer)
        b_screen = self._project_world_to_screen(pts[lines[:, 2]], self.renderer)
        if a_screen is None or b_screen is None or not len(a_screen) or not len(b_screen):
            return None
        p = np.array([cx, cy], dtype=float)
        ab = b_screen - a_screen
        ab_sq = (ab**2).sum(axis=1)
        ab_sq = np.where(ab_sq == 0, 1.0, ab_sq)
        t = np.clip(((p - a_screen) * ab).sum(axis=1) / ab_sq, 0.0, 1.0)
        d2 = ((p - (a_screen + t[:, None] * ab)) ** 2).sum(axis=1)
        idx = int(np.argmin(d2))
        if d2[idx] <= (tol_logical_px * dpr) ** 2:
            return int(frame_ids[idx])
        return None

    def _update_element_tooltip(self, qt_x: float, qt_y: float) -> None:
        """Show the provider's text while hovering an element that has one."""
        eid = self.frame_element_at(qt_x, qt_y)
        text = self.element_tooltip(eid) if (eid is not None and self.element_tooltip) else None
        if text is None:
            if self._tooltip_element is not None:
                QToolTip.hideText()
                self._tooltip_element = None
            return
        if eid != self._tooltip_element:
            self._tooltip_element = eid
            QToolTip.showText(self.mapToGlobal(QPoint(int(qt_x), int(qt_y))), text, self)

    def _camera_state(
        self,
    ) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]] | None:
        """Position, focal point and up vector — what a click must leave alone."""
        camera = self.camera
        if camera is None:
            return None
        return (
            tuple(float(value) for value in camera.position),
            tuple(float(value) for value in camera.focal_point),
            tuple(float(value) for value in camera.up),
        )

    def _camera_moved_visibly(self) -> bool:
        """True when the view visibly turned or panned since the press.

        The question a click/drag decision is really asking: did the user orbit?
        A rotation smaller than :data:`CAMERA_DRAG_ANGLE_DEG`, or a focal point
        that barely moved, is hand tremor rather than intent.
        """
        before = getattr(self, "_press_camera", None)
        after = self._camera_state()
        if before is None or after is None:
            return False
        position0, focal0, _up0 = before
        position1, focal1, _up1 = after
        direction0 = np.asarray(focal0) - np.asarray(position0)
        direction1 = np.asarray(focal1) - np.asarray(position1)
        distance = float(np.linalg.norm(direction0)) or 1.0
        norm0 = float(np.linalg.norm(direction0))
        norm1 = float(np.linalg.norm(direction1))
        if norm0 > 0.0 and norm1 > 0.0:
            cosine = float(np.dot(direction0, direction1) / (norm0 * norm1))
            angle = float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))
            if angle > CAMERA_DRAG_ANGLE_DEG:
                return True
        pan = float(np.linalg.norm(np.asarray(focal1) - np.asarray(focal0)))
        return pan > CAMERA_DRAG_PAN_FRACTION * distance

    def _camera_moved_since_press(self) -> bool:
        """True when the camera is not where it was when the button went down."""
        before = getattr(self, "_press_camera", None)
        after = self._camera_state()
        if before is None or after is None:
            return False
        return any(
            not np.allclose(old, new, rtol=1e-9, atol=1e-12)
            for old, new in zip(before, after, strict=True)
        )

    def _restore_camera(
        self,
        state: tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]] | None,
    ) -> None:
        """Put the camera back where it was when the button went down.

        Only used for a gesture accepted as a click: it removes the
        sub-threshold rotation VTK applied while the pointer drifted inside the
        click budget. A click never zooms, so the scale and angle are untouched.
        """
        if state is None:
            return
        camera = self.camera
        if camera is None:
            return
        position, focal_point, up = state
        if tuple(camera.position) == position and tuple(camera.focal_point) == focal_point:
            return  # nothing moved: leave it alone
        camera.position = position
        camera.focal_point = focal_point
        camera.up = up

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
            print(
                f"[pick] click qt=({qt_x:.0f},{qt_y:.0f}) → vtk=({cx:.0f},{cy:.0f}) "
                f"viewport_logical=({self.width()}x{h_logical}) dpr={dpr}"
            )

        renderer = self.renderer

        # Tolerances are in *device* pixels — scale them with DPR so the
        # click-target stays the same physical size on screen.
        node_tol_px = 18.0 * dpr
        frame_tol_px = 18.0 * dpr

        # ── Try nodes first (smaller targets). ──
        node_pd = self._renderer._node_pd
        node_ids = self._renderer._node_ids_ordered
        if node_pd is not None and node_ids:
            node_screen = self._project_world_to_screen(np.asarray(node_pd.points), renderer)
            if node_screen is not None and len(node_screen):
                d2 = (node_screen[:, 0] - cx) ** 2 + (node_screen[:, 1] - cy) ** 2
                idx = int(np.argmin(d2))
                if _PICK_DEBUG:
                    print(
                        f"[pick] nearest node id={node_ids[idx]} "
                        f"screen={node_screen[idx]} d={np.sqrt(d2[idx]):.1f}px "
                        f"(threshold {node_tol_px:.1f})"
                    )
                if d2[idx] <= node_tol_px**2:
                    self._dispatch_pick("node", int(node_ids[idx]))
                    return

        # ── Otherwise try frames (point-to-segment distance on screen). ──
        # Only the select tool picks members. While a draw tool is armed a member
        # is not a target — and treating it as one swallowed the click silently,
        # which is what made drawing on a model that already has members (a
        # portal frame, say) look broken: every click near a column or a rafter
        # hit the member and nothing happened. Nodes stay pickable, so an
        # existing node can still be reused.
        frame_pd = self._renderer._frame_pd if self._default_selection_enabled else None
        frame_ids = self._renderer._frame_ids_ordered
        if frame_pd is not None and frame_ids:
            pts = np.asarray(frame_pd.points)
            lines = np.asarray(frame_pd.lines).reshape(-1, 3)
            a_world = pts[lines[:, 1]]
            b_world = pts[lines[:, 2]]
            a_screen = self._project_world_to_screen(a_world, renderer)
            b_screen = self._project_world_to_screen(b_world, renderer)
            if a_screen is not None and b_screen is not None and len(a_screen) and len(b_screen):
                # Point-to-segment distance in 2D. Clicking anywhere along
                # the rendered line (not just near the midpoint) picks it.
                p = np.array([cx, cy], dtype=float)
                ab = b_screen - a_screen
                ab_sq = (ab**2).sum(axis=1)
                ab_sq = np.where(ab_sq == 0, 1.0, ab_sq)  # avoid div/0 on degenerate
                pa = p - a_screen
                t = (pa * ab).sum(axis=1) / ab_sq
                t = np.clip(t, 0.0, 1.0)
                closest = a_screen + t[:, None] * ab
                d2 = ((p - closest) ** 2).sum(axis=1)
                idx = int(np.argmin(d2))
                if _PICK_DEBUG:
                    print(
                        f"[pick] nearest frame id={frame_ids[idx]} "
                        f"d={float(np.sqrt(d2[idx])):.1f}px "
                        f"(threshold {frame_tol_px:.1f})"
                    )
                if d2[idx] <= frame_tol_px**2:
                    self._dispatch_pick("element", int(frame_ids[idx]))
                    return

        if _PICK_DEBUG:
            print("[pick] no hit within tolerance")

        # ── Empty-click fallback. ──
        # A grid intersection within a small pixel tolerance wins, so the
        # SAP2000 habit of clicking a grid crossing still gives exactly that
        # point. Anywhere else the click lands where the view ray crosses the
        # working plane (Z = 0 when no level is active) — a dead click with no
        # explanation is what made the draw tools feel broken.
        grid_tol_px = 15.0 * dpr
        snapped = self._nearest_grid_intersection_px(cx, cy, grid_tol_px)
        if snapped is not None:
            if _PICK_DEBUG:
                print(f"[pick] empty click snapped to the grid at {snapped}")
            self.emptyClicked.emit(float(snapped[0]), float(snapped[1]), float(snapped[2]), True)
            return
        free = self.world_on_working_plane(cx, cy)
        if free is not None:
            # A grid exists? Then the click belongs on it: snap to the nearest
            # crossing of a line per in-plane axis. SAP2000 draws on the grid,
            # and a node at (-0.0074, 1.9923) — where the pointer happened to
            # land — reads as broken geometry, not as freedom.
            crossing = self._nearest_grid_crossing(free)
            if crossing is not None:
                if _PICK_DEBUG:
                    print(f"[pick] empty click snapped to the grid crossing {crossing}")
                self.emptyClicked.emit(
                    float(crossing[0]), float(crossing[1]), float(crossing[2]), True
                )
                return
            if _PICK_DEBUG:
                print(f"[pick] no grid: empty click resolved on the working plane at {free}")
            self.emptyClicked.emit(float(free[0]), float(free[1]), float(free[2]), False)
        else:
            # Never silent: this is the "I click and nothing happens" case.
            print(
                "[pick] empty click could not be resolved: the view ray is parallel "
                "to the working plane (rotate the view, or clear the level).",
            )

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

    def _nearest_grid_crossing(
        self,
        point: tuple[float, float, float],
    ) -> tuple[float, float, float] | None:
        """Snap a world point to the nearest crossing of the visible grids.

        The in-plane coordinates each move to their closest grid line (in that
        system's own frame), and the perpendicular one stays on the working
        plane. ``None`` when no visible system has any line — a project with no
        grid draws where the pointer is, which is the only thing it can do.
        """
        project = self._renderer._project
        if project is None:
            return None
        plane = self._working_plane[0] if self._working_plane is not None else "XY"
        in_plane = {"XY": (0, 1), "XZ": (0, 2), "YZ": (1, 2)}[plane]
        best: tuple[float, float, float] | None = None
        best_d2 = float("inf")
        for system in getattr(project, "coord_systems", []) or []:
            grid = system.grid
            if not grid.visible or grid.hide_all:
                continue
            if not (grid.x_lines or grid.y_lines or grid.z_lines):
                continue
            local = system.coord.world_to_local(point)
            lines = (grid.x_lines, grid.y_lines, grid.z_lines)
            snapped = list(local)
            for axis in in_plane:
                if lines[axis]:
                    snapped[axis] = min(lines[axis], key=lambda c: abs(c - local[axis]))
            candidate = system.coord.local_to_world(tuple(snapped))
            d2 = sum((candidate[i] - point[i]) ** 2 for i in range(3))
            if d2 < best_d2:
                best, best_d2 = candidate, d2
        return best

    def _nearest_grid_intersection_px(
        self,
        cx: float,
        cy: float,
        tol_px: float,
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
            print(
                f"[grid-snap] nearest intersection "
                f"world={world_points[idx]} d={float(np.sqrt(d2[idx])):.1f}px "
                f"(threshold {tol_px:.1f})"
            )
        if d2[idx] <= tol_px**2:
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

    def set_display_options(self, *, show_node_labels: bool, show_element_labels: bool) -> None:
        """Toggle viewport labels such as node and element names."""
        self._renderer.set_display_options(
            show_node_labels=show_node_labels,
            show_element_labels=show_element_labels,
        )
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
        self,
        points: np.ndarray,
        renderer: Any,
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

    def world_on_working_plane(self, cx: float, cy: float) -> tuple[float, float, float] | None:
        """Where a click at device pixel ``(cx, cy)`` meets the working plane.

        ``(cx, cy)`` is in VTK display coordinates (origin bottom-left, device
        pixels), the same convention :meth:`_project_world_to_screen` produces.
        The plane is the active level — plan or elevation — or ``Z = 0`` when no
        level is set, which is where a 2D model is drawn from the start.

        Returns ``None`` when the ray is parallel to that plane (a level seen
        edge-on), because then the click has no well-defined point on it.
        """
        try:
            import vtk

            coord = vtk.vtkCoordinate()
            coord.SetCoordinateSystemToDisplay()
            coord.SetValue(float(cx), float(cy), 0.0)
            near = np.asarray(coord.GetComputedWorldValue(self.renderer)[:3], dtype=float)
            coord.SetValue(float(cx), float(cy), 1.0)
            far = np.asarray(coord.GetComputedWorldValue(self.renderer)[:3], dtype=float)
        except Exception:
            return None

        direction = far - near
        if not np.any(np.abs(direction) > 1e-12):
            return None
        if self._working_plane is not None:
            plane, offset = self._working_plane
            axis = {"XY": 2, "XZ": 1, "YZ": 0}[plane]
        else:
            axis, offset = 2, 0.0
        if abs(direction[axis]) < 1e-12:
            return None  # looking along the plane: no single point
        t = (float(offset) - near[axis]) / direction[axis]
        point = near + t * direction
        point[axis] = float(offset)
        return (float(point[0]), float(point[1]), float(point[2]))

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
        return bool(
            mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        )
