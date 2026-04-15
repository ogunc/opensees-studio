"""Main application window.

The MainWindow is the top-level shell: menu bar, toolbars, status bar,
dock layout, and the central 3D viewport. It owns no domain state;
all model interaction is delegated to viewmodels (added in Phase 1).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
)

from opensees_studio import __version__
from opensees_studio.views.canvas3d.model_canvas import ModelCanvas


class MainWindow(QMainWindow):
    """Top-level application shell."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenSees Studio")
        self.resize(1600, 1000)

        self._build_central_canvas()
        self._build_docks()
        self._build_actions()
        self._build_menu_bar()
        self._build_status_bar()

    # ── construction helpers ────────────────────────────────────────────
    def _build_central_canvas(self) -> None:
        self._canvas = ModelCanvas(self)
        self.setCentralWidget(self._canvas)

    def _build_docks(self) -> None:
        # Model tree dock (left)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabel("Model")
        for label in ("Nodes", "Elements", "Materials", "Sections", "Loads", "Analyses"):
            self._tree.addTopLevelItem(QTreeWidgetItem([label]))

        tree_dock = QDockWidget("Model Explorer", self)
        tree_dock.setWidget(self._tree)
        tree_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                                  | Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, tree_dock)

        # Property editor dock (right)
        self._props = QLabel("(no selection)")
        self._props.setAlignment(Qt.AlignmentFlag.AlignCenter)
        props_dock = QDockWidget("Properties", self)
        props_dock.setWidget(self._props)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, props_dock)

        # Console dock (bottom)
        self._console = QPlainTextEdit()
        self._console.setReadOnly(True)
        self._console.setPlaceholderText("OpenSeesPy log output will appear here.")
        console_dock = QDockWidget("Console", self)
        console_dock.setWidget(self._console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, console_dock)

    def _build_actions(self) -> None:
        self._act_new = QAction("&New", self, shortcut=QKeySequence.StandardKey.New)
        self._act_open = QAction("&Open…", self, shortcut=QKeySequence.StandardKey.Open)
        self._act_save = QAction("&Save", self, shortcut=QKeySequence.StandardKey.Save)
        self._act_quit = QAction("&Quit", self, shortcut=QKeySequence.StandardKey.Quit)
        self._act_quit.triggered.connect(self.close)

        self._act_about = QAction("&About OpenSees Studio…", self)
        self._act_about.triggered.connect(self._show_about)

    def _build_menu_bar(self) -> None:
        mb = self.menuBar()

        m_file = mb.addMenu("&File")
        m_file.addActions([self._act_new, self._act_open, self._act_save])
        m_file.addSeparator()
        m_file.addAction(self._act_quit)

        # Stubs for the SAP-style command surface — to be populated per-phase.
        for name in ("&Edit", "&View", "&Define", "&Assign", "&Analyze", "&Display"):
            mb.addMenu(name)

        m_help = mb.addMenu("&Help")
        m_help.addAction(self._act_about)

    def _build_status_bar(self) -> None:
        self.statusBar().showMessage("Ready")

    # ── slots ───────────────────────────────────────────────────────────
    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About OpenSees Studio",
            f"<h3>OpenSees Studio {__version__}</h3>"
            "<p>A modern desktop GUI for OpenSeesPy.</p>"
            "<p>MIT License.</p>",
        )
