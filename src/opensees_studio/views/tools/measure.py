"""MeasureDistanceTool — pick two points and copy the 3D distance between them.

A point is an existing joint or a snapped point: a grid intersection, or a
member snap (midpoint, perpendicular, on member) when its OSNAP is on. The
measurement is read-only: it creates no command and no undo step. The
straight-line distance is taken from all three coordinates, formatted without
trailing zeros and put on the clipboard so it can be pasted into a dialog or a
spreadsheet.

The tool can also feed a dialog: :meth:`measure_for` names a target and takes a
listener (the Move or Replicate window), so each two-point measurement fills
that window's dX, dY and dZ with the vector between the points.
"""

from __future__ import annotations

import contextlib
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


#: Hover snap kinds that resolve to a point Measure can use. ``plane`` is the
#: bare working-plane hit, with no grid or member reference, and is refused.
MEASURABLE_SNAP_KINDS = frozenset({"node", "grid", "midpoint", "perpendicular", "on_element"})


@dataclass(frozen=True)
class Measurement:
    """The two measured points and the vector between them.

    ``first_node`` and ``second_node`` are set when that point was a joint and
    ``None`` when it came from a grid intersection or a member snap.
    """

    first_node: int | None
    second_node: int | None
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    delta: tuple[float, float, float]
    distance: float


class MeasureDistanceTool(CanvasTool):
    """Click two points; the distance goes to the clipboard."""

    name = "Measure Distance"
    consumes_picks = True
    wants_node_snap = True
    measurementFinished = Signal(object)  # Measurement

    def __init__(
        self,
        canvas: ModelCanvas,
        vm: ProjectViewModel,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(canvas, vm, parent)
        self._first: tuple[float, float, float] | None = None
        self._first_node: int | None = None
        self._last_guide: tuple[float, float, float] | None = None
        self._target: str | None = None
        self._listener: Callable[[Measurement], None] | None = None
        self._cursor_connected = False

    # ── lifecycle ───────────────────────────────────────────────────
    def activate(self) -> None:
        # Node OSNAP and the snap preview are what make the points read as
        # targets: the joint or grid point under the pointer turns yellow
        # before the click.
        self._canvas.set_snap_preview_enabled(True)
        if self._cursor_connected:
            with contextlib.suppress(RuntimeError, TypeError):
                self._canvas.cursorMoved.disconnect(self._on_cursor_moved)
        self._canvas.cursorMoved.connect(self._on_cursor_moved)
        self._cursor_connected = True
        super().activate()

    def deactivate(self) -> None:
        if self._cursor_connected:
            with contextlib.suppress(RuntimeError, TypeError):
                self._canvas.cursorMoved.disconnect(self._on_cursor_moved)
            self._cursor_connected = False
        self._canvas.set_snap_preview_enabled(False)
        super().deactivate()

    def reset(self) -> None:
        self._first = None
        self._first_node = None
        self._last_guide = None
        self._canvas.clear_measure_preview()

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
            return (
                f"{self._heading()}: click the first point (a joint or a snapped "
                "grid/member point). Esc cancels; Select finishes."
            )
        if self._first_node is not None:
            first = f"node {self._first_node} is the first point"
        else:
            first = "the first point is set"
        return f"{self._heading()}: {first}; click the second point. Esc cancels; Select finishes."

    @staticmethod
    def _pair_label(first_node: int | None, second_node: int | None) -> str:
        if first_node is not None and second_node is not None:
            return f"nodes {first_node} and {second_node}"
        if first_node is not None:
            return f"node {first_node} and the snapped point"
        if second_node is not None:
            return f"the snapped point and node {second_node}"
        return "the two snapped points"

    def _on_cursor_moved(self, payload: object) -> None:
        """Preview the dashed guide from the first point to the point under the pointer."""
        if self._first is None:
            return
        project = self._vm.project
        if project is None:
            return
        if not (
            isinstance(payload, tuple) and len(payload) >= 4 and payload[3] in MEASURABLE_SNAP_KINDS
        ):
            self._clear_guide()
            return
        target = (float(payload[0]), float(payload[1]), float(payload[2]))
        start = self._first
        if math.dist(start, target) <= 1e-12:
            self._clear_guide()
            return
        if target == self._last_guide:
            return
        distance = math.dist(start, target)
        unit = labels_for(project.meta.units).length
        self._canvas.set_measure_guide(start, target, f"{distance:.10g} {unit}")
        self._last_guide = target

    def _clear_guide(self) -> None:
        if self._last_guide is None:
            return
        self._last_guide = None
        self._canvas.clear_measure_guide()

    # ── picks ───────────────────────────────────────────────────────
    def on_node_picked(self, node_id: int) -> None:
        project = self._vm.project
        if project is None:
            return
        node = next((item for item in project.nodes if item.id == node_id), None)
        if node is None:
            self._first = None
            self._first_node = None
            self._last_guide = None
            self._canvas.clear_measure_preview()
            self.statusChanged.emit(f"{self._heading()}: node {node_id} is no longer in the model.")
            return
        point = (float(node.coords[0]), float(node.coords[1]), float(node.coords[2]))
        self._pick_point(point, node_id)

    def on_element_picked(self, element_id: int) -> None:
        self.statusChanged.emit(
            f"{self._heading()}: click a joint or a snapped grid/member point "
            "(the ends of an element are nodes)."
        )

    def on_empty_clicked(self, x: float, y: float, z: float, snapped: bool = True) -> None:
        if not snapped:
            self.statusChanged.emit(
                f"{self._heading()}: click a joint or a grid intersection "
                "(define a grid to snap to one)."
            )
            return
        self._pick_point((float(x), float(y), float(z)), None)

    def _pick_point(self, point: tuple[float, float, float], node_id: int | None) -> None:
        project = self._vm.project
        if project is None:
            return
        if self._first is None:
            self._first = point
            self._first_node = node_id
            self._last_guide = None
            if node_id is not None:
                self._canvas.selection.select_node(node_id)
            self._canvas.set_measure_anchor(point)
            self.statusChanged.emit(self.prompt())
            return

        if node_id == self._first_node and math.dist(self._first, point) <= 1e-12:
            self.statusChanged.emit(
                f"{self._heading()}: that is already the first point; click a different point."
            )
            return

        start = self._first
        first_node = self._first_node
        self._first = None
        self._first_node = None
        self._last_guide = None
        self._canvas.clear_measure_preview()

        delta = (point[0] - start[0], point[1] - start[1], point[2] - start[2])
        distance = math.dist(start, point)
        measurement = Measurement(
            first_node=first_node,
            second_node=node_id,
            start=start,
            end=point,
            delta=delta,
            distance=distance,
        )
        self.measurementFinished.emit(measurement)
        listener = self._listener
        if listener is not None:
            listener(measurement)

        text = f"{distance:.10g}"
        QGuiApplication.clipboard().setText(text)
        if node_id is not None:
            self._canvas.selection.select_node(node_id, additive=True)
        unit = labels_for(project.meta.units).length
        dx, dy, dz = (f"{value:.10g}" for value in delta)
        pair = self._pair_label(first_node, node_id)
        if listener is not None:
            self.statusChanged.emit(
                f"{self._heading()}: {pair} are {text} {unit} apart; "
                f"dX={dx}, dY={dy}, dZ={dz} filled the dialog "
                "(distance copied to the clipboard). Click the first point for another measurement."
            )
        else:
            self.statusChanged.emit(
                f"{self._heading()}: {pair} are {text} {unit} apart "
                f"(dX={dx}, dY={dy}, dZ={dz}; copied to the clipboard). "
                "Click the first point for another measurement."
            )
