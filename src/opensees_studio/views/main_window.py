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
    AddElementLoadsCommand,
    SetMassCommand,
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
from opensees_studio.viewmodels import AnalysisRunner, ProjectViewModel
from opensees_studio.services.deformation import (
    linear_static_auto_scale,
    modal_to_deformation,
    static_to_deformation,
)
from opensees_studio.services.element_forces import (
    ForceComponent,
    auto_scale as force_diagram_auto_scale,
    extract_diagram_data,
)
from opensees_studio.services.results import (
    ModalResults,
    PushoverResults,
    StaticResults,
    TransientResults,
)
from opensees_studio.views.canvas3d import ModelCanvas
from opensees_studio.views.canvas3d.diagram_renderer import DiagramRenderer
from opensees_studio.views.canvas3d.model_renderer import RendererMode
from opensees_studio.views.dialogs import (
    AnalysisCaseManagerDialog,
    AssignLoadDialog,
    AssignDistributedLoadDialog,
    AssignMaterialDialog,
    AssignSectionDialog,
    AssignSupportDialog,
    GridSystemDialog,
    MaterialLibraryDialog,
    MirrorDialog,
    MoveDialog,
    ReplicateDialog,
    RunAnalysisDialog,
    SectionLibraryDialog,
)
from opensees_studio.views.docks import (
    DeformedShapeView,
    ForceDiagramView,
    HysteresisView,
    ModeShapeAnimator,
    PropertyEditorDock,
    PushoverCurveView,
    ResultsPanel,
    TimeHistoryView,
)
from opensees_studio.views.tools import DrawFrameTool, SelectTool, ToolController


class MainWindow(QMainWindow):
    """Top-level application shell."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenSees Studio")
        self.resize(1600, 1000)

        self._vm = ProjectViewModel(self)
        self._runner = AnalysisRunner(self)
        self._latest_results: object = None       # last analysis output (any kind)
        self._post_dock = None                     # the active post-processing dock
        self._diagram_renderer: DiagramRenderer | None = None   # built lazily once canvas exists

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
        # Diagram overlay paints onto the same plotter as the model.
        self._diagram_renderer = DiagramRenderer(self._canvas)

    def _build_docks(self) -> None:
        # Model tree (left)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabel("Model")
        self._tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        # Top-level category items, populated lazily on refresh.
        self._tree_categories: dict[str, QTreeWidgetItem] = {}
        for label in ("Nodes", "Elements", "Materials", "Sections",
                      "Time Series", "Patterns", "Analyses"):
            cat = QTreeWidgetItem([label])
            self._tree_categories[label] = cat
            self._tree.addTopLevelItem(cat)
        tree_dock = QDockWidget("Model Explorer", self)
        tree_dock.setWidget(self._tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, tree_dock)

        self._props = PropertyEditorDock()
        self._props.on_apply_mass = self._on_apply_mass
        props_dock = QDockWidget("Properties", self)
        props_dock.setWidget(self._props)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, props_dock)

        self._console = QPlainTextEdit()
        self._console.setReadOnly(True)
        self._console.setPlaceholderText("Logs and OpenSeesPy output will appear here.")
        console_dock = QDockWidget("Console", self)
        console_dock.setWidget(self._console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, console_dock)

        self._results_panel = ResultsPanel()
        results_dock = QDockWidget("Results", self)
        results_dock.setWidget(self._results_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, results_dock)
        self.tabifyDockWidget(console_dock, results_dock)
        console_dock.raise_()

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
        self._act_assign_distributed_load = QAction("&Distributed Load…", self)
        self._act_assign_section = QAction("S&ection…", self)
        self._act_assign_material = QAction("&Material…", self)

        # Display (post-processing)
        self._act_show_deformed = QAction("Show &Deformed Shape", self)
        self._act_show_mode_shape = QAction("&Animate Mode Shape", self)
        self._act_show_force_diagram = QAction("Show &Force Diagram…", self)
        self._act_show_time_history = QAction("&Time-History Plot…", self)
        self._act_export_th_animation = QAction("Export Time-History &Animation…", self)
        self._act_show_hysteresis = QAction("&Hysteresis Plot…", self)
        self._act_show_pushover = QAction("Show &Pushover Curve…", self)
        self._act_back_to_model = QAction("Back to &Model View", self, shortcut="Ctrl+Shift+B")

        # Analyze
        self._act_case_manager = QAction("&Cases…", self, shortcut="Ctrl+Shift+A")
        self._act_run = QAction("&Run…", self, shortcut="F5")

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
        m_assign.addAction(self._act_assign_distributed_load)
        m_assign.addSeparator()
        m_assign.addActions([self._act_assign_section, self._act_assign_material])

        m_analyze = mb.addMenu("&Analyze")
        m_analyze.addAction(self._act_case_manager)
        m_analyze.addSeparator()
        m_analyze.addAction(self._act_run)

        m_display = mb.addMenu("&Display")
        m_display.addActions([self._act_show_deformed, self._act_show_mode_shape])
        m_display.addAction(self._act_show_force_diagram)
        m_display.addSeparator()
        m_display.addAction(self._act_show_time_history)
        m_display.addAction(self._act_export_th_animation)
        m_display.addAction(self._act_show_hysteresis)
        m_display.addAction(self._act_show_pushover)
        m_display.addSeparator()
        m_display.addAction(self._act_back_to_model)

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
        self._act_assign_distributed_load.triggered.connect(self._on_assign_distributed_load)
        self._act_assign_section.triggered.connect(self._on_assign_section)
        self._act_assign_material.triggered.connect(self._on_assign_material)

        # Analyze
        self._act_case_manager.triggered.connect(self._on_case_manager)
        self._act_run.triggered.connect(self._on_run_analysis)

        # Display
        self._act_show_deformed.triggered.connect(self._on_show_deformed)
        self._act_show_mode_shape.triggered.connect(self._on_show_mode_shape)
        self._act_show_force_diagram.triggered.connect(self._on_show_force_diagram)
        self._act_show_time_history.triggered.connect(self._on_show_time_history)
        self._act_export_th_animation.triggered.connect(self._on_export_th_animation)
        self._act_show_hysteresis.triggered.connect(self._on_show_hysteresis)
        self._act_show_pushover.triggered.connect(self._on_show_pushover)
        self._act_back_to_model.triggered.connect(self._on_back_to_model)

        # AnalysisRunner: stream log to console + show results in panel
        self._runner.log.connect(self._console.appendPlainText)
        self._runner.finished.connect(self._on_analysis_finished)
        self._runner.failed.connect(self._on_analysis_failed)

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

    def _on_apply_mass(self, node_id: int, mass) -> None:  # type: ignore[no-untyped-def]
        """Callback from the property editor — dispatch as an undoable command."""
        try:
            self._vm.apply_command(SetMassCommand(self._vm, {node_id}, mass))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Apply mass failed", str(exc))

    def _on_assign_distributed_load(self) -> None:
        sel_elements = set(self._canvas.selection.elements)
        if not sel_elements:
            QMessageBox.information(
                self, "Assign Distributed Load",
                "Select one or more elements first.",
            )
            return
        dlg = AssignDistributedLoadDialog(len(sel_elements), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        wy, wz, wx = dlg.values()
        try:
            self._vm.apply_command(
                AddElementLoadsCommand(self._vm, sel_elements, wy=wy, wz=wz, wx=wx),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Assign Distributed Load failed", str(exc))

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

    # ── slots: analyze ──────────────────────────────────────────────
    def _on_case_manager(self) -> None:
        if self._vm.project is None:
            self._on_new()
        AnalysisCaseManagerDialog(self._vm, self).exec()

    def _on_run_analysis(self) -> None:
        if self._vm.project is None:
            QMessageBox.information(self, "Run Analysis", "Open or create a project first.")
            return
        if not self._vm.project.analyses:
            QMessageBox.information(
                self, "Run Analysis",
                "No analysis cases defined. Open Analyze → Cases…",
            )
            return
        dlg = RunAnalysisDialog(self._vm, self._runner, self)
        dlg.exec()

    def _on_analysis_finished(self, results) -> None:  # type: ignore[no-untyped-def]
        self._latest_results = results
        self._results_panel.show_results(results)
        self._log(f"Analysis complete: {type(results).__name__}.")
        self._refresh_action_enablement()

    def _on_analysis_failed(self, traceback_str: str) -> None:
        QMessageBox.critical(self, "Analysis failed",
                             "See the Console dock for the full traceback.")
        self._log("Analysis failed.")

    # ── slots: display (post-processing) ────────────────────────────
    def _on_show_deformed(self) -> None:
        if not isinstance(self._latest_results, StaticResults) or self._vm.project is None:
            QMessageBox.information(
                self, "Deformed Shape",
                "Run a Static analysis first (Display works on the latest results).",
            )
            return
        self._tear_down_post_dock()
        suggested = linear_static_auto_scale(self._vm.project, self._latest_results)
        view = DeformedShapeView(suggested_scale=suggested)
        dock = QDockWidget("Deformed Shape", self)
        dock.setWidget(view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._post_dock = dock

        def _apply(scale: float) -> None:
            if not isinstance(self._latest_results, StaticResults):
                return
            src = static_to_deformation(self._vm.project, self._latest_results,
                                        scale=scale)
            self._canvas._renderer.set_mode(RendererMode.DEFORMED, src)
            self._canvas.render()

        view.scaleChanged.connect(_apply)
        view.closed.connect(self._on_back_to_model)
        _apply(suggested)   # initial frame at the suggested scale

    def _on_show_mode_shape(self) -> None:
        if not isinstance(self._latest_results, ModalResults) or self._vm.project is None:
            QMessageBox.information(
                self, "Mode Shape",
                "Run a Modal analysis first.",
            )
            return
        self._tear_down_post_dock()
        n_modes = len(self._latest_results.eigenvalues)
        freqs = list(self._latest_results.frequencies)
        animator = ModeShapeAnimator(n_modes, freqs)
        dock = QDockWidget("Mode Shape Animator", self)
        dock.setWidget(animator)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._post_dock = dock

        def _apply(mode: int, scale: float, phase: float) -> None:
            if not isinstance(self._latest_results, ModalResults):
                return
            src = modal_to_deformation(self._vm.project, self._latest_results,
                                       mode=mode, scale=scale, phase=phase)
            self._canvas._renderer.set_mode(RendererMode.MODAL, src)
            self._canvas.render()

        animator.frameChanged.connect(_apply)
        animator.closed.connect(self._on_back_to_model)
        animator.exportRequested.connect(
            lambda: self._on_export_mode_shape(animator, _apply),
        )
        # Animator emits an initial frame in its constructor; nothing to do.

    def _on_export_mode_shape(self, animator, apply_callable) -> None:  # type: ignore[no-untyped-def]
        """Capture one period of the current mode shape to MP4/GIF.

        Runs synchronously on the main thread — typically <10s for a
        100-node model. We deliberately don't push this to a QThread
        because the off-screen renderer must be touched from the GUI
        thread (VTK's Qt-backed render window isn't thread-safe).
        """
        from PySide6.QtWidgets import QFileDialog

        path, sel = QFileDialog.getSaveFileName(
            self, "Export Mode Shape Animation",
            f"mode_{animator.current_mode() + 1}.mp4",
            "MP4 Video (*.mp4);;GIF Animation (*.gif);;WebM Video (*.webm)",
        )
        if not path:
            return
        from pathlib import Path

        from opensees_studio.services.animation_export import export_mode_shape_video

        mode = animator.current_mode()
        scale = animator.current_scale()

        def set_phase(phase: float) -> None:
            apply_callable(mode, scale, phase)

        try:
            self._log(f"Exporting mode {mode + 1} animation → {path} …")
            export_mode_shape_video(
                self._canvas,
                set_phase,
                Path(path),
                n_frames=60,
                fps=30,
                progress=lambda i, n: self.statusBar().showMessage(
                    f"Exporting frame {i}/{n}",
                ),
            )
            self.statusBar().clearMessage()
            self._log(f"Export complete: {path}")
        except Exception as exc:
            QMessageBox.critical(
                self, "Export failed",
                f"Could not write the animation:\n\n{exc}\n\n"
                "MP4 export requires FFmpeg via imageio. Try .gif as a fallback.",
            )

    def _on_show_force_diagram(self) -> None:
        if not isinstance(self._latest_results, StaticResults) or self._vm.project is None:
            QMessageBox.information(
                self, "Force Diagram",
                "Run a Static analysis first; force diagrams visualise its "
                "element-force output.",
            )
            return
        self._tear_down_post_dock()

        # Pick the component with the largest abs_max as the initial choice
        # so the user sees something even if N (the default) happens to be
        # zero (cantilever bending case, etc.).
        best_comp, best_data = self._best_initial_component()
        suggested = force_diagram_auto_scale(self._vm.project, best_data)

        view = ForceDiagramView(suggested_scale=suggested)
        # Sync the picker to the auto-chosen best component WITHOUT firing
        # signals (we'll emit a single render below).
        view._component.blockSignals(True)
        idx = view._component.findData(best_comp)
        if idx >= 0:
            view._component.setCurrentIndex(idx)
        view._component.blockSignals(False)

        dock = QDockWidget("Force Diagram", self)
        dock.setWidget(view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._post_dock = dock

        def _render(component: ForceComponent, scale: float) -> None:
            if not isinstance(self._latest_results, StaticResults):
                return
            data = extract_diagram_data(
                self._vm.project, self._latest_results, component,
            )
            if self._diagram_renderer is not None:
                self._diagram_renderer.render(self._vm.project, data, scale)
            self._canvas.render()

        def _on_component_changed(component: ForceComponent) -> None:
            # Recompute the suggested scale for the new component and push
            # it back into the view, which will re-emit `changed`.
            data = extract_diagram_data(
                self._vm.project, self._latest_results, component,
            )
            new_scale = force_diagram_auto_scale(self._vm.project, data)
            view.set_scale_base(new_scale)

        view.componentChanged.connect(_on_component_changed)
        view.changed.connect(_render)
        view.closed.connect(self._on_back_to_model)

        # Force the first render now that everything is wired.
        view._emit_changed()

    def _best_initial_component(self):
        """Return the (component, data) pair with the largest |force|.

        Used when first opening the diagram dock so we don't show an empty
        diagram for cases where the default component happens to be zero.
        """
        from opensees_studio.services.element_forces import ForceComponent as FC
        best_comp = FC.N
        best_data = extract_diagram_data(self._vm.project, self._latest_results, FC.N)
        best_max = best_data.abs_max
        for comp in (FC.V2, FC.V3, FC.M2, FC.M3, FC.T):
            d = extract_diagram_data(self._vm.project, self._latest_results, comp)
            if d.abs_max > best_max:
                best_max, best_comp, best_data = d.abs_max, comp, d
        return best_comp, best_data

    def _on_show_time_history(self) -> None:
        if not isinstance(self._latest_results, TransientResults) or self._vm.project is None:
            QMessageBox.information(
                self, "Time-History Plot",
                "Run a Transient (time-history) analysis first.",
            )
            return
        self._tear_down_post_dock()
        view = TimeHistoryView()
        view.set_results(self._latest_results)
        view.set_available_nodes([n.id for n in self._vm.project.nodes])
        dock = QDockWidget("Time-History Plot", self)
        dock.setWidget(view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        # Plotter docks deserve more space than the slim deformed-shape panel.
        dock.resize(700, 500)
        self._post_dock = dock
        view.closed.connect(self._on_back_to_model)

    def _on_export_th_animation(self) -> None:
        """Export the deformed shape evolution over a transient analysis."""
        if not isinstance(self._latest_results, TransientResults) or self._vm.project is None:
            QMessageBox.information(
                self, "Export Time-History Animation",
                "Run a Transient (time-history) analysis first.",
            )
            return
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        from pathlib import Path

        from opensees_studio.services.animation_export import (
            export_time_history_video,
        )
        # Compute a sensible scale: peak displacement → ~10% of bbox.
        # We piggy-back on the deformation service for consistency.
        # First peek at the data so we can pick `every` such that the
        # video ends up reasonable (~150 frames target).
        n_steps = self._latest_results.n_steps
        every, ok = QInputDialog.getInt(
            self, "Frame decimation",
            f"Take every Nth step ({n_steps} steps available):",
            max(1, n_steps // 150), 1, n_steps,
        )
        if not ok:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Time-History Animation",
            f"timehistory_{self._latest_results.case_name}.mp4",
            "MP4 Video (*.mp4);;GIF Animation (*.gif);;WebM Video (*.webm)",
        )
        if not path:
            return

        # Find the largest displacement to set a visible scale.
        from opensees_studio.services.deformation import (
            transient_to_deformation_at_step,
        )

        def set_step(step: int) -> None:
            src = transient_to_deformation_at_step(
                self._vm.project, self._latest_results, step=step,
            )
            self._canvas._renderer.set_mode(RendererMode.DEFORMED, src)
            self._canvas.render()

        try:
            self._log(f"Exporting time-history animation → {path} …")
            export_time_history_video(
                self._canvas, set_step, Path(path), n_steps,
                fps=30, every=every,
                progress=lambda i, n: self.statusBar().showMessage(
                    f"Exporting frame {i}/{n}",
                ),
            )
            self.statusBar().clearMessage()
            self._log(f"Export complete: {path}")
        except Exception as exc:
            QMessageBox.critical(
                self, "Export failed",
                f"Could not write the animation:\n\n{exc}\n\n"
                "MP4 export requires FFmpeg via imageio. Try .gif as a fallback.",
            )

    def _on_show_hysteresis(self) -> None:
        if not isinstance(self._latest_results, TransientResults) or self._vm.project is None:
            QMessageBox.information(
                self, "Hysteresis Plot",
                "Run a Transient (time-history) analysis first.",
            )
            return
        self._tear_down_post_dock()
        view = HysteresisView()
        view.set_results(self._latest_results)
        view.set_available_nodes([n.id for n in self._vm.project.nodes])
        view.set_available_elements([e.id for e in self._vm.project.elements])
        dock = QDockWidget("Hysteresis Plot", self)
        dock.setWidget(view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.resize(700, 500)
        self._post_dock = dock
        view.closed.connect(self._on_back_to_model)

    def _on_show_pushover(self) -> None:
        if not isinstance(self._latest_results, PushoverResults):
            QMessageBox.information(
                self, "Pushover Curve",
                "Run a Pushover analysis first.",
            )
            return
        self._tear_down_post_dock()
        view = PushoverCurveView()
        view.set_results(self._latest_results)
        dock = QDockWidget("Pushover Curve", self)
        dock.setWidget(view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.resize(700, 500)
        self._post_dock = dock
        view.closed.connect(self._on_back_to_model)

    def _on_back_to_model(self) -> None:
        self._tear_down_post_dock()
        if self._diagram_renderer is not None:
            self._diagram_renderer.clear()
        self._canvas._renderer.set_mode(RendererMode.MODEL)
        self._canvas.render()

    def _tear_down_post_dock(self) -> None:
        if self._post_dock is not None:
            self.removeDockWidget(self._post_dock)
            self._post_dock.deleteLater()
            self._post_dock = None

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
        """Repopulate the model explorer with category counts AND children."""
        # Helper to refill one category in place.
        def _fill(cat: QTreeWidgetItem, items: list, label_fn) -> None:  # type: ignore[no-untyped-def]
            cat.takeChildren()
            cat.setText(0, f"{cat.text(0).split(' (')[0]} ({len(items)})")
            for it in items:
                child = QTreeWidgetItem([label_fn(it)])
                # Tag with kind + id so selection sync can dispatch.
                child.setData(0, Qt.ItemDataRole.UserRole, (cat.text(0).split(' (')[0], it.id))
                cat.addChild(child)

        if project is None:
            for cat in self._tree_categories.values():
                cat.takeChildren()
                cat.setText(0, f"{cat.text(0).split(' (')[0]} (0)")
            return

        _fill(self._tree_categories["Nodes"], project.nodes,
              lambda n: f"#{n.id}  {n.name or ''}".strip())
        _fill(self._tree_categories["Elements"], project.elements,
              lambda e: f"#{e.id}  [{e.type}]  {e.name or ''}".strip())
        _fill(self._tree_categories["Materials"], project.materials,
              lambda m: f"#{m.id}  [{m.type}]  {m.name or ''}".strip())
        _fill(self._tree_categories["Sections"], project.sections,
              lambda s: f"#{s.id}  [{s.type}]  {s.name or ''}".strip())
        _fill(self._tree_categories["Time Series"], project.time_series,
              lambda t: f"#{t.id}  [{t.type}]  {t.name or ''}".strip())
        _fill(self._tree_categories["Patterns"], project.load_patterns,
              lambda p: f"#{p.id}  [{p.type}]  {p.name or ''}".strip())
        _fill(self._tree_categories["Analyses"], project.analyses,
              lambda a: f"#{a.id}  [{a.type}]  {a.name or ''}".strip())

    def _on_tree_selection_changed(self) -> None:
        """When a Node or Element row is picked in the tree, sync the canvas."""
        items = self._tree.selectedItems()
        if not items:
            return
        item = items[0]
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is None:    # category header itself was clicked
            return
        kind, entity_id = data
        if kind == "Nodes":
            self._canvas.selection.select_node(entity_id)
        elif kind == "Elements":
            self._canvas.selection.select_element(entity_id)
        # Materials / Sections / Patterns / Analyses: just show in property dock.
        # Properties dock is wired to selection signal which doesn't carry these
        # types yet; for now, the user already saw the row label in the tree.

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
        has_selected_elements = bool(self._canvas.selection.elements)
        has_static = isinstance(self._latest_results, StaticResults)
        has_modal = isinstance(self._latest_results, ModalResults)
        has_transient = isinstance(self._latest_results, TransientResults)
        has_pushover = isinstance(self._latest_results, PushoverResults)
        self._act_save.setEnabled(has_project)
        self._act_save_as.setEnabled(has_project)
        self._act_grid.setEnabled(True)
        self._act_assign_support.setEnabled(has_project and has_selected_nodes)
        self._act_assign_load.setEnabled(has_project and has_selected_nodes)
        self._act_assign_distributed_load.setEnabled(has_project and has_selected_elements)
        self._act_delete.setEnabled(has_project and has_selection)
        self._act_move.setEnabled(has_project and has_selected_nodes)
        self._act_replicate.setEnabled(has_project and has_selected_nodes)
        self._act_mirror.setEnabled(has_project and has_selected_nodes)
        self._act_tool_draw_frame.setEnabled(has_project)
        self._act_show_deformed.setEnabled(has_static)
        self._act_show_mode_shape.setEnabled(has_modal)
        self._act_show_force_diagram.setEnabled(has_static)
        self._act_show_time_history.setEnabled(has_transient)
        self._act_export_th_animation.setEnabled(has_transient)
        self._act_show_hysteresis.setEnabled(has_transient)
        self._act_show_pushover.setEnabled(has_pushover)
        self._act_back_to_model.setEnabled(self._post_dock is not None)

    def _log(self, message: str) -> None:
        self._console.appendPlainText(message)
        self.statusBar().showMessage(message, 5000)
