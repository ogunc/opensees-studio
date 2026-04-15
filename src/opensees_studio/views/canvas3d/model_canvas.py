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

from typing import Any

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget
from pyvistaqt import QtInteractor

from opensees_studio.core import Project
from opensees_studio.views.canvas3d.model_renderer import ModelRenderer
from opensees_studio.views.canvas3d.selection import SelectionState
from opensees_studio.views.canvas3d.style import RenderStyle


class ModelCanvas(QtInteractor):  # type: ignore[misc]
    """The central 3D viewport widget."""

    # Convenience signals re-emitted from SelectionState.
    nodePicked = Signal(int)
    elementPicked = Signal(int)

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
        self._enable_picking()

        # Re-render on selection change so highlighting updates.
        self.selection.selectionChanged.connect(self._renderer.update_selection)

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
        self.set_background(self._style.background_bottom, top=self._style.background_top)
        self.show_axes()
        self.show_grid(color="gray", xtitle="X", ytitle="Y", ztitle="Z")
        self.view_isometric()

    def _enable_picking(self) -> None:
        """Hook left-click picking using screen-space distance.

        We bypass VTK pickers entirely. Pickers fail in our scene because
        glyph meshes overflow vtkHardwareSelector's prop limit. Instead:
          1) Capture left-click viewport coords via track_click_position.
          2) Project every source node into screen space using the
             current camera/renderer.
          3) Pick the node whose screen projection is closest to the
             click — within a generous pixel threshold.
          4) For frames, project each frame midpoint the same way.

        This is O(N) per click which is fine for tens of thousands of
        nodes. No GPU read-back, no shader, no hardware selector.
        """
        self.track_click_position(callback=self._on_left_click, side="left")

    def _on_left_click(self, click_xy) -> None:  # type: ignore[no-untyped-def]
        """User left-clicked at viewport position ``click_xy = (x, y)``."""
        cx, cy = float(click_xy[0]), float(click_xy[1])
        renderer = self.renderer

        # ── Try nodes first (smaller targets, deserve priority). ─────────
        node_pd = self._renderer._node_pd
        node_ids = self._renderer._node_ids_ordered
        if node_pd is not None and node_ids:
            node_screen = self._project_world_to_screen(
                np.asarray(node_pd.points), renderer
            )
            if node_screen is not None:
                d2 = (node_screen[:, 0] - cx) ** 2 + (node_screen[:, 1] - cy) ** 2
                idx = int(np.argmin(d2))
                # 18 px tolerance — comfortable for 8 px diameter glyph spheres.
                if d2[idx] <= 18.0 ** 2:
                    self._dispatch_pick("node", int(node_ids[idx]))
                    return

        # ── Otherwise try frames. ────────────────────────────────────────
        frame_pd = self._renderer._frame_pd
        frame_ids = self._renderer._frame_ids_ordered
        if frame_pd is not None and frame_ids:
            pts = np.asarray(frame_pd.points)
            lines = np.asarray(frame_pd.lines).reshape(-1, 3)
            midpoints = (pts[lines[:, 1]] + pts[lines[:, 2]]) * 0.5
            mid_screen = self._project_world_to_screen(midpoints, renderer)
            if mid_screen is not None:
                d2 = (mid_screen[:, 0] - cx) ** 2 + (mid_screen[:, 1] - cy) ** 2
                idx = int(np.argmin(d2))
                # 12 px — frames are 4 px lines, click can be on the line itself.
                if d2[idx] <= 12.0 ** 2:
                    self._dispatch_pick("element", int(frame_ids[idx]))
                    return

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

    def _nearest_node_to_point(self, pick_point: np.ndarray) -> int | None:
        node_pd = self._renderer._node_pd
        ids = self._renderer._node_ids_ordered
        if node_pd is None or not ids:
            return None
        pts = np.asarray(node_pd.points)
        diffs = pts - pick_point
        dists = np.einsum("ij,ij->i", diffs, diffs)
        return int(ids[int(np.argmin(dists))])

    def _nearest_frame_to_point(self, pick_point: np.ndarray) -> int | None:
        frame_pd = self._renderer._frame_pd
        ids = self._renderer._frame_ids_ordered
        if frame_pd is None or not ids:
            return None
        # For each frame line cell, compute the midpoint and find closest.
        pts = np.asarray(frame_pd.points)
        # frame_pd.lines is [2, i0, j0, 2, i1, j1, ...]
        lines = np.asarray(frame_pd.lines).reshape(-1, 3)   # [[2, i, j], ...]
        midpoints = (pts[lines[:, 1]] + pts[lines[:, 2]]) * 0.5
        diffs = midpoints - pick_point
        dists = np.einsum("ij,ij->i", diffs, diffs)
        return int(ids[int(np.argmin(dists))])

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
        """True if Ctrl or Shift was held during the most recent VTK event.

        VTK exposes modifier state on its interactor; PyVista's pick
        callback doesn't surface the original Qt event, so we read VTK
        directly. ``self.interactor`` is the underlying
        ``vtkRenderWindowInteractor``.
        """
        try:
            iren = self.interactor
            return bool(iren.GetControlKey() or iren.GetShiftKey())
        except AttributeError:
            return False
