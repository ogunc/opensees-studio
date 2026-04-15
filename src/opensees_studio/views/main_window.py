"""Main application window — Phase 4a integration.

Adds on top of Phase 3:
- Edit menu (Undo / Redo / Delete) with keyboard shortcuts
- Define menu (Grid System… → AddNodesCommand)
- Assign menu (Restraints…, Loads…) — both gated by current selection
- modelMutated path: command-driven re-renders preserve camera/selection
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
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
from opensees_studio.commands import (
    AddNodalLoadsCommand,
    AddNodesCommand,
    AssignMaterialCommand,
    AssignSectionCommand,
    DeleteElementsCommand,
    DeleteNodesCommand,
    MirrorCommand,
    MoveNodesCommand,
    ReplicateCommand,
    SetRestraintCommand,
)
from opensees_studio.core import Project
from opensees_studio.services import PROJECT_FILE_SUFFIX
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.canvas3d import ModelCanvas
from opensees_studio.views.dialogs import (
    AssignLoadDialog,
    AssignMaterialDialog,
    AssignSectionDialog,
    AssignSupportDialog,
    GridSystemDialog,
    MaterialLibraryDialog,
    MirrorDialog,
    MoveDialog,
    ReplicateDialog,
    SectionLibraryDialog,
)
from opensees_studio.views.docks import PropertyEditorDock
from opensees_studio.views.tools import DrawFrameTool, SelectTool, ToolController


class MainWindow(QMainWindow):
    """Top-level application shell."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenSees Studio")
        self.resize(1600, 1000)

        self._vm = ProjectViewModel(self)

        self._build_central_canvas()
        self._tool_controller = ToolController(self._canvas, self._vm, self)
        self._select_tool = SelectTool(self._canvas, self._vm, self)
        self._draw_frame_tool: DrawFrameTool | None = None  # lazy-created on activation

        self._build_docks()
        self._build_actions()
        self._build_menu_bar()
        self._build_view_toolbar()
        self._build_tools_toolbar()
        self._build_status_bar()
        self._wire()
        self._refresh_action_enablement()

    # ── construction ─────────────────────────────────────────────────
    def _build_central_canvas(self) -> None:
        self._canvas = ModelCanvas(self)
        self.setCentralWidget(self._canvas)

    def _build_docks(self) -> None:
        self._tree = QTreeWidget()
        self._tree.setHeaderLabel("Model")
        for label in ("Nodes", "Elements", "Materials", "Sections",
                      "Time Series", "Patterns", "Analyses"):
            self._tree.addTopLevelItem(QTreeWidgetItem([label]))
        tree_dock = QDockWidget("Model Explorer", self)
        tree_dock.setWidget(self._tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, tree_dock)

        self._props = PropertyEditorDock()
        props_dock = QDockWidget("Properties", self)
        props_dock.setWidget(self._props)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, props_dock)

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

        # Edit (created from QUndoStack so text auto-tracks "Undo Add 4 nodes" etc.)
        self._act_undo = self._vm.undo_stack.createUndoAction(self, "Undo")
        self._act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self._act_redo = self._vm.undo_stack.createRedoAction(self, "Redo")
        self._act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self._act_delete = QAction("&Delete selection", self, shortcut=QKeySequence.StandardKey.Delete)
        self._act_clear_selection = QAction("Clear &selection", self, shortcut="Esc")
        self._act_select_all = QAction("Select &all", self, shortcut="Ctrl+A")

        # Edit → transforms
        self._act_move = QAction("&Move…", self, shortcut="Ctrl+M")
        self._act_replicate = QAction("&Replicate…", self, shortcut="Ctrl+Shift+R")
        self._act_mirror = QAction("Mirr&or…", self)

        # Tools (exclusive)
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self._act_tool_select = QAction("Se&lect", self, checkable=True, checked=True)
        self._act_tool_draw_frame = QAction("&Draw Frame", self, checkable=True, shortcut="F2")
        self._tool_group.addAction(self._act_tool_select)
        self._tool_group.addAction(self._act_tool_draw_frame)

        # Define
        self._act_grid = QAction("&Grid System…", self, shortcut="Ctrl+G")
        self._act_material_library = QAction("&Material Library…", self, shortcut="Ctrl+Shift+M")
        self._act_section_library = QAction("&Section Library…", self, shortcut="Ctrl+Shift+S")

        # Assign
        self._act_assign_support = QAction("&Restraints…", self, shortcut="Ctrl+R")
        self._act_assign_load = QAction("&Loads…", self, shortcut="Ctrl+L")
        self._act_assign_section = QAction("S&ection…", self)
        self._act_assign_material = QAction("&Material…", self)

        # View
        self._act_zoom_extents = QAction("Zoom &Extents", self, shortcut="Ctrl+E")
        self._act_view_iso = QAction("&Isometric", self, shortcut="Ctrl+1")
        self._act_view_top = QAction("&Top (XY)", self, shortcut="Ctrl+2")
        self._act_view_front = QAction("&Front (XZ)", self, shortcut="Ctrl+3")
        self._act_view_right = QAction("&Right (YZ)", self, shortcut="Ctrl+4")
        self._act_toggle_parallel = QAction("&Parallel projection", self, checkable=True)

        self._act_about = QAction("&About OpenSees Studio…", self)

    def _build_menu_bar(self) -> None:
        mb = self.menuBar()

        m_file = mb.addMenu("&File")
        m_file.addActions([self._act_new, self._act_open])
        m_file.addSeparator()
        m_file.addActions([self._act_save, self._act_save_as])
        m_file.addSeparator()
        m_file.addAction(self._act_quit)

        m_edit = mb.addMenu("&Edit")
        m_edit.addActions([self._act_undo, self._act_redo])
        m_edit.addSeparator()
        m_edit.addActions([self._act_delete, self._act_select_all, self._act_clear_selection])
        m_edit.addSeparator()
        m_edit.addActions([self._act_move, self._act_replicate, self._act_mirror])

        m_define = mb.addMenu("&Define")
        m_define.addAction(self._act_grid)
        m_define.addSeparator()
        m_define.addActions([self._act_material_library, self._act_section_library])

        m_assign = mb.addMenu("&Assign")
        m_assign.addActions([self._act_assign_support, self._act_assign_load])
        m_assign.addSeparator()
        m_assign.addActions([self._act_assign_section, self._act_assign_material])

        mb.addMenu("&Analyze")  # populated in Phase 6

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

    def _build_tools_toolbar(self) -> None:
        tb = QToolBar("Tools", self)
        tb.setMovable(True)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tb)
        tb.addAction(self._act_tool_select)
        tb.addAction(self._act_tool_draw_frame)

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

        # Edit
        self._act_delete.triggered.connect(self._on_delete)
        self._act_clear_selection.triggered.connect(self._on_clear_selection)
        self._act_select_all.triggered.connect(self._on_select_all)
        self._act_move.triggered.connect(self._on_move)
        self._act_replicate.triggered.connect(self._on_replicate)
        self._act_mirror.triggered.connect(self._on_mirror)

        # Tools
        self._act_tool_select.triggered.connect(self._on_select_tool)
        self._act_tool_draw_frame.triggered.connect(self._on_draw_frame_tool)
        self._tool_controller.toolChanged.connect(self._on_tool_changed)

        # Define
        self._act_grid.triggered.connect(self._on_grid_system)
        self._act_material_library.triggered.connect(self._on_material_library)
        self._act_section_library.triggered.connect(self._on_section_library)

        # Assign
        self._act_assign_support.triggered.connect(self._on_assign_support)
        self._act_assign_load.triggered.connect(self._on_assign_load)
        self._act_assign_section.triggered.connect(self._on_assign_section)
        self._act_assign_material.triggered.connect(self._on_assign_material)

        # View
        self._act_zoom_extents.triggered.connect(self._canvas.reset_camera)
        self._act_view_iso.triggered.connect(self._canvas.view_isometric)
        self._act_view_top.triggered.connect(self._canvas.view_xy)
        self._act_view_front.triggered.connect(self._canvas.view_xz)
        self._act_view_right.triggered.connect(self._canvas.view_yz)
        self._act_toggle_parallel.toggled.connect(self._on_toggle_parallel)

        # ViewModel
        self._vm.projectChanged.connect(self._on_project_changed)
        self._vm.modelMutated.connect(self._on_model_mutated)
        self._vm.dirtyChanged.connect(self._on_dirty_changed)

        # Selection → properties + action enablement
        self._canvas.selection.selectionChanged.connect(self._on_selection_changed)

    # ── slots: file ──────────────────────────────────────────────────
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

    # ── slots: edit ──────────────────────────────────────────────────
    def _on_delete(self) -> None:
        if self._vm.project is None:
            return
        sel = self._canvas.selection
        if sel.is_empty:
            return
        try:
            if sel.elements:
                self._vm.apply_command(DeleteElementsCommand(self._vm, set(sel.elements)))
            if sel.nodes:
                self._vm.apply_command(DeleteNodesCommand(self._vm, set(sel.nodes)))
            sel.clear()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Delete failed", str(exc))

    def _on_select_all(self) -> None:
        """Select all nodes AND all elements in the project."""
        if self._vm.project is None:
            return
        node_ids = {n.id for n in self._vm.project.nodes}
        elem_ids = {e.id for e in self._vm.project.elements}
        self._canvas.selection.set_selection(node_ids, elem_ids)

    def _on_clear_selection(self) -> None:
        """Esc: clear selection AND reset any in-progress tool gesture."""
        self._canvas.selection.clear()
        self._tool_controller.cancel()

    # ── slots: edit → transforms ────────────────────────────────────
    def _on_move(self) -> None:
        sel_nodes = set(self._canvas.selection.nodes)
        if not sel_nodes:
            QMessageBox.information(self, "Move", "Select one or more nodes first.")
            return
        dlg = MoveDialog(len(sel_nodes), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(MoveNodesCommand(self._vm, sel_nodes, dlg.offset()))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Move failed", str(exc))

    def _on_replicate(self) -> None:
        sel_nodes = set(self._canvas.selection.nodes)
        sel_elements = set(self._canvas.selection.elements)
        if not sel_nodes:
            QMessageBox.information(self, "Replicate", "Select one or more nodes first.")
            return
        # Forgiving: if the user selected only nodes, include any element whose
        # endpoints are all in the node selection.
        if not sel_elements and self._vm.project is not None:
            sel_elements = {
                el.id for el in self._vm.project.elements
                if all(nid in sel_nodes for nid in el.nodes)
            }
        dlg = ReplicateDialog(len(sel_nodes), len(sel_elements), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(
                ReplicateCommand(self._vm, sel_nodes, sel_elements,
                                 dlg.offset(), dlg.n_copies())
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Replicate failed", str(exc))

    def _on_mirror(self) -> None:
        sel_nodes = set(self._canvas.selection.nodes)
        sel_elements = set(self._canvas.selection.elements)
        if not sel_nodes:
            QMessageBox.information(self, "Mirror", "Select one or more nodes first.")
            return
        if not sel_elements and self._vm.project is not None:
            sel_elements = {
                el.id for el in self._vm.project.elements
                if all(nid in sel_nodes for nid in el.nodes)
            }
        dlg = MirrorDialog(len(sel_nodes), len(sel_elements), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(
                MirrorCommand(self._vm, sel_nodes, sel_elements, dlg.plane())  # type: ignore[arg-type]
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Mirror failed", str(exc))

    # ── slots: tools ────────────────────────────────────────────────
    def _on_select_tool(self) -> None:
        self._tool_controller.set_active(None)

    def _on_draw_frame_tool(self) -> None:
        if self._draw_frame_tool is None:
            self._draw_frame_tool = DrawFrameTool(self._canvas, self._vm, self)
            self._draw_frame_tool.statusChanged.connect(
                lambda msg: self.statusBar().showMessage(msg)
            )
        self._tool_controller.set_active(self._draw_frame_tool)

    def _on_tool_changed(self, tool) -> None:  # type: ignore[no-untyped-def]
        if tool is None:
            self.statusBar().showMessage("Select tool active.", 3000)
        else:
            self.statusBar().showMessage(tool.prompt())

    # ── slots: define ────────────────────────────────────────────────
    def _on_grid_system(self) -> None:
        if self._vm.project is None:
            self._on_new()
        dlg = GridSystemDialog(self._vm.project.next_node_id(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        nodes = dlg.generated_nodes()
        if not nodes:
            return
        try:
            self._vm.apply_command(
                AddNodesCommand(self._vm, nodes, text=f"Generate {len(nodes)} grid nodes")
            )
            self._log(f"Generated {len(nodes)} nodes from grid.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Grid generation failed", str(exc))

    # ── slots: assign ────────────────────────────────────────────────
    def _on_assign_support(self) -> None:
        sel_nodes = set(self._canvas.selection.nodes)
        if not sel_nodes:
            QMessageBox.information(self, "Assign Support", "Select one or more nodes first.")
            return
        dlg = AssignSupportDialog(len(sel_nodes), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(SetRestraintCommand(self._vm, sel_nodes, dlg.restraint()))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Assign Support failed", str(exc))

    def _on_assign_load(self) -> None:
        sel_nodes = set(self._canvas.selection.nodes)
        if not sel_nodes:
            QMessageBox.information(self, "Assign Load", "Select one or more nodes first.")
            return
        dlg = AssignLoadDialog(len(sel_nodes), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(AddNodalLoadsCommand(self._vm, sel_nodes, dlg.forces()))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Assign Load failed", str(exc))

    # ── slots: define ────────────────────────────────────────────────
    def _on_material_library(self) -> None:
        if self._vm.project is None:
            self._on_new()
        MaterialLibraryDialog(self._vm, self).exec()

    def _on_section_library(self) -> None:
        if self._vm.project is None:
            self._on_new()
        SectionLibraryDialog(self._vm, self).exec()

    # ── slots: assign property ──────────────────────────────────────
    def _on_assign_section(self) -> None:
        if self._vm.project is None:
            return
        sel_elements = set(self._canvas.selection.elements)
        if not sel_elements:
            QMessageBox.information(self, "Assign Section",
                                    "Select one or more frame elements first.")
            return
        dlg = AssignSectionDialog(self._vm.project.sections, len(sel_elements), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(
                AssignSectionCommand(self._vm, sel_elements, dlg.section_id())
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Assign Section failed", str(exc))

    def _on_assign_material(self) -> None:
        if self._vm.project is None:
            return
        sel_elements = set(self._canvas.selection.elements)
        if not sel_elements:
            QMessageBox.information(self, "Assign Material",
                                    "Select one or more truss/zero-length elements first.")
            return
        dlg = AssignMaterialDialog(self._vm.project.materials, len(sel_elements), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(
                AssignMaterialCommand(self._vm, sel_elements, dlg.material_id())
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Assign Material failed", str(exc))

    # ── slots: view & state ──────────────────────────────────────────
    def _on_toggle_parallel(self, on: bool) -> None:
        cam = self._canvas.camera
        cam.parallel_projection = on
        self._canvas.render()

    def _on_project_changed(self, project: Project | None) -> None:
        self._canvas.show_project(project)
        self._props.set_project(project)
        self._refresh_tree(project)
        self._refresh_status()
        self._refresh_action_enablement()

    def _on_model_mutated(self) -> None:
        # Same project, contents changed: re-render but DON'T reset camera.
        # We still clear and re-add actors, which loses selection — but the
        # selection state persists, so highlights re-apply.
        if self._vm.project is not None:
            self._canvas._renderer.render(self._vm.project)
            self._canvas.render()
        self._refresh_tree(self._vm.project)
        # Update the property editor with the (possibly new) entity values
        # at the current selection.
        self._props.update_for_selection(
            self._canvas.selection.nodes, self._canvas.selection.elements
        )
        self._refresh_action_enablement()

    def _on_dirty_changed(self, _dirty: bool) -> None:
        self._refresh_status()

    def _on_selection_changed(self, nodes: frozenset[int], elements: frozenset[int]) -> None:
        self._props.update_for_selection(nodes, elements)
        self._refresh_action_enablement()

    def _on_about(self) -> None:
        QMessageBox.about(
            self, "About OpenSees Studio",
            f"<h3>OpenSees Studio {__version__}</h3>"
            "<p>A modern desktop GUI for OpenSeesPy.</p>"
            "<p>MIT License.</p>",
        )

    # ── helpers ──────────────────────────────────────────────────────
    def _refresh_tree(self, project: Project | None) -> None:
        if project is None:
            counts = (0,) * 7
        else:
            counts = (
                len(project.nodes), len(project.elements), len(project.materials),
                len(project.sections), len(project.time_series),
                len(project.load_patterns), len(project.analyses),
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

    def _refresh_action_enablement(self) -> None:
        has_project = self._vm.project is not None
        has_selection = not self._canvas.selection.is_empty
        has_selected_nodes = bool(self._canvas.selection.nodes)
        self._act_save.setEnabled(has_project)
        self._act_save_as.setEnabled(has_project)
        self._act_grid.setEnabled(True)               # creates a new project if needed
        self._act_assign_support.setEnabled(has_project and has_selected_nodes)
        self._act_assign_load.setEnabled(has_project and has_selected_nodes)
        self._act_delete.setEnabled(has_project and has_selection)
        self._act_move.setEnabled(has_project and has_selected_nodes)
        self._act_replicate.setEnabled(has_project and has_selected_nodes)
        self._act_mirror.setEnabled(has_project and has_selected_nodes)
        self._act_tool_draw_frame.setEnabled(has_project)

    def _log(self, message: str) -> None:
        self._console.appendPlainText(message)
        self.statusBar().showMessage(message, 5000)
