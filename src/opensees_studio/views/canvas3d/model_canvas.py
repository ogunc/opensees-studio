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
        if cd is None or "_oss_id" not in cd:
            return
        try:
            entity_id = int(np.asarray(cd["_oss_id"])[0])
            kind = str(np.asarray(cd["_oss_kind"])[0])
        except (KeyError, IndexError, ValueError):
            return

        additive = self._is_additive_modifier()
        if kind == "node":
            if additive:
                self.selection.toggle_node(entity_id)
            else:
                self.selection.select_node(entity_id)
            self.nodePicked.emit(entity_id)
        elif kind == "element":
            if additive:
                self.selection.toggle_element(entity_id)
            else:
                self.selection.select_element(entity_id)
            self.elementPicked.emit(entity_id)
