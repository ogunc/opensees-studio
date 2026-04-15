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
        """Hook left-click picking using track_click_position + manual VTK picker.

        Why not enable_mesh_picking? Two reasons:
        1) The PyVista API ate the picker reference in some versions.
        2) Glyph-filter polydata has metadata in point_data, not cell_data,
           which the built-in picking flow handles inconsistently.

        Instead we listen to raw left-clicks (in viewport coords), run a
        :vtk:`vtkPropPicker`, then walk our own polydata to find the
        nearest source entity.
        """
        import vtk
        self._picker = vtk.vtkPropPicker()
        self.track_click_position(callback=self._on_left_click, side="left")

    def _on_left_click(self, click_xy) -> None:  # type: ignore[no-untyped-def]
        """User left-clicked at viewport position ``click_xy = (x, y)``."""
        x, y = int(click_xy[0]), int(click_xy[1])
        renderer = self.renderer
        ok = self._picker.Pick(x, y, 0, renderer)
        if not ok:
            return
        actor = self._picker.GetActor()
        if actor is None:
            return
        pos = self._picker.GetPickPosition()
        if pos is None or not any(pos):
            return
        pick_point = np.asarray(pos, dtype=float)

        # Match the actor against our renderer's frame and node actors.
        if actor is self._renderer._node_actor:
            entity_id = self._nearest_node_to_point(pick_point)
            if entity_id is not None:
                self._dispatch_pick("node", entity_id)
        elif actor is self._renderer._frame_actor:
            entity_id = self._nearest_frame_to_point(pick_point)
            if entity_id is not None:
                self._dispatch_pick("element", entity_id)
        # else: support glyph, load, axes, etc. — ignore

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
