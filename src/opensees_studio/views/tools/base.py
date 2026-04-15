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

    def __init__(
        self,
        canvas: "ModelCanvas",
        vm: "ProjectViewModel",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._vm = vm
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    # ── lifecycle (override only if needed) ─────────────────────────
    def activate(self) -> None:
        self._active = True
        self.statusChanged.emit(self.prompt())

    def deactivate(self) -> None:
        self._active = False
        self.reset()

    def reset(self) -> None:
        """Wipe any in-progress state; called on Esc and on deactivate."""
        pass

    def prompt(self) -> str:
        """Status-bar text shown when the tool is active."""
        return f"{self.name}: ready."

    # ── hooks (override) ────────────────────────────────────────────
    def on_node_picked(self, node_id: int) -> None: ...
    def on_element_picked(self, element_id: int) -> None: ...


class SelectTool(CanvasTool):
    """The default tool. Does nothing — canvas handles selection itself."""

    name = "Select"
    consumes_picks = False

    def prompt(self) -> str:
        return "Select: click to pick. Ctrl/Shift = additive."


class ToolController(QObject):
    """Owns the active tool and routes canvas pick signals to it."""

    toolChanged = Signal(object)   # emits the new CanvasTool (or None for default)

    def __init__(self, canvas: "ModelCanvas", vm: "ProjectViewModel",
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._vm = vm
        self._active: CanvasTool | None = None

        # Always-on signal hookups: canvas → controller → active tool
        self._canvas.nodePicked.connect(self._on_node_picked)
        self._canvas.elementPicked.connect(self._on_element_picked)

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
