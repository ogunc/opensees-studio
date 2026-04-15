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
        """Hook left-click picking; dispatch to selection state by tag kind."""
        self.enable_mesh_picking(
            callback=self._on_mesh_picked,
            show_message=False,
            show=False,
            left_clicking=True,
        )

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

    def _on_mesh_picked(self, mesh: Any) -> None:
        # Ignore untagged meshes (support glyphs, loads, etc. are non-pickable
        # but be defensive). We never auto-clear the selection on a "miss"
        # because PyVista doesn't signal misses reliably across versions.
        if mesh is None:
            return
        cd = getattr(mesh, "cell_data", None)
        pd = getattr(mesh, "point_data", None)

        # ── Frame elements: cell_data carries one _oss_id per line cell. ──
        # We can use the picker's pick position to identify which cell.
        if cd is not None and "_oss_id" in cd:
            entity_id, kind = self._pick_from_cell_data(mesh, cd)
            if entity_id is not None:
                self._dispatch_pick(kind, entity_id)
            return

        # ── Node glyphs: point_data has _oss_id but the pick gives us the ──
        # whole glyph mesh. Use the picker's 3D position to find the
        # nearest source node, not the first one in the array.
        if pd is not None and "_oss_id" in pd:
            entity_id = self._nearest_node_to_pick()
            if entity_id is not None:
                self._dispatch_pick("node", entity_id)
            return

    def _pick_from_cell_data(self, mesh: Any, cd: Any) -> tuple[int | None, str | None]:
        """Frame pick: pick position → nearest line cell → its _oss_id."""
        try:
            ids = np.asarray(cd["_oss_id"])
            kinds = np.asarray(cd["_oss_kind"])
            if len(ids) == 0:
                return None, None
            pos = self._picked_pick_position()
            if pos is None:
                # Fall back to first cell.
                return int(ids[0]), str(kinds[0])
            # Compute the centroid of each cell and find the closest one.
            best_idx, best_dist = 0, float("inf")
            for i in range(mesh.n_cells):
                cell = mesh.get_cell(i)
                centroid = np.asarray(cell.points).mean(axis=0)
                d = float(np.linalg.norm(centroid - pos))
                if d < best_dist:
                    best_dist = d
                    best_idx = i
            return int(ids[best_idx]), str(kinds[best_idx])
        except (KeyError, IndexError, ValueError, AttributeError):
            return None, None

    def _nearest_node_to_pick(self) -> int | None:
        """Node pick: pick position → nearest source node id."""
        pos = self._picked_pick_position()
        if pos is None:
            return None
        # Walk the renderer's source node polydata for the closest point.
        node_pd = self._renderer._node_pd
        ids = self._renderer._node_ids_ordered
        if node_pd is None or not ids:
            return None
        pts = np.asarray(node_pd.points)
        diffs = pts - pos
        dists = np.einsum("ij,ij->i", diffs, diffs)
        return int(ids[int(np.argmin(dists))])

    def _picked_pick_position(self) -> np.ndarray | None:
        """The 3D world position the user clicked, from VTK's picker."""
        try:
            picker = self.iren.get_picker() if hasattr(self, "iren") else None
            if picker is None:
                # PyVista stores the picker as `picker` on the plotter.
                picker = getattr(self, "picker", None)
            if picker is None:
                return None
            pos = picker.GetPickPosition()
            if pos is None:
                return None
            return np.asarray(pos, dtype=float)
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
