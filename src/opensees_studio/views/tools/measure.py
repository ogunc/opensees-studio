"""MeasureDistanceTool — click two nodes and copy the distance between them.

The measurement is read-only: it creates no command and no undo step. The
straight-line distance is taken from the nodes' stored coordinates (the X-Z
plane for a 2D model, as everywhere else), formatted without trailing zeros
and put on the clipboard so it can be pasted into a dialog or a spreadsheet.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtGui import QGuiApplication

from opensees_studio.core.units import labels_for
from opensees_studio.views.tools.base import CanvasTool

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

    from opensees_studio.viewmodels import ProjectViewModel
    from opensees_studio.views.canvas3d import ModelCanvas


class MeasureDistanceTool(CanvasTool):
    """Click the first node, then the second; the distance goes to the clipboard."""

    name = "Measure Distance"
    consumes_picks = True

    def __init__(
        self,
        canvas: ModelCanvas,
        vm: ProjectViewModel,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(canvas, vm, parent)
        self._first: int | None = None

    # ── lifecycle ───────────────────────────────────────────────────
    def reset(self) -> None:
        self._first = None

    def prompt(self) -> str:
        if self._first is None:
            return "Measure Distance: click the first node. Esc cancels; Select finishes."
        return (
            f"Measure Distance: node {self._first} is the first point; "
            "click the second node. Esc cancels; Select finishes."
        )

    # ── picks ───────────────────────────────────────────────────────
    def on_node_picked(self, node_id: int) -> None:
        project = self._vm.project
        if project is None:
            return
        node = next((item for item in project.nodes if item.id == node_id), None)
        if node is None:
            self._first = None
            self.statusChanged.emit(f"Measure Distance: node {node_id} is no longer in the model.")
            return

        if self._first is None:
            self._first = node_id
            self._canvas.selection.select_node(node_id)
            self.statusChanged.emit(self.prompt())
            return

        if node_id == self._first:
            self.statusChanged.emit(
                f"Measure Distance: node {node_id} is already the first point; "
                "click a different node."
            )
            return

        first = next((item for item in project.nodes if item.id == self._first), None)
        self._first = None
        if first is None:
            self.statusChanged.emit("Measure Distance: the first node was removed; start again.")
            return

        distance = math.dist(first.coords, node.coords)
        text = f"{distance:.10g}"
        QGuiApplication.clipboard().setText(text)
        self._canvas.selection.select_node(node_id, additive=True)
        unit = labels_for(project.meta.units).length
        self.statusChanged.emit(
            f"Measure Distance: nodes {first.id} and {node.id} are {text} {unit} apart "
            "(copied to the clipboard). Click the first node for another measurement."
        )

    def on_element_picked(self, element_id: int) -> None:
        self.statusChanged.emit(
            "Measure Distance: click a node (the ends of an element are nodes)."
        )

    def on_empty_clicked(self, x: float, y: float, z: float, snapped: bool = True) -> None:
        self.statusChanged.emit("Measure Distance: click an existing node.")
