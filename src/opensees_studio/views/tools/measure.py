"""MeasureDistanceTool — click two nodes and copy the distance between them.

The measurement is read-only: it creates no command and no undo step. The
straight-line distance is taken from the nodes' stored coordinates (the X-Z
plane for a 2D model, as everywhere else), formatted without trailing zeros
and put on the clipboard so it can be pasted into a dialog or a spreadsheet.

The tool can also feed a dialog: :meth:`measure_for` names a target and takes a
listener (the Move or Replicate window), so each two-joint measurement fills
that window's dX, dY and dZ with the vector between the joints.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication

from opensees_studio.core.units import labels_for
from opensees_studio.views.tools.base import CanvasTool

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

    from opensees_studio.viewmodels import ProjectViewModel
    from opensees_studio.views.canvas3d import ModelCanvas


@dataclass(frozen=True)
class Measurement:
    """Two joints and the vector between them, in the project's length unit."""

    first_node: int
    second_node: int
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    delta: tuple[float, float, float]
    distance: float


class MeasureDistanceTool(CanvasTool):
    """Click the first node, then the second; the distance goes to the clipboard."""

    name = "Measure Distance"
    consumes_picks = True
    measurementFinished = Signal(object)  # Measurement

    def __init__(
        self,
        canvas: ModelCanvas,
        vm: ProjectViewModel,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(canvas, vm, parent)
        self._first: int | None = None
        self._target: str | None = None
        self._listener: Callable[[Measurement], None] | None = None

    # ── lifecycle ───────────────────────────────────────────────────
    def reset(self) -> None:
        self._first = None

    def measure_for(self, target: str, listener: Callable[[Measurement], None]) -> None:
        """Send each measurement to ``listener``, naming ``target`` in the prompts."""
        self._target = target
        self._listener = listener

    def stop_measuring_for(self) -> None:
        """Back to a plain measurement: the distance goes to the clipboard only."""
        self._target = None
        self._listener = None

    def _heading(self) -> str:
        return f"Measure for {self._target}" if self._target else "Measure Distance"

    def prompt(self) -> str:
        if self._first is None:
            return f"{self._heading()}: click the first node. Esc cancels; Select finishes."
        return (
            f"{self._heading()}: node {self._first} is the first point; "
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
            self.statusChanged.emit(f"{self._heading()}: node {node_id} is no longer in the model.")
            return

        if self._first is None:
            self._first = node_id
            self._canvas.selection.select_node(node_id)
            self.statusChanged.emit(self.prompt())
            return

        if node_id == self._first:
            self.statusChanged.emit(
                f"{self._heading()}: node {node_id} is already the first point; "
                "click a different node."
            )
            return

        first = next((item for item in project.nodes if item.id == self._first), None)
        self._first = None
        if first is None:
            self.statusChanged.emit(f"{self._heading()}: the first node was removed; start again.")
            return

        start = (float(first.coords[0]), float(first.coords[1]), float(first.coords[2]))
        end = (float(node.coords[0]), float(node.coords[1]), float(node.coords[2]))
        delta = (end[0] - start[0], end[1] - start[1], end[2] - start[2])
        distance = math.dist(start, end)
        measurement = Measurement(
            first_node=first.id,
            second_node=node.id,
            start=start,
            end=end,
            delta=delta,
            distance=distance,
        )
        self.measurementFinished.emit(measurement)
        listener = self._listener
        if listener is not None:
            listener(measurement)

        text = f"{distance:.10g}"
        QGuiApplication.clipboard().setText(text)
        self._canvas.selection.select_node(node_id, additive=True)
        unit = labels_for(project.meta.units).length
        if listener is not None:
            dx, dy, dz = (f"{value:.10g}" for value in delta)
            self.statusChanged.emit(
                f"{self._heading()}: nodes {first.id} and {node.id} are {text} {unit} apart; "
                f"dX={dx}, dY={dy}, dZ={dz} filled the dialog "
                "(distance copied to the clipboard). Click the first node for another measurement."
            )
        else:
            self.statusChanged.emit(
                f"{self._heading()}: nodes {first.id} and {node.id} are {text} {unit} apart "
                "(copied to the clipboard). Click the first node for another measurement."
            )

    def on_element_picked(self, element_id: int) -> None:
        self.statusChanged.emit(
            f"{self._heading()}: click a node (the ends of an element are nodes)."
        )

    def on_empty_clicked(self, x: float, y: float, z: float, snapped: bool = True) -> None:
        self.statusChanged.emit(f"{self._heading()}: click an existing node.")
