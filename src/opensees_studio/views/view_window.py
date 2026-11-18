"""Secondary 3D view windows.

Each window is an independent viewport on the *same* project: it owns its
``ModelCanvas`` (so its own colours, visibility toggles and camera) but shares
the ``SelectionState`` with the main window, which is what makes a selection
highlight everywhere at once.

Drawing stays in the main window; these windows are for looking at the model
from several angles at the same time.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QCloseEvent, QMouseEvent
from PySide6.QtWidgets import QMainWindow, QToolBar

from opensees_studio.core import Project
from opensees_studio.core.view_settings import ViewSettings
from opensees_studio.views.canvas3d.model_canvas import ModelCanvas
from opensees_studio.views.canvas3d.selection import SelectionState


class ViewWindow(QMainWindow):
    """A floating viewport on the shared project and selection."""

    #: Emitted when this window becomes the one the menu acts on.
    activated = Signal(object)
    #: Emitted when the user closes it, so the owner can forget it.
    closed = Signal(object)

    def __init__(
        self,
        selection: SelectionState,
        settings: ViewSettings | None = None,
        parent: QMainWindow | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.canvas = ModelCanvas(self, selection=selection)
        if settings is not None:
            self.canvas.set_view_settings(settings)
        self.setCentralWidget(self.canvas)
        self.setWindowTitle("OpenSees Studio — View")
        self.resize(900, 640)
        self._build_toolbar()

    # ── construction ────────────────────────────────────────────────
    def _build_toolbar(self) -> None:
        bar = QToolBar("View", self)
        bar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        for label, slot in (
            ("Iso", self.canvas.view_isometric),
            ("Top", self.canvas.view_xy),
            ("Front", self.canvas.view_xz),
            ("Right", self.canvas.view_yz),
            ("Extents", self.canvas.reframe),
            ("Zoom +", self.canvas.zoom_in),
            ("Zoom -", self.canvas.zoom_out),
        ):
            action = bar.addAction(label)
            # Lambdas so the ``bool`` a QAction emits is not passed on to a
            # zero-argument canvas method.
            action.triggered.connect(lambda _checked=False, fn=slot: fn())

    # ── project plumbing ────────────────────────────────────────────
    def show_project(self, project: Project | None) -> None:
        """Render ``project`` and frame the camera (used when the window opens)."""
        self.canvas.show_project(project)

    def refresh(self, project: Project | None) -> None:
        """Re-render after a model edit, keeping the camera where the user left it."""
        self.canvas.refresh(project)

    # ── activation / closing ────────────────────────────────────────
    def event(self, event: QEvent) -> bool:
        """Report activation so the main window's View menu targets this canvas."""
        if event.type() == QEvent.Type.WindowActivate:
            self.activated.emit(self)
        return super().event(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.activated.emit(self)
        super().mousePressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closed.emit(self)
        super().closeEvent(event)
