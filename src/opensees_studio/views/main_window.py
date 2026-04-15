"""Main application window — Phase 3 integration.

Wires together:
- ProjectViewModel (current project + dirty state)
- ModelCanvas (3D viewport with picking and selection)
- File actions (New, Open .osmodel, Save, Save As)
- View toolbar (Top / Front / Right / Iso / Zoom-Extents / Ortho-Persp)
- Properties dock that reflects the current selection
- Status bar that reflects project state
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
)

from opensees_studio import __version__
from opensees_studio.core import Project
from opensees_studio.services import PROJECT_FILE_SUFFIX
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.canvas3d import ModelCanvas


class MainWindow(QMainWindow):
    """Top-level application shell."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenSees Studio")
        self.resize(1600, 1000)

        self._vm = ProjectViewModel(self)

        self._build_central_canvas()
        self._build_docks()
        self._build_actions()
        self._build_menu_bar()
        self._build_view_toolbar()
        self._build_status_bar()

        self._wire()

    # ── construction ─────────────────────────────────────────────────
    def _build_central_canvas(self) -> None:
        self._canvas = ModelCanvas(self)
        self.setCentralWidget(self._canvas)

    def _build_docks(self) -> None:
        # Model tree (left)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabel("Model")
        for label in ("Nodes", "Elements", "Materials", "Sections",
                      "Time Series", "Patterns", "Analyses"):
            self._tree.addTopLevelItem(QTreeWidgetItem([label]))

        tree_dock = QDockWidget("Model Explorer", self)
        tree_dock.setWidget(self._tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, tree_dock)

        # Properties (right) — selection-aware
        self._props = QLabel("(no selection)")
        self._props.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._props.setWordWrap(True)
        props_dock = QDockWidget("Properties", self)
        props_dock.setWidget(self._props)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, props_dock)

        # Console (bottom)
        self._console = QPlainTextEdit()
        self._console.setReadOnly(True)
        self._console.setPlaceholderText("Logs and OpenSeesPy output will appear here.")
        console_dock = QDockWidget("Console", self)
        console_dock.setWidget(self._console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, console_dock)

    def _build_actions(self) -> None:
        # File
        self._act_new = QAction("&New", self, shortcut=QKeySequence.StandardKey.New)
        self._act_open = QAction("&Open…", self, shortcut=QKeySequence.StandardKey.Open)
        self._act_save = QAction("&Save", self, shortcut=QKeySequence.StandardKey.Save)
        self._act_save_as = QAction("Save &As…", self, shortcut=QKeySequence.StandardKey.SaveAs)
        self._act_quit = QAction("&Quit", self, shortcut=QKeySequence.StandardKey.Quit)

        # View
        self._act_zoom_extents = QAction("Zoom &Extents", self, shortcut="Ctrl+E")
        self._act_view_iso = QAction("&Isometric", self, shortcut="Ctrl+1")
        self._act_view_top = QAction("&Top (XY)", self, shortcut="Ctrl+2")
        self._act_view_front = QAction("&Front (XZ)", self, shortcut="Ctrl+3")
        self._act_view_right = QAction("&Right (YZ)", self, shortcut="Ctrl+4")
        self._act_toggle_parallel = QAction("&Parallel projection", self, checkable=True)

        # Help
        self._act_about = QAction("&About OpenSees Studio…", self)

    def _build_menu_bar(self) -> None:
        mb = self.menuBar()

        m_file = mb.addMenu("&File")
        m_file.addActions([self._act_new, self._act_open])
        m_file.addSeparator()
        m_file.addActions([self._act_save, self._act_save_as])
        m_file.addSeparator()
        m_file.addAction(self._act_quit)

        for name in ("&Edit", "&Define", "&Assign", "&Analyze"):
            mb.addMenu(name)

        m_view = mb.addMenu("&View")
        m_view.addAction(self._act_zoom_extents)
        m_view.addSeparator()
        m_view.addActions([self._act_view_iso, self._act_view_top,
                           self._act_view_front, self._act_view_right])
        m_view.addSeparator()
        m_view.addAction(self._act_toggle_parallel)

        m_help = mb.addMenu("&Help")
        m_help.addAction(self._act_about)

    def _build_view_toolbar(self) -> None:
        tb = QToolBar("View", self)
        tb.setMovable(True)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        tb.addAction(self._act_zoom_extents)
        tb.addSeparator()
        tb.addAction(self._act_view_iso)
        tb.addAction(self._act_view_top)
        tb.addAction(self._act_view_front)
        tb.addAction(self._act_view_right)
        tb.addSeparator()
        tb.addAction(self._act_toggle_parallel)

    def _build_status_bar(self) -> None:
        self._status_label = QLabel("No project")
        self.statusBar().addPermanentWidget(self._status_label)
        self.statusBar().showMessage("Ready")

    def _wire(self) -> None:
        # File
        self._act_new.triggered.connect(self._on_new)
        self._act_open.triggered.connect(self._on_open)
        self._act_save.triggered.connect(self._on_save)
        self._act_save_as.triggered.connect(self._on_save_as)
        self._act_quit.triggered.connect(self.close)
        self._act_about.triggered.connect(self._on_about)

        # View
        self._act_zoom_extents.triggered.connect(self._canvas.reset_camera)
        self._act_view_iso.triggered.connect(self._canvas.view_isometric)
        self._act_view_top.triggered.connect(self._canvas.view_xy)
        self._act_view_front.triggered.connect(self._canvas.view_xz)
        self._act_view_right.triggered.connect(self._canvas.view_yz)
        self._act_toggle_parallel.toggled.connect(self._on_toggle_parallel)

        # ViewModel
        self._vm.projectChanged.connect(self._on_project_changed)
        self._vm.dirtyChanged.connect(self._on_dirty_changed)

        # Canvas selection → properties dock
        self._canvas.selection.selectionChanged.connect(self._on_selection_changed)

    # ── slots ────────────────────────────────────────────────────────
    def _on_new(self) -> None:
        self._vm.new_project()
        self._log("New empty project.")

    def _on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "",
            f"OpenSees Studio model (*{PROJECT_FILE_SUFFIX});;All files (*)",
        )
        if not path:
            return
        try:
            self._vm.open(path)
            self._log(f"Opened: {path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Open failed", str(exc))

    def _on_save(self) -> None:
        if self._vm.path is None:
            self._on_save_as()
            return
        try:
            self._vm.save()
            self._log(f"Saved: {self._vm.path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save failed", str(exc))

    def _on_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project as", "",
            f"OpenSees Studio model (*{PROJECT_FILE_SUFFIX})",
        )
        if not path:
            return
        try:
            out = self._vm.save(path)
            self._log(f"Saved: {out}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save failed", str(exc))

    def _on_toggle_parallel(self, on: bool) -> None:
        cam = self._canvas.camera
        cam.parallel_projection = on
        self._canvas.render()

    def _on_project_changed(self, project: Project | None) -> None:
        self._canvas.show_project(project)
        self._refresh_tree(project)
        self._refresh_status()

    def _on_dirty_changed(self, _dirty: bool) -> None:
        self._refresh_status()

    def _on_selection_changed(self, nodes: frozenset[int], elements: frozenset[int]) -> None:
        if not nodes and not elements:
            self._props.setText("(no selection)")
            return
        parts = []
        if nodes:
            parts.append(f"<b>Nodes:</b> {sorted(nodes)}")
        if elements:
            parts.append(f"<b>Elements:</b> {sorted(elements)}")
        self._props.setText("<br>".join(parts))

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About OpenSees Studio",
            f"<h3>OpenSees Studio {__version__}</h3>"
            "<p>A modern desktop GUI for OpenSeesPy.</p>"
            "<p>MIT License.</p>",
        )

    # ── helpers ──────────────────────────────────────────────────────
    def _refresh_tree(self, project: Project | None) -> None:
        # Phase 3: just update the counts. Phase 4 will populate actual ids.
        if project is None:
            counts = (0, 0, 0, 0, 0, 0, 0)
        else:
            counts = (
                len(project.nodes),
                len(project.elements),
                len(project.materials),
                len(project.sections),
                len(project.time_series),
                len(project.load_patterns),
                len(project.analyses),
            )
        labels = ("Nodes", "Elements", "Materials", "Sections",
                  "Time Series", "Patterns", "Analyses")
        for i, (label, n) in enumerate(zip(labels, counts, strict=True)):
            self._tree.topLevelItem(i).setText(0, f"{label} ({n})")

    def _refresh_status(self) -> None:
        if self._vm.project is None:
            self._status_label.setText("No project")
            return
        path = self._vm.path.name if self._vm.path else "Untitled"
        marker = "*" if self._vm.is_dirty else ""
        self._status_label.setText(
            f"{path}{marker}  |  ndm={self._vm.project.ndm}, ndf={self._vm.project.ndf}"
        )

    def _log(self, message: str) -> None:
        self._console.appendPlainText(message)
        self.statusBar().showMessage(message, 5000)
