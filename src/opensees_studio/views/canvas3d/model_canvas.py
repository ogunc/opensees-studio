"""3D model viewport, backed by PyVista (VTK).

This is the central widget of the application. In Phase 0 it shows only
the world axes and a reference grid; in Phase 3 it gains node/element
glyphs, picking, and selection highlighting.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from pyvistaqt import QtInteractor


class ModelCanvas(QtInteractor):  # type: ignore[misc]
    """PyVista QtInteractor configured as the model canvas.

    Subclassing keeps room to attach signals (``nodePicked``, ``elementPicked``)
    in later phases without changing the embedding code.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_scene()

    def _setup_scene(self) -> None:
        """Add the persistent scene furniture: axes, grid, background."""
        self.set_background("white", top="lightsteelblue")
        self.show_axes()
        self.show_grid(
            color="gray",
            xtitle="X",
            ytitle="Y",
            ztitle="Z",
        )
        # A neutral starting view; will be replaced by view-cube control later.
        self.view_isometric()
