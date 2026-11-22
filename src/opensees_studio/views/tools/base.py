"""Canvas tool framework — modal interactions that intercept picks.

A :class:`CanvasTool` is a "mode" the user enters (e.g. "Draw Frame")
that intercepts canvas pick events. Only one tool is active at a
time; switching tools deactivates the previous one.

The :class:`ToolController` plugs into a :class:`ModelCanvas`. When a
non-default tool is active, the controller suppresses the canvas's
default pick→selection behavior so the tool can interpret picks its
own way.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel
    from opensees_studio.views.canvas3d import ModelCanvas


class CanvasTool(QObject):
    """Base class for canvas interaction tools."""

    statusChanged = Signal(str)
    finished = Signal()  # the tool wants to deactivate itself

    #: Display name used in the toolbar.
    name: str = "tool"
    #: If True, the canvas suppresses its automatic pick→selection update
    #: while this tool is active.
    consumes_picks: bool = True
    #: If True, the canvas highlights the joint under the pointer (node OSNAP).
    wants_node_snap: bool = False
    #: If True, the tool shows a dashed preview of the element the next click
    #: would create (:meth:`preview_points`), following the snapped point.
    draws_preview: bool = False
    #: Whether that preview closes back on its first point (a shell outline).
    preview_closed: bool = False

    def __init__(
        self,
        canvas: ModelCanvas,
        vm: ProjectViewModel,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._vm = vm
        self._active = False
        self._preview_connected = False
        #: The snapped point under the pointer, as the canvas last reported it.
        self._cursor_point: tuple[float, float, float] | None = None
        self._preview_shown = False

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def canvas(self) -> ModelCanvas:
        """The viewport this tool was created for."""
        return self._canvas

    # ── lifecycle (override only if needed) ─────────────────────────
    def activate(self) -> None:
        self._active = True
        if self.draws_preview:
            self._connect_preview()
        self.statusChanged.emit(self.prompt())

    def deactivate(self) -> None:
        self._active = False
        self._disconnect_preview()
        self.reset()
        self._clear_draw_preview()

    def reset(self) -> None:
        """Wipe any in-progress state; called on Esc and on deactivate."""
        pass

    def prompt(self) -> str:
        """Status-bar text shown when the tool is active."""
        return f"{self.name}: ready."

    def _set_snap_reference_to_node(self, node_id: int | None) -> None:
        """Tell the canvas which point perpendicular snaps are measured from.

        Two-click tools call this with the first endpoint and with ``None``
        when the gesture ends, so the perpendicular OSNAP has a reference.
        """
        project = self._vm.project
        node = None
        if node_id is not None and project is not None:
            node = next((item for item in project.nodes if item.id == node_id), None)
        self._canvas.set_snap_reference(
            None
            if node is None
            else (float(node.coords[0]), float(node.coords[1]), float(node.coords[2]))
        )

    # ── dashed preview of the next element ──────────────────────────
    #: Snap kinds a click resolves to a point the draw tools accept: a joint,
    #: a grid crossing, a member snap, or the working plane.
    PREVIEW_SNAP_KINDS = frozenset(
        {"node", "grid", "midpoint", "perpendicular", "on_element", "plane"}
    )

    def preview_points(self) -> list[tuple[float, float, float]]:
        """The points already placed for the element being drawn (override).

        The preview runs from them to the point under the pointer. An empty
        list means there is nothing to preview yet.
        """
        return []

    def _node_point(self, node_id: int) -> tuple[float, float, float] | None:
        project = self._vm.project
        if project is None:
            return None
        node = next((item for item in project.nodes if item.id == node_id), None)
        if node is None:
            return None
        return (float(node.coords[0]), float(node.coords[1]), float(node.coords[2]))

    def _connect_preview(self) -> None:
        signal = getattr(self._canvas, "cursorMoved", None)
        if signal is None:
            return  # a canvas without hover reporting (test stubs)
        if self._preview_connected:
            with contextlib.suppress(RuntimeError, TypeError):
                signal.disconnect(self._on_preview_cursor)
        signal.connect(self._on_preview_cursor)
        self._preview_connected = True

    def _disconnect_preview(self) -> None:
        if not self._preview_connected:
            return
        signal = getattr(self._canvas, "cursorMoved", None)
        if signal is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                signal.disconnect(self._on_preview_cursor)
        self._preview_connected = False
        self._cursor_point = None

    def _on_preview_cursor(self, payload: object) -> None:
        """Follow the snapped point under the pointer with the dashed preview."""
        if (
            isinstance(payload, tuple)
            and len(payload) >= 4
            and payload[3] in self.PREVIEW_SNAP_KINDS
        ):
            x, y, z = (float(payload[0]), float(payload[1]), float(payload[2]))
            project = self._vm.project
            if project is not None and project.ndm == 2:
                y = 0.0  # where the click puts the node (core.plane)
            self._cursor_point = (x, y, z)
        else:
            self._cursor_point = None
        self._refresh_draw_preview()

    def _refresh_draw_preview(self) -> None:
        """Redraw the preview from the placed points and the last pointer point."""
        if not (self.draws_preview and self._active):
            return
        placed = self.preview_points()
        if not placed or self._cursor_point is None:
            self._clear_draw_preview()
            return
        setter = getattr(self._canvas, "set_draw_preview", None)
        if setter is None:
            return
        setter([*placed, self._cursor_point], closed=self.preview_closed)
        self._preview_shown = True

    def _clear_draw_preview(self) -> None:
        if not self._preview_shown:
            return
        self._preview_shown = False
        clear = getattr(self._canvas, "clear_draw_preview", None)
        if clear is not None:
            clear()

    def grid_hint(self) -> str:
        """A sentence for the prompt when there is no grid to snap to.

        A project with an empty grid (the default) still draws — the canvas
        resolves a click onto the working plane — but it does not *snap*, and
        the difference should be visible rather than discovered.
        """
        project = self._vm.project
        if project is None:
            return ""
        has_lines = any(system.grid.shown for system in project.coord_systems)
        if has_lines:
            return ""
        return " No grid defined: clicks land on the working plane (Define → Grids… snaps)."

    # ── hooks (override) ────────────────────────────────────────────
    def on_node_picked(self, node_id: int) -> None: ...
    def on_element_picked(self, element_id: int) -> None: ...
    def on_empty_clicked(self, x: float, y: float, z: float, snapped: bool = True) -> None:
        """Empty-space click at a world point.

        ``snapped`` is True when the point is a grid intersection, False when it
        is where the click met the working plane (no intersection was close
        enough). Tools may say which, so the user learns the difference.
        """


class SelectTool(CanvasTool):
    """The default tool. Does nothing — canvas handles selection itself."""

    name = "Select"
    consumes_picks = False

    def prompt(self) -> str:
        return "Select: click to pick. Ctrl/Shift = additive."


class ToolController(QObject):
    """Owns the active tool and routes canvas pick signals to it."""

    toolChanged = Signal(object)  # emits the new CanvasTool (or None for default)

    def __init__(
        self, canvas: ModelCanvas, vm: ProjectViewModel, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._vm = vm
        self._active: CanvasTool | None = None
        self._connect(canvas)

    def _connect(self, canvas: ModelCanvas) -> None:
        """Always-on signal hookups: canvas → controller → active tool."""
        canvas.nodePicked.connect(self._on_node_picked)
        canvas.elementPicked.connect(self._on_element_picked)
        canvas.emptyClicked.connect(self._on_empty_clicked)
        # A drag while a tool is armed places nothing; say so, because silence
        # is exactly what made the drawing tools feel broken.
        canvas.dragNotAClick.connect(self._on_drag_not_a_click)

    def set_canvas(self, canvas: ModelCanvas) -> None:
        """Follow the window the user is working in.

        The main window has one controller but several viewports (View → New
        View). A tool created for the newly focused canvas must receive that
        canvas's picks, so the old signal hookups are dropped first and any
        armed tool is returned to Select.
        """
        if canvas is self._canvas:
            return
        if self._active is not None:
            self.set_active(None)
        for signal, slot in (
            (self._canvas.nodePicked, self._on_node_picked),
            (self._canvas.elementPicked, self._on_element_picked),
            (self._canvas.emptyClicked, self._on_empty_clicked),
            (self._canvas.dragNotAClick, self._on_drag_not_a_click),
        ):
            with contextlib.suppress(RuntimeError, TypeError):
                signal.disconnect(slot)
        self._canvas = canvas
        self._connect(canvas)

    @property
    def active(self) -> CanvasTool | None:
        return self._active

    def set_active(self, tool: CanvasTool | None) -> None:
        if self._active is not None:
            self._active.deactivate()
        self._active = tool
        # Tell the canvas whether to do its default pick→select behavior.
        suppress = tool is not None and tool.consumes_picks
        self._canvas.set_default_selection_enabled(not suppress)
        # Tool-specific hover feedback: Measure highlights the joint a click
        # would pick; the other tools keep the grid/member preview only.
        self._canvas.set_node_snap_preview_enabled(tool is not None and tool.wants_node_snap)
        # Quick draw reads the bare point on the working plane before any snap.
        self._canvas.plane_click_handler = getattr(tool, "on_plane_point", None)
        if tool is not None:
            tool.activate()
        self.toolChanged.emit(tool)

    def cancel(self) -> None:
        """Reset the active tool's in-progress state without deactivating it."""
        if self._active is not None:
            self._active.reset()
            self._active.statusChanged.emit(self._active.prompt())

    def _on_node_picked(self, node_id: int) -> None:
        if self._active is not None:
            self._active.on_node_picked(node_id)

    def _on_element_picked(self, element_id: int) -> None:
        if self._active is not None:
            self._active.on_element_picked(element_id)

    def _on_drag_not_a_click(self) -> None:
        if self._active is None:
            return
        self._active.statusChanged.emit(
            f"{self._active.name}: that was a drag (the view moved), so nothing was "
            "placed. Click without moving the pointer.",
        )

    def _on_empty_clicked(self, x: float, y: float, z: float, snapped: bool) -> None:
        if self._active is not None:
            self._active.on_empty_clicked(x, y, z, snapped)
