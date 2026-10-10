"""Main application window — Phase 4a integration.

Adds on top of Phase 3:
- Edit menu (Undo / Redo / Delete) with keyboard shortcuts
- Define menu (Grid System… → AddNodesCommand)
- Assign menu (Restraints…, Loads…) — both gated by current selection
- modelMutated path: command-driven re-renders preserve camera/selection
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from opensees_studio import __version__
from opensees_studio.commands import (
    AddElementLoadsCommand,
    AddElementsCommand,
    AddEqualDOFConstraintCommand,
    AddNodalLoadsCommand,
    AddNodesCommand,
    AddSectionsCommand,
    AssignMaterialCommand,
    AssignSectionCommand,
    DeleteElementsCommand,
    DeleteNodesCommand,
    FixDuplicatesCommand,
    MeshCommand,
    MirrorCommand,
    MoveNodesCommand,
    ReplaceElementsCommand,
    ReplicateCommand,
    SetCoordSystemsCommand,
    SetMassCommand,
    SetRestraintCommand,
)
from opensees_studio.core import (
    SUPPORTED_NDF,
    ElasticMembranePlateSection,
    Project,
    ShellMITC4Element,
    UnitConverter,
    UnitSystem,
    build_portal_frame,
    frame_grid,
    labels_for,
    make_default_section,
)
from opensees_studio.core.geometry.ordering import QuadOrderError, order_quad_nodes
from opensees_studio.core.help import ACTION_TOPICS, TOPIC_PROPERTY
from opensees_studio.core.model_check import check_model
from opensees_studio.services import PROJECT_FILE_SUFFIX
from opensees_studio.services.deformation import (
    linear_static_auto_scale,
    modal_to_deformation,
    peak_static_displacement,
    static_to_deformation,
)
from opensees_studio.services.element_forces import (
    ForceComponent,
    extract_diagram_data,
)
from opensees_studio.services.element_forces import (
    auto_scale as force_diagram_auto_scale,
)
from opensees_studio.services.opensees_script import case_label, export_script
from opensees_studio.services.results import (
    ModalResults,
    PushoverResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)
from opensees_studio.services.shell_fields import shell_elements
from opensees_studio.viewmodels import AnalysisRunner, ProjectViewModel
from opensees_studio.views.canvas3d import ModelCanvas
from opensees_studio.views.canvas3d.diagram_renderer import DiagramRenderer
from opensees_studio.views.canvas3d.model_renderer import RendererMode
from opensees_studio.views.canvas3d.shell_contour_renderer import ShellContourRenderer
from opensees_studio.views.dialogs import (
    AddNodeDialog,
    AnalysisCaseManagerDialog,
    AssignBeamIntegrationDialog,
    AssignDistributedLoadDialog,
    AssignElastomericBearingDialog,
    AssignEqualDOFDialog,
    AssignGeomTransfDialog,
    AssignHingeDialog,
    AssignLoadDialog,
    AssignMassesDialog,
    AssignMaterialDialog,
    AssignSectionDialog,
    AssignSupportDialog,
    AssignZeroLengthSectionDialog,
    CoordinateGridSystemsDialog,
    DisplayOptionsDialog,
    DuplicatesDialog,
    DxfImportDialog,
    FrameWizard,
    FrictionLibraryDialog,
    GroundMotionsDialog,
    LinearTimeSeriesDialog,
    MaterialLibraryDialog,
    MaterialTesterDialog,
    MeshDialog,
    MirrorDialog,
    ModelCheckDialog,
    MoveDialog,
    PathTimeSeriesDialog,
    PlainPatternDialog,
    ReplicateDialog,
    RunAnalysisDialog,
    SectionLibraryDialog,
    UniformExcitationDialog,
    member_sections,
)
from opensees_studio.views.docks import (
    DeformedShapeView,
    ForceDiagramView,
    HysteresisView,
    ModeShapeAnimator,
    PropertyEditorDock,
    PushoverCurveView,
    ResponseSpectrumView,
    ResultsPanel,
    ShellContourView,
    TimeHistoryView,
)
from opensees_studio.views.help_window import HelpController
from opensees_studio.views.tools import (
    DrawFrameTool,
    DrawNodeTool,
    DrawTrussTool,
    SelectTool,
    ToolController,
)

#: First entry of the export dialog's case list: no analysis block in the script.
EXPORT_MODEL_ONLY = "Model only"


class MainWindow(QMainWindow):
    """Top-level application shell."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenSees Studio")
        self.resize(1600, 1000)

        self._vm = ProjectViewModel(self)
        self._runner = AnalysisRunner(self)
        self._latest_results: object = None  # last analysis output (any kind)
        self._analysis_error_box: QMessageBox | None = None  # last failure report
        self._run_dialog: RunAnalysisDialog | None = None  # open while a Run dialog is shown
        self._post_dock: QDockWidget | None = None  # the active post-processing dock
        self._post_units_refresh: Callable[[], None] | None = None  # re-show the dock in new units
        self._diagram_renderer: DiagramRenderer | None = None  # built lazily once canvas exists
        self._show_node_labels = False
        self._show_element_labels = False
        self._user_close_requested = False  # File → Quit sets this before close()

        self._build_central_canvas()
        self._tool_controller = ToolController(self._canvas, self._vm, self)
        self._select_tool = SelectTool(self._canvas, self._vm, self)
        self._draw_frame_tool: DrawFrameTool | None = None  # lazy-created on activation
        self._draw_node_tool: DrawNodeTool | None = None
        self._draw_truss_tool: DrawTrussTool | None = None
        self._material_tester_dlg: MaterialTesterDialog | None = None  # non-modal, reused
        self._ground_motions_dlg: GroundMotionsDialog | None = None  # non-modal, reused

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
        self._contour_renderer = ShellContourRenderer(self._canvas)

    def _build_docks(self) -> None:
        # Model tree (left)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabel("Model")
        # Allow Ctrl+click / Shift+click to build up a multi-row selection,
        # so Assign → Joint → Zero-Length Section (and other multi-entity
        # commands) work directly from the tree.
        self._tree.setSelectionMode(
            QTreeWidget.SelectionMode.ExtendedSelection,
        )
        self._tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        # Top-level category items, populated lazily on refresh.
        self._tree_categories: dict[str, QTreeWidgetItem] = {}
        for label in (
            "Nodes",
            "Elements",
            "Materials",
            "Sections",
            "Time Series",
            "Patterns",
            "Analyses",
        ):
            cat = QTreeWidgetItem([label])
            self._tree_categories[label] = cat
            self._tree.addTopLevelItem(cat)
        tree_dock = QDockWidget("Model Explorer", self)
        tree_dock.setWidget(self._tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, tree_dock)

        self._props = PropertyEditorDock()
        self._props.on_apply_mass = self._on_apply_mass
        self._props.on_change_element_type = self._on_change_element_type
        self._props.on_change_element_material = self._on_change_element_material
        self._props.on_change_element_section = self._on_change_element_section
        self._props.on_change_element_fields = self._on_change_element_fields
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
        self._act_new = QAction("&New (3D Frame)", self, shortcut=QKeySequence.StandardKey.New)
        self._act_new_2d = QAction("New &2D Frame…", self)
        self._act_new_2d_truss = QAction("New 2D &Truss", self)
        self._act_open = QAction("&Open…", self, shortcut=QKeySequence.StandardKey.Open)
        self._act_save = QAction("&Save", self, shortcut=QKeySequence.StandardKey.Save)
        self._act_save_as = QAction("Save &As…", self, shortcut=QKeySequence.StandardKey.SaveAs)
        self._act_import_dxf = QAction("&DXF Drawing…", self)
        self._act_export_script = QAction("OpenSees &script (.py)…", self)
        self._act_quit = QAction("&Quit", self, shortcut=QKeySequence.StandardKey.Quit)

        # Edit (created from QUndoStack so text auto-tracks "Undo Add 4 nodes" etc.)
        self._act_undo = self._vm.undo_stack.createUndoAction(self, "Undo")
        self._act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self._act_redo = self._vm.undo_stack.createRedoAction(self, "Redo")
        self._act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self._act_delete = QAction(
            "&Delete selection", self, shortcut=QKeySequence.StandardKey.Delete
        )
        self._act_clear_selection = QAction("Clear &selection", self, shortcut="Esc")
        self._act_select_all = QAction("Select &all", self, shortcut="Ctrl+A")

        # Edit → transforms
        self._act_move = QAction("&Move…", self, shortcut="Ctrl+M")
        self._act_replicate = QAction("&Replicate…", self, shortcut="Ctrl+Shift+R")
        self._act_check_duplicates = QAction("Check Model for &Duplicates…", self)
        self._act_mesh = QAction("&Mesh…", self)
        self._act_mirror = QAction("Mirr&or…", self)

        # Tools (exclusive)
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self._act_tool_select = QAction("Se&lect", self, checkable=True, checked=True)
        self._act_tool_draw_node = QAction("Draw &Node", self, checkable=True, shortcut="F4")
        self._act_tool_draw_frame = QAction("&Draw Frame", self, checkable=True, shortcut="F2")
        self._act_tool_draw_truss = QAction("Draw &Truss", self, checkable=True, shortcut="F3")
        self._tool_group.addAction(self._act_tool_select)
        self._tool_group.addAction(self._act_tool_draw_node)
        self._tool_group.addAction(self._act_tool_draw_frame)
        self._tool_group.addAction(self._act_tool_draw_truss)

        # Define
        self._act_grid = QAction("&Coordinate System/Grids…", self, shortcut="Ctrl+G")
        self._act_add_node = QAction("Add &Node…", self, shortcut="Ctrl+N")
        self._act_create_shell = QAction("Create S&hell from 4 Nodes…", self)
        self._act_frame_wizard = QAction("Create Portal &Frame…", self)
        self._act_material_library = QAction("&Material Library…", self, shortcut="Ctrl+Shift+M")
        self._act_friction_library = QAction("&Friction Models…", self)
        self._act_material_tester = QAction("Material &Tester…", self, shortcut="Ctrl+Shift+T")
        self._act_ground_motions = QAction("&Ground Motions…", self, shortcut="Ctrl+Shift+G")
        self._act_section_library = QAction("&Section Library…", self, shortcut="Ctrl+Shift+S")
        self._act_add_linear_ts = QAction("Add &Linear TimeSeries…", self)
        self._act_add_path_ts = QAction("Add &Path TimeSeries…", self)
        self._act_add_plain_pattern = QAction("Add &Plain Load Pattern…", self)
        self._act_add_uniform_excitation = QAction("Add &Uniform Excitation…", self)

        # Assign
        # Assign — organized as Joint (nodes) / Frame (elements) for SAP2000 parity.
        self._act_assign_support = QAction("&Restraints…", self, shortcut="Ctrl+R")
        self._act_assign_masses = QAction("&Masses…", self)
        self._act_assign_equal_dof = QAction("&EqualDOF…", self)
        self._act_assign_load = QAction("&Point Loads…", self, shortcut="Ctrl+L")
        self._act_assign_zls = QAction("&Zero-Length Section…", self)
        self._act_assign_bearing = QAction("&Bearing…", self)
        self._act_assign_distributed_load = QAction("&Distributed Load…", self)
        self._act_assign_hinge = QAction("Plastic &Hinge…", self)
        self._act_assign_section = QAction("S&ection…", self)
        self._act_assign_material = QAction("&Material…", self)
        self._act_assign_geom_transf = QAction("&Geometric Transformation…", self)
        self._act_assign_integration = QAction("Beam &Integration…", self)

        # Display (post-processing)
        self._act_show_deformed = QAction("Show &Deformed Shape", self)
        self._act_show_mode_shape = QAction("&Animate Mode Shape", self)
        self._act_show_force_diagram = QAction("Show &Force Diagram…", self)
        self._act_shell_contours = QAction("Show Shell &Contours…", self)
        self._act_show_time_history = QAction("&Time-History Plot…", self)
        self._act_export_th_animation = QAction("Export Time-History &Animation…", self)
        self._act_show_hysteresis = QAction("&Hysteresis Plot…", self)
        self._act_show_pushover = QAction("Show &Pushover Curve…", self)
        self._act_show_response_spectrum = QAction("Show &Response Spectrum…", self)
        self._act_display_options = QAction("Display &Options…", self)
        self._act_back_to_model = QAction("Back to &Model View", self, shortcut="Ctrl+Shift+B")

        # Analyze
        self._act_case_manager = QAction("&Cases…", self, shortcut="Ctrl+Shift+A")
        self._act_check_model = QAction("Check &Model…", self, shortcut="F6")
        self._act_run = QAction("&Run…", self, shortcut="F5")

        # View
        self._act_zoom_extents = QAction("Zoom &Extents", self, shortcut="Ctrl+E")
        self._act_view_iso = QAction("&Isometric", self, shortcut="Ctrl+1")
        self._act_view_top = QAction("&Top (XY)", self, shortcut="Ctrl+2")
        self._act_view_front = QAction("&Front (XZ)", self, shortcut="Ctrl+3")
        self._act_view_right = QAction("&Right (YZ)", self, shortcut="Ctrl+4")
        self._act_toggle_parallel = QAction("&Parallel projection", self, checkable=True)
        self._act_show_extruded = QAction("Show &Extruded Sections", self, checkable=True)

        self._act_about = QAction("&About OpenSees Studio…", self)
        self._act_help_contents = QAction("&Help Contents (F1)", self)
        self._act_set_units = QAction("Set Display &Units…", self)

    def _annotate_help_topics(self) -> None:
        """Point every action at its help page (see ``core.help.ACTION_TOPICS``).

        One table, keyed by the action's attribute name, so an action added
        without help is visible in the coverage test rather than silently
        opening the contents page.
        """
        for attribute, topic_id in ACTION_TOPICS.items():
            action = getattr(self, attribute, None)
            if isinstance(action, QAction):
                action.setProperty(TOPIC_PROPERTY, topic_id)

    def _on_help_contents(self) -> None:
        """Help → Contents: the same F1, on the contents page."""
        self._help_controller.open_help("index")

    def _build_menu_bar(self) -> None:
        mb = self.menuBar()

        m_file = mb.addMenu("&File")
        m_file.addActions(
            [
                self._act_new,
                self._act_new_2d,
                self._act_new_2d_truss,
                self._act_open,
            ]
        )
        m_file.addSeparator()
        m_file.addActions([self._act_save, self._act_save_as])
        m_file.addSeparator()
        m_import = m_file.addMenu("&Import")
        m_import.addAction(self._act_import_dxf)
        m_export = m_file.addMenu("&Export")
        m_export.addAction(self._act_export_script)
        m_file.addSeparator()
        m_file.addAction(self._act_quit)

        m_edit = mb.addMenu("&Edit")
        m_edit.addActions([self._act_undo, self._act_redo])
        m_edit.addSeparator()
        m_edit.addActions([self._act_delete, self._act_select_all, self._act_clear_selection])
        m_edit.addSeparator()
        m_edit.addActions([self._act_move, self._act_replicate, self._act_mirror])
        m_edit.addSeparator()
        m_edit.addAction(self._act_check_duplicates)
        m_edit.addAction(self._act_mesh)

        m_define = mb.addMenu("&Define")
        m_define.addAction(self._act_grid)
        m_define.addAction(self._act_add_node)
        m_define.addAction(self._act_create_shell)
        m_define.addAction(self._act_frame_wizard)
        m_define.addSeparator()
        m_define.addActions(
            [
                self._act_material_library,
                self._act_friction_library,
                self._act_material_tester,
                self._act_ground_motions,
                self._act_section_library,
            ]
        )
        m_define.addSeparator()
        m_define.addAction(self._act_add_linear_ts)
        m_define.addAction(self._act_add_path_ts)
        m_define.addAction(self._act_add_plain_pattern)
        m_define.addAction(self._act_add_uniform_excitation)

        m_assign = mb.addMenu("&Assign")
        # Joint submenu — operates on selected nodes.
        m_joint = m_assign.addMenu("&Joint")
        m_joint.addAction(self._act_assign_support)
        m_joint.addAction(self._act_assign_masses)
        m_joint.addAction(self._act_assign_equal_dof)
        m_joint.addAction(self._act_assign_load)
        m_joint.addAction(self._act_assign_zls)
        m_joint.addAction(self._act_assign_bearing)
        # Frame submenu — operates on selected frame elements.
        m_frame = m_assign.addMenu("&Frame")
        m_frame.addAction(self._act_assign_section)
        m_frame.addAction(self._act_assign_material)
        m_frame.addAction(self._act_assign_geom_transf)
        m_frame.addAction(self._act_assign_integration)
        m_frame.addSeparator()
        m_frame.addAction(self._act_assign_distributed_load)
        m_frame.addAction(self._act_assign_hinge)

        m_analyze = mb.addMenu("&Analyze")
        m_analyze.addAction(self._act_case_manager)
        m_analyze.addSeparator()
        m_analyze.addAction(self._act_check_model)
        m_analyze.addAction(self._act_run)

        m_display = mb.addMenu("&Display")
        m_display.addActions([self._act_show_deformed, self._act_show_mode_shape])
        m_display.addAction(self._act_show_force_diagram)
        m_display.addAction(self._act_shell_contours)
        m_display.addSeparator()
        m_display.addAction(self._act_show_time_history)
        m_display.addAction(self._act_export_th_animation)
        m_display.addAction(self._act_show_hysteresis)
        m_display.addAction(self._act_show_pushover)
        m_display.addAction(self._act_show_response_spectrum)
        m_display.addSeparator()
        m_display.addAction(self._act_display_options)
        m_display.addSeparator()
        m_display.addAction(self._act_back_to_model)

        m_view = mb.addMenu("&View")
        m_view.addAction(self._act_zoom_extents)
        m_view.addSeparator()
        m_view.addActions(
            [self._act_view_iso, self._act_view_top, self._act_view_front, self._act_view_right]
        )
        m_view.addSeparator()
        m_view.addAction(self._act_toggle_parallel)
        m_view.addAction(self._act_show_extruded)

        m_options = mb.addMenu("&Options")
        m_options.addAction(self._act_set_units)

        m_help = mb.addMenu("&Help")
        m_help.addAction(self._act_help_contents)
        m_help.addSeparator()
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
        # SAP2000-style "Level" combo: when the user is in Top / Front /
        # Right mode AND the grid has multiple perpendicular-axis lines,
        # this picks which one is active for drawing + snap filtering.
        tb.addWidget(QLabel("Level: "))
        self._level_combo = QComboBox()
        self._level_combo.setMinimumWidth(120)
        self._level_combo.setToolTip(
            "Active plan / elevation level. Click a view button first "
            "(Top, Front, Right) to populate the list from the grid."
        )
        self._level_combo.currentIndexChanged.connect(self._on_level_changed)
        tb.addWidget(self._level_combo)
        tb.addSeparator()
        tb.addAction(self._act_toggle_parallel)
        tb.addAction(self._act_show_extruded)

    def _build_tools_toolbar(self) -> None:
        tb = QToolBar("Tools", self)
        tb.setMovable(True)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tb)
        tb.addAction(self._act_tool_select)
        tb.addAction(self._act_tool_draw_node)
        tb.addAction(self._act_tool_draw_frame)
        tb.addAction(self._act_tool_draw_truss)

    def _build_status_bar(self) -> None:
        self._status_label = QLabel("No project")
        self.statusBar().addPermanentWidget(self._status_label)

        # SAP2000-style bottom-right unit picker. Drives the same state
        # as Options → Set Display Units — changes here are instantly
        # reflected in the menu dialog (and vice-versa).
        self._units_combo = QComboBox()
        self._units_combo.setToolTip(
            "Display units — results, diagrams and tables convert to this "
            "system. The model keeps the units its values were entered in."
        )
        for u in UnitSystem:
            self._units_combo.addItem(u.value, u)
        self._units_combo.currentIndexChanged.connect(
            self._on_units_combo_changed,
        )
        self.statusBar().addPermanentWidget(QLabel("Units:"))
        self.statusBar().addPermanentWidget(self._units_combo)

        self.statusBar().showMessage("Ready")

    def _on_units_combo_changed(self, _idx: int) -> None:
        """Status-bar unit picker → ``project.meta.display_units``.

        Qt stores the userData as a bare string (UnitSystem inherits
        from str), so we re-cast to the enum before writing through
        and logging. The model's own system is untouched, and every view
        that shows a number is refreshed with the new conversion.
        """
        if self._vm.project is None:
            return

        raw = self._units_combo.currentData()
        if raw is None:
            return
        chosen = raw if isinstance(raw, UnitSystem) else UnitSystem(str(raw))
        if chosen is self._current_display_units():
            return
        self._set_display_units(chosen)

    def _current_display_units(self) -> UnitSystem:
        """The system results are shown in (the model's own when none was picked)."""
        if self._vm.project is None:
            return UnitSystem.SI_M_N
        meta = self._vm.project.meta
        return meta.display_units if meta.display_units is not None else meta.units

    def _set_display_units(self, chosen: UnitSystem) -> None:
        """Change the display system and refresh everything that shows a number."""
        if self._vm.project is None:
            return
        self._vm.project.meta.display_units = chosen
        self._vm.mark_dirty()
        self._sync_units_combo()
        self._log(f"Display units set to {chosen.value}.")
        self._apply_display_units()

    def _apply_display_units(self) -> None:
        """Re-render every result view in the project's current display units.

        The model is untouched — OpenSees numbers do not move — but each number
        read off a diagram, table or curve is converted, so a unit change is
        visible without re-running anything.
        """
        if self._vm.project is None:
            return
        converter = UnitConverter.of(self._vm.project.meta)
        # Results panel: displacements, reactions, element forces, curves.
        self._results_panel.refresh(self._vm.project)
        # Active post-processing dock (diagram, deformed shape, plots).
        if self._post_units_refresh is not None:
            self._post_units_refresh()
        elif self._latest_results is not None:
            self._canvas.render()
        self._log(
            f"Displayed values converted to {converter.target.value} (model units unchanged).",
        )

    def _register_units_refresh(
        self,
        view: Any,
        after: Callable[[], None] | None = None,
    ) -> None:
        """Remember how to re-show ``view`` when the display units change.

        ``view`` must expose ``set_units(UnitConverter)``; ``after`` re-applies
        whatever the dock draws (a diagram overlay, a deformed shape). The dock
        being torn down, or another project being opened, drops the callback.
        """
        project = self._vm.project

        def _refresh() -> None:
            if self._post_dock is None or self._vm.project is not project:
                return
            view.set_units(UnitConverter.of(project.meta))
            if after is not None:
                after()

        self._post_units_refresh = _refresh

    def _sync_units_combo(self) -> None:
        """Reflect the project's current display units in the status-bar combo.

        Called after project load / menu-based unit change so the
        status-bar widget stays consistent with the model state. When the
        display system differs from the model's, the tooltip says so — the
        typed values are in the model's system, not in the picker's.
        """
        if self._vm.project is None:
            return
        target = self._current_display_units()
        idx = self._units_combo.findData(target)
        if idx >= 0 and idx != self._units_combo.currentIndex():
            self._units_combo.blockSignals(True)
            self._units_combo.setCurrentIndex(idx)
            self._units_combo.blockSignals(False)
        model = self._vm.project.meta.units
        tooltip = (
            "Display units — results, diagrams and tables convert to this "
            "system. The model keeps the units its values were entered in."
        )
        if target is not model:
            tooltip += f"  Model units: {model.value} — typed values are unchanged."
        self._units_combo.setToolTip(tooltip)

    def _wire(self) -> None:
        # File
        self._act_new.triggered.connect(self._on_new)
        self._act_new_2d.triggered.connect(self._on_new_2d)
        self._act_new_2d_truss.triggered.connect(self._on_new_2d_truss)
        self._act_open.triggered.connect(self._on_open)
        self._act_save.triggered.connect(self._on_save)
        self._act_save_as.triggered.connect(self._on_save_as)
        self._act_import_dxf.triggered.connect(self._on_import_dxf)
        self._act_export_script.triggered.connect(self._on_export_script)
        self._act_quit.triggered.connect(self._on_quit)
        self._act_about.triggered.connect(self._on_about)
        self._act_help_contents.triggered.connect(self._on_help_contents)
        self._act_set_units.triggered.connect(self._on_set_units)

        # Edit
        self._act_delete.triggered.connect(self._on_delete)
        self._act_clear_selection.triggered.connect(self._on_clear_selection)
        self._act_select_all.triggered.connect(self._on_select_all)
        self._act_move.triggered.connect(self._on_move)
        self._act_replicate.triggered.connect(self._on_replicate)
        self._act_check_duplicates.triggered.connect(self._on_check_duplicates)
        self._act_mesh.triggered.connect(self._on_mesh)
        self._act_mirror.triggered.connect(self._on_mirror)

        # Tools
        self._act_tool_select.triggered.connect(self._on_select_tool)
        self._act_tool_draw_node.triggered.connect(self._on_draw_node_tool)
        self._act_tool_draw_frame.triggered.connect(self._on_draw_frame_tool)
        self._act_tool_draw_truss.triggered.connect(self._on_draw_truss_tool)
        self._tool_controller.toolChanged.connect(self._on_tool_changed)

        # Define
        self._act_grid.triggered.connect(self._on_grid_system)
        self._act_add_node.triggered.connect(self._on_add_node)
        self._act_create_shell.triggered.connect(self._on_create_shell)
        self._act_frame_wizard.triggered.connect(self._on_frame_wizard)
        self._act_material_library.triggered.connect(self._on_material_library)
        self._act_friction_library.triggered.connect(self._on_friction_library)
        self._act_material_tester.triggered.connect(self._on_material_tester)
        self._act_ground_motions.triggered.connect(self._on_ground_motions)
        self._act_section_library.triggered.connect(self._on_section_library)
        self._act_add_linear_ts.triggered.connect(self._on_add_linear_ts)
        self._act_add_path_ts.triggered.connect(self._on_add_path_ts)
        self._act_add_plain_pattern.triggered.connect(self._on_add_plain_pattern)
        self._act_add_uniform_excitation.triggered.connect(
            self._on_add_uniform_excitation,
        )

        # Assign
        self._act_assign_support.triggered.connect(self._on_assign_support)
        self._act_assign_masses.triggered.connect(self._on_assign_masses)
        self._act_assign_equal_dof.triggered.connect(self._on_assign_equal_dof)
        self._act_assign_load.triggered.connect(self._on_assign_load)
        self._act_assign_zls.triggered.connect(self._on_assign_zls)
        self._act_assign_bearing.triggered.connect(self._on_assign_bearing)
        self._act_assign_distributed_load.triggered.connect(self._on_assign_distributed_load)
        self._act_assign_hinge.triggered.connect(self._on_assign_hinge)
        self._act_assign_section.triggered.connect(self._on_assign_section)
        self._act_assign_material.triggered.connect(self._on_assign_material)
        self._act_assign_geom_transf.triggered.connect(self._on_assign_geom_transf)
        self._act_assign_integration.triggered.connect(self._on_assign_integration)

        # Analyze
        self._act_case_manager.triggered.connect(self._on_case_manager)
        self._act_check_model.triggered.connect(self._on_check_model)
        self._act_run.triggered.connect(self._on_run_analysis)

        # Display
        self._act_show_deformed.triggered.connect(self._on_show_deformed)
        self._act_show_mode_shape.triggered.connect(self._on_show_mode_shape)
        self._act_show_force_diagram.triggered.connect(self._on_show_force_diagram)
        self._act_shell_contours.triggered.connect(self._on_show_shell_contours)
        self._act_show_time_history.triggered.connect(self._on_show_time_history)
        self._act_export_th_animation.triggered.connect(self._on_export_th_animation)
        self._act_show_hysteresis.triggered.connect(self._on_show_hysteresis)
        self._act_show_pushover.triggered.connect(self._on_show_pushover)
        self._act_show_response_spectrum.triggered.connect(self._on_show_response_spectrum)
        self._act_display_options.triggered.connect(self._on_display_options)
        self._act_back_to_model.triggered.connect(self._on_back_to_model)

        # AnalysisRunner: stream log to console + show results in panel
        self._runner.log.connect(self._console.appendPlainText)
        self._runner.finished.connect(self._on_analysis_finished)
        self._runner.failed.connect(self._on_analysis_failed)
        self._runner.cancelled.connect(lambda: self._log("Analysis cancelled."))

        # View
        self._act_zoom_extents.triggered.connect(self._canvas.reset_camera)
        self._act_view_iso.triggered.connect(self._on_view_iso)
        self._act_view_top.triggered.connect(self._on_view_top)
        self._act_view_front.triggered.connect(self._on_view_front)
        self._act_view_right.triggered.connect(self._on_view_right)
        self._act_toggle_parallel.toggled.connect(self._on_toggle_parallel)
        self._act_show_extruded.toggled.connect(self._canvas.set_show_section_extrusions)

        # ViewModel
        self._vm.projectChanged.connect(self._on_project_changed)
        self._vm.modelMutated.connect(self._on_model_mutated)
        self._vm.dirtyChanged.connect(self._on_dirty_changed)
        self._vm.noticePosted.connect(lambda msg: self.statusBar().showMessage(msg, 10000))

        # Selection → properties + action enablement
        self._canvas.selection.selectionChanged.connect(self._on_selection_changed)
        self._canvas.element_tooltip = self.element_tooltip

        # Contextual help: F1 anywhere, on the topic of what is on screen.
        self._annotate_help_topics()
        self._help_controller = HelpController(self)
        self._help_controller.install()

    # ── slots: file ──────────────────────────────────────────────────
    def _on_new(self) -> None:
        if not self._confirm_discard_changes("Creating a new project"):
            return
        self._vm.new_project()

    def _on_new_2d(self) -> None:
        """Planar frame model — (ndm=2, ndf=3): Ux, Uy, Rz per joint, then the wizard.

        Right choice when beam-columns are in the mix; for a pure truss use
        'New 2D Truss' so the solver doesn't face unrestrained rotational DOFs.

        An empty 2D frame project is just an empty canvas, and the only plane it
        can build in is the wizard's XY, so the wizard opens here: it is what
        turns "new 2D frame" into a frame. Cancelling leaves the empty project,
        which is still the right start for drawing by hand.
        """
        if not self._confirm_discard_changes("Creating a new 2D frame"):
            return
        self._vm.new_project(ndm=2, ndf=3)
        self._log("New 2D frame project (ndm = 2, ndf = 3).")
        self._create_portal_frame(with_grid=True)

    def _on_new_2d_truss(self) -> None:
        """Planar truss model — (ndm=2, ndf=2): only Ux, Uy per joint.

        Matches OpenSees's ``model BasicBuilder -ndm 2 -ndf 2`` from
        the Basic Truss Example and keeps the stiffness matrix well
        posed (no empty rotational rows).
        """
        if not self._confirm_discard_changes("Creating a new project"):
            return
        self._vm.new_project(ndm=2, ndf=2)
        self._log("New empty project.")

    def _on_open(self) -> None:
        if not self._confirm_discard_changes("Opening another project"):
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open project",
            "",
            f"OpenSees Studio model (*{PROJECT_FILE_SUFFIX});;All files (*)",
        )
        if not path:
            return
        self.open_project(path)

    def open_project(self, path: str | Path) -> bool:
        """Open ``path``; offer to restore a newer pre-run snapshot if one exists.

        Returns True when the project was opened (with or without the
        recovered changes).
        """
        try:
            self._vm.open(path)
            self._log(f"Opened: {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return False
        snapshot = self._vm.pending_run_snapshot()
        if snapshot is None:
            return True
        if self._ask_restore_snapshot(snapshot):
            try:
                self._vm.restore_run_snapshot()
                self._log(f"Restored unsaved changes from {snapshot.name} (not yet saved).")
            except Exception as exc:
                QMessageBox.critical(self, "Restore failed", str(exc))
        else:
            self._vm.discard_run_snapshot()
            self._log(f"Discarded {snapshot.name}.")
        return True

    def _ask_restore_snapshot(self, snapshot: Path) -> bool:
        """Ask whether the newer pre-run snapshot should replace the file's content."""
        answer = QMessageBox.question(
            self,
            "Recover unsaved changes",
            "A snapshot written before the last analysis run is newer than this "
            "project file.\n\nRestore unsaved changes from the last analysis run?\n\n"
            f"Snapshot: {snapshot}\n"
            "Yes loads the snapshot as unsaved changes; No deletes it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return answer == QMessageBox.StandardButton.Yes

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """Close: confirm unsaved work for a user-initiated close only.

        A close the user asked for (the window-manager button, Alt+F4, File →
        Quit) confirms unsaved changes. A programmatic ``close()`` — the test
        session teardown, ``closeAllWindows()`` while shutting down — does
        not: there is nobody to answer the dialog, and a modal prompt there
        would wedge the shutdown.
        """
        user_initiated = event.spontaneous() or self._user_close_requested
        self._user_close_requested = False
        if user_initiated and not self._confirm_discard_changes("Closing the application"):
            event.ignore()
            return
        self._vm.discard_run_snapshot()
        super().closeEvent(event)

    def _on_quit(self) -> None:
        """File → Quit — a user gesture, so unsaved changes are confirmed."""
        self._user_close_requested = True
        self.close()

    def _confirm_discard_changes(self, action: str) -> bool:
        """Ask before throwing away unsaved work. True when it is safe to go on.

        ``is_dirty`` used to drive only the ``*`` in the window title, so
        closing, opening and File → New dropped the model without a word.
        Returns False when the user cancels, or chooses Save and the save
        does not go through (dialog cancelled, write failed).
        """
        if self._vm.project is None or not self._vm.is_dirty:
            return True
        answer = QMessageBox.warning(
            self,
            "Unsaved changes",
            f"{action} will discard changes that have not been saved.\n\nSave the project first?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self._on_save()
        return True

    def _on_save(self) -> bool:
        """Save to the current path (asking for one if needed). True when written."""
        if self._vm.path is None:
            return self._on_save_as()
        try:
            self._vm.save()
            self._log(f"Saved: {self._vm.path}")
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        return True

    def _on_save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save project as",
            "",
            f"OpenSees Studio model (*{PROJECT_FILE_SUFFIX})",
        )
        if not path:
            return False
        try:
            out = self._vm.save(path)
            self._log(f"Saved: {out}")
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        return True

    def _on_export_script(self) -> None:
        """File → Export → OpenSees script: the model as plain OpenSeesPy.

        The script is the command sequence the runner itself emits, so it
        cannot drift from what the solver is given (see
        ``services/opensees_script.py``).
        """
        if self._vm.project is None:
            QMessageBox.information(self, "Export script", "Open or create a project first.")
            return
        chosen, case = self._ask_export_case()
        if not chosen:
            return
        default = (self._vm.path.stem if self._vm.path is not None else "model") + ".py"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export OpenSees script",
            default,
            "Python script (*.py)",
        )
        if not path:
            return
        try:
            source = export_script(
                self._vm.project, case, version=__version__, filename=Path(path).name
            )
            Path(path).write_text(source, encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self._log(f"Exported OpenSees script: {path}")

    def _ask_export_case(self) -> tuple[bool, Any]:
        """Ask which case the script should run. ``(False, None)`` on cancel."""
        project = self._vm.project
        if project is None or not project.analyses:
            return True, None
        analyses = project.analyses
        labels = [EXPORT_MODEL_ONLY, *(case_label(c) for c in analyses)]
        choice, accepted = QInputDialog.getItem(
            self,
            "Export OpenSees script",
            "Include which analysis case?",
            labels,
            0,
            False,
        )
        if not accepted:
            return False, None
        if choice == EXPORT_MODEL_ONLY:
            return True, None
        return True, analyses[labels.index(choice) - 1]

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
        except Exception as exc:
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
        except Exception as exc:
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
                el.id
                for el in self._vm.project.elements
                if all(nid in sel_nodes for nid in el.nodes)
            }
        dlg = ReplicateDialog(len(sel_nodes), len(sel_elements), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(
                ReplicateCommand(self._vm, sel_nodes, sel_elements, dlg.offset(), dlg.n_copies())
            )
        except Exception as exc:
            QMessageBox.critical(self, "Replicate failed", str(exc))

    def _on_mirror(self) -> None:
        sel_nodes = set(self._canvas.selection.nodes)
        sel_elements = set(self._canvas.selection.elements)
        if not sel_nodes:
            QMessageBox.information(self, "Mirror", "Select one or more nodes first.")
            return
        if not sel_elements and self._vm.project is not None:
            sel_elements = {
                el.id
                for el in self._vm.project.elements
                if all(nid in sel_nodes for nid in el.nodes)
            }
        dlg = MirrorDialog(len(sel_nodes), len(sel_elements), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(
                MirrorCommand(self._vm, sel_nodes, sel_elements, dlg.plane())  # type: ignore[arg-type]
            )
        except Exception as exc:
            QMessageBox.critical(self, "Mirror failed", str(exc))

    # ── slots: tools ────────────────────────────────────────────────
    def _on_select_tool(self) -> None:
        self._tool_controller.set_active(None)

    def _has_grid_lines(self) -> bool:
        """True when some visible coordinate system carries grid lines."""
        project = self._vm.project
        if project is None:
            return False
        return any(
            cs.grid.visible
            and not cs.grid.hide_all
            and bool(cs.grid.x_lines or cs.grid.y_lines or cs.grid.z_lines)
            for cs in project.coord_systems
        )

    def _abort_tool_activation(self) -> None:
        """Fall back to Select when a draw tool refused to arm."""
        self._act_tool_select.setChecked(True)
        self._tool_controller.set_active(None)

    def _on_draw_frame_tool(self) -> None:
        if self._vm.project is None:
            self._abort_tool_activation()
            return
        if self._draw_frame_tool is None:
            self._draw_frame_tool = DrawFrameTool(self._canvas, self._vm, self)
            self._draw_frame_tool.statusChanged.connect(
                lambda msg: self.statusBar().showMessage(msg)
            )
        self._tool_controller.set_active(self._draw_frame_tool)

    def _on_draw_node_tool(self) -> None:
        if self._vm.project is None:
            self._abort_tool_activation()
            return
        if self._draw_node_tool is None:
            self._draw_node_tool = DrawNodeTool(self._canvas, self._vm, self)
            self._draw_node_tool.statusChanged.connect(
                lambda msg: self.statusBar().showMessage(msg)
            )
        self._tool_controller.set_active(self._draw_node_tool)

    def _on_draw_truss_tool(self) -> None:
        if self._vm.project is None:
            self._abort_tool_activation()
            return
        if self._draw_truss_tool is None:
            self._draw_truss_tool = DrawTrussTool(self._canvas, self._vm, self)
            self._draw_truss_tool.statusChanged.connect(
                lambda msg: self.statusBar().showMessage(msg)
            )
        self._tool_controller.set_active(self._draw_truss_tool)

    def _on_tool_changed(self, tool) -> None:  # type: ignore[no-untyped-def]
        if tool is None:
            self.statusBar().showMessage("Select tool active.", 3000)
        else:
            self.statusBar().showMessage(tool.prompt())

    # ── slots: define ────────────────────────────────────────────────
    def _on_grid_system(self) -> None:
        """Open the SAP2000-style Coordinate/Grid Systems manager."""
        if self._vm.project is None:
            self._on_new()
        proj = self._vm.project
        assert proj is not None
        dlg = CoordinateGridSystemsDialog(proj.coord_systems, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            new_systems = dlg.result_systems()
            self._vm.apply_command(SetCoordSystemsCommand(self._vm, new_systems))
            names = ", ".join(cs.name for cs in new_systems)
            self._log(f"Coordinate/Grid Systems updated: {names}.")
        except Exception as exc:
            QMessageBox.critical(self, "Grid update failed", str(exc))

    def _on_create_shell(self) -> None:
        """Define → Create Shell: a ShellMITC4 from four selected nodes.

        The selection carries no order, so the winding is derived from the
        nodes' coordinates: a shell built from a scrambled list is inverted or
        twisted, and the user has no way to express "counter-clockwise" by
        clicking.
        """
        project = self._vm.project
        if project is None:
            QMessageBox.information(self, "Create shell", "Open or create a project first.")
            return
        selected = [n for n in project.nodes if n.id in self._canvas.selection.nodes]
        if len(selected) != 4:
            QMessageBox.information(
                self,
                "Create shell",
                f"Select exactly four nodes first (you have {len(selected)}).",
            )
            return
        plate_sections = [s for s in project.sections if isinstance(s, ElasticMembranePlateSection)]
        if not plate_sections:
            QMessageBox.information(
                self,
                "Create shell",
                "A shell needs a plate section. Add one from Define → Section Library "
                "(type 'Plate Section (shell)').",
            )
            return
        if len(plate_sections) == 1:
            section = plate_sections[0]
        else:
            labels = [f"#{s.id} {s.name} (h = {s.h:g})" for s in plate_sections]
            choice, accepted = QInputDialog.getItem(
                self, "Create shell", "Plate section:", labels, 0, False
            )
            if not accepted:
                return
            section = plate_sections[labels.index(choice)]
        points = [
            (float(node.coords[0]), float(node.coords[1]), float(node.coords[2]))
            for node in selected
        ]
        try:
            order = order_quad_nodes(points)
        except QuadOrderError as exc:
            QMessageBox.critical(self, "Cannot build the shell", str(exc))
            return
        ordered = [selected[index] for index in order]
        nodes = (ordered[0].id, ordered[1].id, ordered[2].id, ordered[3].id)
        element_id = project.next_element_id()
        try:
            self._vm.apply_command(
                AddElementsCommand(
                    self._vm,
                    [ShellMITC4Element(id=element_id, nodes=nodes, section_id=section.id)],
                    text=f"Add shell {element_id}",
                )
            )
        except Exception as exc:
            QMessageBox.critical(self, "Cannot create the shell", str(exc))
            return
        self._log(
            f"Shell {element_id}: nodes {nodes}, plate section {section.id} "
            f"(winding ordered counter-clockwise)."
        )

    def _on_check_duplicates(self) -> None:
        """Edit → Check Model for Duplicates: report, then repair on request.

        The dialog reports; :class:`FixDuplicatesCommand` repairs and recomputes
        the element duplicates *after* merging the nodes, because merging two
        coincident nodes can turn two members into the same member.
        """
        project = self._vm.project
        if project is None:
            QMessageBox.information(self, "Duplicates", "Open or create a project first.")
            return
        dlg = DuplicatesDialog(project, on_select=self._select_report_row, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        command = FixDuplicatesCommand(self._vm, tolerance=dlg.tolerance())
        try:
            self._vm.apply_command(command)
        except Exception as exc:
            QMessageBox.critical(self, "Could not fix the duplicates", str(exc))
            return
        self._canvas.selection.clear()
        self._canvas.render()
        self._log(f"Duplicates: {command.report.summary()}")

    def _select_report_row(self, node_ids: Sequence[int], element_ids: Sequence[int]) -> None:
        """Highlight the nodes/elements of a report row so they can be inspected."""
        self._canvas.selection.clear()
        for node_id in node_ids:
            self._canvas.selection.select_node(node_id, additive=True)
        for element_id in element_ids:
            self._canvas.selection.select_element(element_id, additive=True)
        self._canvas.render()

    def _on_import_dxf(self) -> None:
        """File → Import → DXF Drawing: bars from a drawing, in one undo step.

        The dialog decides what the drawing means (layers, units, plane); this
        inserts the result the same way the frame wizard does, so a bad import is
        one Ctrl+Z away.
        """
        project = self._vm.project
        if project is None:
            QMessageBox.information(self, "Import DXF", "Open or create a project first.")
            return

        dialog = DxfImportDialog(project, sections=member_sections(project), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        section_id = dialog.section_choice()
        if section_id is None:
            # Section ids are allocated inside the macro, so the models must be
            # built there too: the dialog is asked for the drawing, not for bars.
            section_id = project.next_section_id()

        self._vm.undo_stack.beginMacro("Import DXF")
        try:
            if dialog.section_choice() is None:
                self._vm.apply_command(
                    AddSectionsCommand(self._vm, [make_default_section(section_id)])
                )
            bars = dialog.imported_bars(section_id)
            if bars is None:
                return
            self._vm.apply_command(AddNodesCommand(self._vm, bars.nodes))
            self._vm.apply_command(AddElementsCommand(self._vm, bars.elements))
        except Exception as exc:
            QMessageBox.critical(self, "Could not import the drawing", str(exc))
            return
        finally:
            self._vm.undo_stack.endMacro()

        self._canvas.selection.clear()
        for node in bars.nodes:
            self._canvas.selection.select_node(node.id, additive=True)
        source = dialog.source()
        self._log(f"Imported {bars.summary()} from {source.name if source else 'the drawing'}.")
        drawing = dialog.drawing()
        if drawing is not None and drawing.skipped_summary():
            self._log(drawing.skipped_summary())

    def _on_mesh(self) -> None:
        """Edit → Mesh: subdivide members and shells, and join the mesh up.

        The plan comes from ``core.mesh`` (pure geometry, tested on its own) and
        is applied by one command, so a mesh is a single undo step.
        """
        project = self._vm.project
        if project is None:
            QMessageBox.information(self, "Mesh", "Open or create a project first.")
            return
        selected = set(self._canvas.selection.elements)
        dialog = MeshDialog(
            project,
            selected_element_ids=selected,
            has_selection=bool(selected),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        plan = dialog.plan()
        if plan.is_empty:
            return
        try:
            self._vm.apply_command(MeshCommand(self._vm, plan))
        except Exception as exc:
            QMessageBox.critical(self, "Could not mesh the model", str(exc))
            return
        self._canvas.selection.clear()
        for node in plan.new_nodes:
            self._canvas.selection.select_node(node.id, additive=True)
        self._canvas.render()
        self._log(f"Mesh: {plan.summary()}")

    def _on_frame_wizard(self) -> None:
        """Define → Create Portal Frame: a parametric 2D frame, one undo step.

        This builds a frame into whatever project is open and touches nothing
        else. ``File → New 2D Frame`` (:meth:`_on_new_2d`) asks for the matching
        grid as well, because there the wizard is the whole point of the menu
        entry rather than one of the ways to draw a member.
        """
        self._create_portal_frame(with_grid=False)

    def _create_portal_frame(self, *, with_grid: bool) -> None:
        """Collect the wizard's answers and insert the frame (and, if asked, its grid).

        The geometry comes from ``core.frames``; this only collects it, resolves
        the two section choices (creating the canonical default one *inside* the
        macro when the project has none) and inserts the result.
        """
        project = self._vm.project
        if project is None:
            QMessageBox.information(self, "Portal frame", "Open or create a project first.")
            return
        if (project.ndm, project.ndf) not in SUPPORTED_NDF:
            QMessageBox.information(
                self,
                "Portal frame",
                "A plane frame needs a 2D frame model (ndm = 2, ndf = 3) or a 3D frame "
                f"model (ndm = 3, ndf = 6); this project is ndm = {project.ndm}, "
                f"ndf = {project.ndf}.",
            )
            return

        sections = [s for s in project.sections if not isinstance(s, ElasticMembranePlateSection)]
        wizard = FrameWizard(
            sections,
            ndm=project.ndm,
            ndf=project.ndf,
            length_unit=labels_for(project.meta.units).length,
            parent=self,
        )
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return
        column_id, rafter_id = wizard.section_choice()

        self._vm.undo_stack.beginMacro("Create portal frame")
        grid = None
        try:
            if column_id is None or rafter_id is None:
                section = make_default_section(project.next_section_id())
                self._vm.apply_command(AddSectionsCommand(self._vm, [section]))
                column_id = rafter_id = section.id
            spec = wizard.spec(column_section_id=column_id, rafter_section_id=rafter_id)
            frame = build_portal_frame(
                spec,
                ndm=project.ndm,
                ndf=project.ndf,
                first_node_id=project.next_node_id(),
                first_element_id=project.next_element_id(),
            )
            self._vm.apply_command(AddNodesCommand(self._vm, frame.nodes))
            self._vm.apply_command(AddElementsCommand(self._vm, frame.elements))
            if with_grid:
                # The same undo step as the frame: one Ctrl+Z takes both back.
                grid = frame_grid(spec)
                self._vm.apply_command(
                    SetCoordSystemsCommand(self._vm, [*project.coord_systems, grid])
                )
        except Exception as exc:
            QMessageBox.critical(self, "Cannot create the frame", str(exc))
            return
        finally:
            self._vm.undo_stack.endMacro()

        # Leave the frame selected: the next thing most users do is copy it.
        self._canvas.selection.clear()
        for node in frame.nodes:
            self._canvas.selection.select_node(node.id, additive=True)
        self._log(f"{frame.summary()} Left selected for Edit → Replicate.")
        if grid is not None:
            lines = (
                len(grid.grid.x_grid_lines)
                + len(grid.grid.y_grid_lines)
                + len(grid.grid.z_grid_lines)
            )
            self._log(f"Grid '{grid.name}' created with {lines} line(s) from the same numbers.")
            if project.ndm == 2:
                # A 2D model has one plane: show it face on, with the frame's
                # heights available as the working-plane levels.
                self._on_view_top()

    def _on_add_node(self) -> None:
        if self._vm.project is None:
            self._on_new()
        proj = self._vm.project
        assert proj is not None
        dlg = AddNodeDialog(
            next_node_id=proj.next_node_id(),
            grid=proj.grid_system,
            ndm=proj.ndm,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            node = dlg.node()
            self._vm.apply_command(
                AddNodesCommand(
                    self._vm,
                    [node],
                    text=f"Add node {node.id}",
                )
            )
            self._log(
                f"Added node {node.id} at "
                f"({node.coords[0]:g}, {node.coords[1]:g}, {node.coords[2]:g})."
            )
        except Exception as exc:
            QMessageBox.critical(self, "Add Node failed", str(exc))

    def _on_add_linear_ts(self) -> None:
        """Define → Add Linear TimeSeries…"""
        from opensees_studio.commands import AddTimeSeriesCommand

        if self._vm.project is None:
            self._on_new()
        proj = self._vm.project
        assert proj is not None
        dlg = LinearTimeSeriesDialog(
            next_ts_id=proj.next_time_series_id(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            ts = dlg.time_series()
            self._vm.apply_command(AddTimeSeriesCommand(self._vm, ts))
            self._log(
                f"Added LinearTimeSeries #{ts.id} '{ts.name}' (factor={ts.factor:g}).",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Add Linear TimeSeries failed", str(exc))

    def _on_add_path_ts(self) -> None:
        """Define → Add Path TimeSeries… — ground-motion import."""
        from opensees_studio.commands import AddTimeSeriesCommand

        if self._vm.project is None:
            self._on_new()
        proj = self._vm.project
        assert proj is not None
        dlg = PathTimeSeriesDialog(
            next_ts_id=proj.next_time_series_id(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            ts = dlg.time_series()
            self._vm.apply_command(AddTimeSeriesCommand(self._vm, ts))
            self._log(
                f"Added PathTimeSeries #{ts.id} '{ts.name}' "
                f"({len(ts.values)} points, Δt={ts.dt:g} s, "
                f"factor={ts.factor:g}).",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Add Path TimeSeries failed", str(exc))

    def _on_add_plain_pattern(self) -> None:
        """Define → Add Plain Load Pattern…"""
        from opensees_studio.commands import AddLoadPatternCommand

        if self._vm.project is None:
            self._on_new()
        proj = self._vm.project
        assert proj is not None
        if not proj.time_series:
            QMessageBox.warning(
                self,
                "Add Plain Load Pattern",
                "Define a TimeSeries first (Define → Add Linear TimeSeries… "
                "or Define → Add Path TimeSeries…) so the pattern has a "
                "time-series reference.",
            )
            return
        dlg = PlainPatternDialog(
            project=proj,
            next_pattern_id=proj.next_pattern_id(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            pat = dlg.pattern()
            self._vm.apply_command(AddLoadPatternCommand(self._vm, pat))
            self._log(
                f"Added PlainLoadPattern #{pat.id} '{pat.name}' (series #{pat.time_series_id}).",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Add Plain Load Pattern failed", str(exc))

    def _on_add_uniform_excitation(self) -> None:
        """Define → Add Uniform Excitation… — base ground-motion pattern."""
        from opensees_studio.commands import AddLoadPatternCommand

        if self._vm.project is None:
            self._on_new()
        proj = self._vm.project
        assert proj is not None
        if not proj.time_series:
            QMessageBox.warning(
                self,
                "Add Uniform Excitation",
                "Define a Path TimeSeries first (Define → Add Path "
                "TimeSeries…) so the pattern has a ground-motion record "
                "to reference.",
            )
            return
        dlg = UniformExcitationDialog(
            project=proj,
            next_pattern_id=proj.next_pattern_id(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            pat = dlg.pattern()
            self._vm.apply_command(AddLoadPatternCommand(self._vm, pat))
            self._log(
                f"Added UniformExcitation pattern #{pat.id} '{pat.name}' "
                f"(DOF {pat.direction}, series #{pat.accel_series_id}, "
                f"factor {pat.factor:g}).",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Add Uniform Excitation failed",
                str(exc),
            )

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
        except Exception as exc:
            QMessageBox.critical(self, "Assign Support failed", str(exc))

    def _on_assign_equal_dof(self) -> None:
        sel = sorted(self._canvas.selection.nodes)
        if len(sel) != 2 or self._vm.project is None:
            QMessageBox.information(
                self,
                "Assign EqualDOF",
                "Select exactly two nodes first.",
            )
            return
        dlg = AssignEqualDOFDialog(sel, ndf=self._vm.project.ndf, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(AddEqualDOFConstraintCommand(self._vm, dlg.constraint()))
            self._log(f"Added equalDOF constraint between nodes {sel[0]} and {sel[1]}.")
        except Exception as exc:
            QMessageBox.critical(self, "Assign EqualDOF failed", str(exc))

    def _on_assign_load(self) -> None:
        sel_nodes = set(self._canvas.selection.nodes)
        if not sel_nodes or self._vm.project is None:
            QMessageBox.information(self, "Assign Load", "Select one or more nodes first.")
            return
        from opensees_studio.core import PlainLoadPattern

        existing = [
            (p.id, p.name)
            for p in self._vm.project.load_patterns
            if isinstance(p, PlainLoadPattern)
        ]
        dlg = AssignLoadDialog(len(sel_nodes), existing_patterns=existing, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            pid = dlg.selected_pattern_id()
            new_name = dlg.new_pattern_name() if pid is None else None
            new_ts_type = dlg.new_time_series_type() if pid is None else "Linear"
            self._vm.apply_command(
                AddNodalLoadsCommand(
                    self._vm,
                    sel_nodes,
                    dlg.forces(),
                    pattern_id=pid,
                    new_pattern_name=new_name,
                    new_ts_type=new_ts_type,
                )
            )
        except Exception as exc:
            QMessageBox.critical(self, "Assign Load failed", str(exc))

    def _on_apply_mass(self, node_id: int, mass) -> None:  # type: ignore[no-untyped-def]
        """Callback from the property editor — dispatch as an undoable command."""
        try:
            self._vm.apply_command(SetMassCommand(self._vm, {node_id}, mass))
        except Exception as exc:
            QMessageBox.critical(self, "Apply mass failed", str(exc))

    # ── property editor: live-edit callbacks ─────────────────────────
    def _on_change_element_type(self, element_id: int, new_type: str) -> None:
        """User picked a different element type from the Properties dock."""
        from opensees_studio.commands import ConvertElementTypeCommand

        project = self._vm.project
        if project is None:
            return
        # Supply sensible defaults for fields the target type requires.
        defaults: dict[str, object] = {}
        if new_type in ("Truss", "CorotTruss"):
            # Prefer an existing ElasticUniaxial + a nominal area.
            from opensees_studio.core import ElasticUniaxial

            mat = next((m for m in project.materials if isinstance(m, ElasticUniaxial)), None)
            if mat is None and project.materials:
                mat = project.materials[0]
            if mat is None:
                QMessageBox.warning(
                    self,
                    "Convert element",
                    "Define a material before converting to a truss type.",
                )
                return
            defaults["material_id"] = mat.id
            defaults["area"] = 0.001
        elif new_type in ("ElasticBeamColumn", "ForceBeamColumn", "DispBeamColumn"):
            if not project.sections:
                QMessageBox.warning(
                    self,
                    "Convert element",
                    f"Define a section before converting to {new_type}.",
                )
                return
            defaults["section_id"] = project.sections[0].id
        try:
            self._vm.apply_command(
                ConvertElementTypeCommand(
                    self._vm,
                    {element_id},
                    new_type,
                    defaults=defaults,
                )
            )
            self._log(f"Element {element_id} → {new_type}.")
        except Exception as exc:
            QMessageBox.critical(self, "Convert element failed", str(exc))

    def _on_change_element_material(self, element_id: int, material_id: int) -> None:
        try:
            self._vm.apply_command(AssignMaterialCommand(self._vm, {element_id}, material_id))
        except Exception as exc:
            QMessageBox.critical(self, "Assign material failed", str(exc))

    def _on_change_element_section(self, element_id: int, section_id: int) -> None:
        try:
            self._vm.apply_command(AssignSectionCommand(self._vm, {element_id}, section_id))
        except Exception as exc:
            QMessageBox.critical(self, "Assign section failed", str(exc))

    def _on_change_element_fields(self, element_id: int, fields: dict) -> None:  # type: ignore[type-arg]
        """Inline scalar edit dispatched from Properties dock (e.g. area)."""
        from opensees_studio.commands import UpdateElementFieldsCommand

        try:
            self._vm.apply_command(UpdateElementFieldsCommand(self._vm, element_id, fields))
        except Exception as exc:
            QMessageBox.critical(self, "Edit element failed", str(exc))

    def _on_assign_zls(self) -> None:
        """Assign → Joint → Zero-Length Section: wrap 2 coincident nodes."""
        from opensees_studio.commands import AddElementsCommand
        from opensees_studio.core import ZeroLengthSectionElement

        sel = sorted(self._canvas.selection.nodes)
        if len(sel) != 2 or self._vm.project is None:
            QMessageBox.information(
                self,
                "Assign Zero-Length Section",
                "Select exactly two coincident nodes first.",
            )
            return
        # Verify coincidence — differ by more than 1e-6 in any axis is
        # a modelling error; zeroLengthSection needs coincident nodes.
        n1, n2 = (next(n for n in self._vm.project.nodes if n.id == sel[i]) for i in (0, 1))
        if any(abs(n1.coords[k] - n2.coords[k]) > 1e-6 for k in range(3)):
            QMessageBox.warning(
                self,
                "Assign Zero-Length Section",
                f"Nodes {sel[0]} and {sel[1]} are not coincident. "
                "Move one onto the other before creating the element.",
            )
            return
        if not self._vm.project.sections:
            QMessageBox.warning(
                self,
                "Assign Zero-Length Section",
                "Define a section first (Define → Section Library).",
            )
            return
        dlg = AssignZeroLengthSectionDialog(
            self._vm.project,
            (sel[0], sel[1]),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sec_id = dlg.section_id()
        if sec_id is None:
            return
        try:
            eid = self._vm.project.next_element_id()
            elem = ZeroLengthSectionElement(
                id=eid,
                nodes=(sel[0], sel[1]),
                section_id=int(sec_id),
            )
            self._vm.apply_command(AddElementsCommand(self._vm, [elem]))
            self._log(
                f"Created ZeroLengthSection {eid} "
                f"between nodes {sel[0]}-{sel[1]} (section {sec_id})."
            )
        except Exception as exc:
            QMessageBox.critical(self, "Assign Zero-Length Section failed", str(exc))

    def _on_assign_bearing(self) -> None:
        """Assign > Joint > Bearing: elastomeric or sliding isolator between two joints."""

        sel = sorted(self._canvas.selection.nodes)
        if len(sel) != 2 or self._vm.project is None:
            QMessageBox.information(
                self,
                "Assign Bearing",
                "Select exactly two nodes first (bottom, then top).",
            )
            return
        dlg = AssignElastomericBearingDialog(self._vm.project, (sel[0], sel[1]), parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._create_bearing_from_dialog(dlg)

    def _create_bearing_from_dialog(self, dlg: AssignElastomericBearingDialog) -> bool:
        """Build the bearing the dialog describes and add it undoably."""
        from opensees_studio.commands import AddElementsCommand
        from opensees_studio.core import SLIDING_BEARING_CLASSES

        if self._vm.project is None:
            return False
        try:
            eid = self._vm.project.next_element_id()
            elem = dlg.build_element(eid)
            self._vm.apply_command(AddElementsCommand(self._vm, [elem]))
        except Exception as exc:
            QMessageBox.critical(self, "Assign Bearing failed", str(exc))
            return False
        if isinstance(elem, SLIDING_BEARING_CLASSES):
            detail = f"Kinit {elem.k_init:g}, friction model {elem.friction_model_id}"
            if elem.type == "SingleFPBearing":
                detail += f", Reff {elem.r_eff:g}"
        else:
            detail = f"Kinit {elem.k_init:g}, Qd {elem.qd:g}, alpha1 {elem.alpha1:g}"
        self._log(
            f"Created {elem.type} {eid} between nodes {elem.nodes[0]}-{elem.nodes[1]} ({detail})."
        )
        return True

    def element_tooltip(self, element_id: int) -> str | None:
        """Hover text for the canvas: key parameters of a bearing, None otherwise."""
        from opensees_studio.core import BEARING_CLASSES, SLIDING_BEARING_CLASSES

        if self._vm.project is None:
            return None
        try:
            el = self._vm.project.element(element_id)
        except KeyError:
            return None
        if not isinstance(el, BEARING_CLASSES):
            return None
        if isinstance(el, SLIDING_BEARING_CLASSES):
            try:
                friction = self._vm.project.friction_model(el.friction_model_id).type
            except KeyError:
                friction = "missing"
            lines = [
                f"{el.type} #{el.id}, nodes {el.nodes[0]}-{el.nodes[1]}",
                f"Kinit = {el.k_init:g}, friction model #{el.friction_model_id} ({friction})",
            ]
            if el.type == "SingleFPBearing":
                units = self._vm.project.meta.units
                lines.append(
                    f"Reff = {el.r_eff:g}, T = 2 pi sqrt(Reff / g) = "
                    f"{el.isolated_period(units):.4g} s"
                )
            return "\n".join(lines)
        lines = [
            f"{el.type} #{el.id}, nodes {el.nodes[0]}-{el.nodes[1]}",
            f"Kinit = {el.k_init:g}, Qd = {el.qd:g}, alpha1 = {el.alpha1:g}",
            f"u_y = {el.yield_displacement:.6g}, F_y = {el.yield_force:.6g}",
        ]
        if el.alpha2:
            lines.append(f"alpha2 = {el.alpha2:g}, mu = {el.mu:g}")
        if el.type == "ElastomericBearingBoucWen":
            lines.append(f"eta = {el.eta:g}, beta = {el.beta:g}, gamma = {el.gamma:g}")
        return "\n".join(lines)

    def _on_assign_masses(self) -> None:
        """Assign → Joint → Masses: bulk-set mass on every selected node."""
        sel_nodes = set(self._canvas.selection.nodes)
        if not sel_nodes or self._vm.project is None:
            QMessageBox.information(
                self,
                "Assign Masses",
                "Select one or more nodes first.",
            )
            return
        dlg = AssignMassesDialog(len(sel_nodes), ndf=self._vm.project.ndf, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(SetMassCommand(self._vm, sel_nodes, dlg.mass_vector()))
            self._log(f"Assigned mass to {len(sel_nodes)} node(s).")
        except Exception as exc:
            QMessageBox.critical(self, "Assign Masses failed", str(exc))

    def _on_assign_distributed_load(self) -> None:
        sel_elements = set(self._canvas.selection.elements)
        if not sel_elements:
            QMessageBox.information(
                self,
                "Assign Distributed Load",
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
        except Exception as exc:
            QMessageBox.critical(self, "Assign Distributed Load failed", str(exc))

    def _on_assign_hinge(self) -> None:
        from opensees_studio.core import BeamWithHingesElement

        sel_elements = set(self._canvas.selection.elements)
        if not sel_elements or self._vm.project is None:
            QMessageBox.information(
                self,
                "Assign Hinge",
                "Select one or more elements first.",
            )
            return
        if not self._vm.project.sections:
            QMessageBox.warning(
                self,
                "Assign Hinge",
                "No sections defined. Add a section before assigning hinges.",
            )
            return
        dlg = AssignHingeDialog(len(sel_elements), self._vm.project, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.values()
        replacements = []
        for el in self._vm.project.elements:
            if el.id in sel_elements:
                replacements.append(
                    BeamWithHingesElement(
                        id=el.id,
                        name=el.name,
                        nodes=el.nodes,
                        section_i_id=vals["section_i_id"],
                        section_j_id=vals["section_j_id"],
                        lp_i=vals["lp_i"],
                        lp_j=vals["lp_j"],
                        E=vals["E"],
                        A=vals["A"],
                        Iz=vals["Iz"],
                        Iy=vals["Iy"],
                        G=vals["G"],
                        J=vals["J"],
                        geom_transf=getattr(el, "geom_transf", "Linear"),
                    )
                )
        self._vm.apply_command(ReplaceElementsCommand(self._vm, replacements))
        self._log(f"Converted {len(sel_elements)} element(s) to BeamWithHinges.")

    # ── slots: define ────────────────────────────────────────────────
    def _on_material_library(self) -> None:
        if self._vm.project is None:
            self._on_new()
        MaterialLibraryDialog(self._vm, self).exec()

    def _on_friction_library(self) -> None:
        """Define > Friction Models: friction models for the sliding bearings."""
        if self._vm.project is None:
            self._on_new()
        FrictionLibraryDialog(self._vm, self).exec()

    def _on_material_tester(self) -> None:
        # Non-modal and reused: a second trigger raises the open dialog.
        if self._vm.project is None:
            self._on_new()
        if self._material_tester_dlg is None:
            self._material_tester_dlg = MaterialTesterDialog(self._vm, self)
        self._material_tester_dlg.show()
        self._material_tester_dlg.raise_()
        self._material_tester_dlg.activateWindow()

    def _on_ground_motions(self) -> None:
        # Non-modal and reused: a second trigger raises the open dialog.
        if self._vm.project is None:
            self._on_new()
        if self._ground_motions_dlg is None:
            self._ground_motions_dlg = GroundMotionsDialog(self._vm, self)
        self._ground_motions_dlg.show()
        self._ground_motions_dlg.raise_()
        self._ground_motions_dlg.activateWindow()

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
            QMessageBox.information(
                self, "Assign Section", "Select one or more frame elements first."
            )
            return
        dlg = AssignSectionDialog(self._vm.project.sections, len(sel_elements), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(AssignSectionCommand(self._vm, sel_elements, dlg.section_id()))
        except Exception as exc:
            QMessageBox.critical(self, "Assign Section failed", str(exc))

    def _on_assign_material(self) -> None:
        if self._vm.project is None:
            return
        sel_elements = set(self._canvas.selection.elements)
        if not sel_elements:
            QMessageBox.information(
                self, "Assign Material", "Select one or more truss/zero-length elements first."
            )
            return
        dlg = AssignMaterialDialog(self._vm.project.materials, len(sel_elements), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(AssignMaterialCommand(self._vm, sel_elements, dlg.material_id()))
        except Exception as exc:
            QMessageBox.critical(self, "Assign Material failed", str(exc))

    def _selected_accepting(self, fields: dict[str, Any]) -> set[int]:
        """Selected elements that declare every one of ``fields`` (frames for a transformation)."""
        from opensees_studio.commands import AssignElementFieldsCommand

        project = self._vm.project
        if project is None:
            return set()
        selected = set(self._canvas.selection.elements)
        return {
            el.id
            for el in project.elements
            if el.id in selected and AssignElementFieldsCommand.accepts(el, fields)
        }

    def _assign_element_fields(self, title: str, ids: set[int], fields: dict[str, Any]) -> None:
        from opensees_studio.commands import AssignElementFieldsCommand

        try:
            self._vm.apply_command(AssignElementFieldsCommand(self._vm, ids, fields))
            self._log(f"{title}: {fields} on {len(ids)} element(s).")
        except Exception as exc:
            QMessageBox.critical(self, f"{title} failed", str(exc))

    def _on_assign_geom_transf(self) -> None:
        """Assign > Frame > Geometric Transformation: Linear, PDelta or Corotational."""
        project = self._vm.project
        ids = self._selected_accepting({"geom_transf": "Linear"})
        if project is None or not ids:
            QMessageBox.information(
                self, "Geometric Transformation", "Select one or more frame elements first."
            )
            return
        current = {project.element(i).geom_transf for i in ids}  # type: ignore[union-attr]
        dlg = AssignGeomTransfDialog(
            len(ids), project.ndm, current.pop() if len(current) == 1 else None, self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._assign_element_fields(
            "Geometric Transformation", ids, {"geom_transf": dlg.transf_type()}
        )

    def _on_assign_integration(self) -> None:
        """Assign > Frame > Beam Integration: rule and points of force/disp beam-columns."""
        project = self._vm.project
        ids = self._selected_accepting({"integration": "Lobatto", "integration_points": 5})
        if project is None or not ids:
            QMessageBox.information(
                self,
                "Beam Integration",
                "Select one or more force or displacement beam-column elements first.",
            )
            return
        frames = [project.element(i) for i in ids]
        rules = {el.integration for el in frames}  # type: ignore[union-attr]
        points = {el.integration_points for el in frames}  # type: ignore[union-attr]
        dlg = AssignBeamIntegrationDialog(
            len(ids),
            rules.pop() if len(rules) == 1 else None,
            points.pop() if len(points) == 1 else None,
            self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._assign_element_fields(
            "Beam Integration",
            ids,
            {"integration": dlg.rule(), "integration_points": dlg.points()},
        )

    # ── slots: analyze ──────────────────────────────────────────────
    def _on_case_manager(self) -> None:
        if self._vm.project is None:
            self._on_new()
        AnalysisCaseManagerDialog(self._vm, self).exec()

    def _on_check_model(self) -> None:
        """Analyze → Check Model: loose nodes, unconnected elements, mechanisms."""
        project = self._vm.project
        if project is None:
            QMessageBox.information(self, "Check Model", "Open or create a project first.")
            return
        report = check_model(project)
        dlg = ModelCheckDialog(
            project, report=report, on_select=self._select_report_row, parent=self
        )
        try:
            dlg.exec()
        finally:
            dlg.deleteLater()
        self._log(report.summary())

    def _review_model_before_run(self) -> bool:
        """Check the model on the way into Run; ``False`` means the run was called off.

        Errors stop at a dialog that offers *Run anyway* (the check is a linear,
        small-displacement test, so the person may know better). Warnings are
        written to the console and do not interrupt: a modeller who has seen
        "two separate parts" once does not want to click through it on every run.
        """
        project = self._vm.project
        if project is None:
            return True
        report = check_model(project)
        if report.has_errors:
            dlg = ModelCheckDialog(
                project,
                report=report,
                pre_run=True,
                on_select=self._select_report_row,
                parent=self,
            )
            try:
                proceed = dlg.exec() == QDialog.DialogCode.Accepted
            finally:
                dlg.deleteLater()
            self._log(report.summary() + (" Running anyway." if proceed else " Run cancelled."))
            return proceed
        for finding in report.warnings:
            self._log(finding.summary())
        return True

    def _on_run_analysis(self) -> None:
        if self._vm.project is None:
            QMessageBox.information(self, "Run Analysis", "Open or create a project first.")
            return
        if not self._vm.project.analyses:
            QMessageBox.information(
                self,
                "Run Analysis",
                "No analysis cases defined. Open Analyze → Cases…",
            )
            return
        if not self._review_model_before_run():
            return
        dlg = RunAnalysisDialog(self._vm, self._runner, self)
        self._run_dialog = dlg
        try:
            dlg.exec()
        finally:
            self._run_dialog = None
            self._keep_failure_report_alive(dlg)
            # The dialog connects seven signals of the long-lived runner and
            # is parented to this window, so without this it stays alive
            # after exec() returns and every later run keeps appending to
            # its log widget.
            dlg.deleteLater()

    def _keep_failure_report_alive(self, dlg: QWidget) -> None:
        """Reparent an unread failure report so it outlives the Run dialog.

        The report is created with ``WA_DeleteOnClose``, so once the user has
        closed it Qt has destroyed the C++ object while this window still holds
        the Python wrapper. ``box.parent()`` then raises ``RuntimeError``, and
        an exception raised here — inside the ``finally`` of a Qt slot — used to
        take the whole application down with it. Hence the validity check, and
        the reference being dropped when the box is gone.
        """
        box = self._analysis_error_box
        if box is None:
            return
        if not shiboken6.isValid(box):
            self._analysis_error_box = None
            return
        if box.parent() is dlg:
            box.setParent(self, box.windowFlags())
            box.show()

    def _failure_parent(self) -> QWidget:
        """The dialog that started the run while it is open, else the main window."""
        dlg = self._run_dialog
        if dlg is not None and dlg.isVisible():
            return dlg
        return self

    def _on_analysis_finished(self, results) -> None:  # type: ignore[no-untyped-def]
        self._latest_results = results
        self._results_panel.show_results(results, self._vm.project)
        self._log(f"Analysis complete: {type(results).__name__}.")
        if isinstance(results, TransientResults) and results.early_stop:
            self._log(f"Warning: transient run did not converge ({results.steps_summary()}).")
        if isinstance(results, ResponseSpectrumResults):
            for warning in results.warnings:
                self._log(f"Warning: {warning}")
        self._refresh_action_enablement()

    def _on_analysis_failed(self, report: str) -> None:
        """Show the failure report (exit code, last error, stderr tail) without blocking."""
        self._console.appendPlainText(report)
        code = self._runner.last_exit_code
        headline = "Analysis failed."
        if code is not None:
            headline = f"Analysis process exited with code {code}."
        # A child of the modal Run dialog, so it is not blocked and opens in front of it.
        box = QMessageBox(self._failure_parent())
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Analysis failed")
        box.setText(headline)
        box.setInformativeText(
            "The application and your model are unaffected. "
            "The pre-run snapshot is kept for recovery. Details below and in the Console dock."
        )
        box.setDetailedText(report)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        box.setModal(False)
        box.finished.connect(self._forget_failure_report)
        self._analysis_error_box = box
        box.show()
        box.raise_()
        box.activateWindow()
        self._log(headline)

    def report_unexpected_error(self, traceback_text: str) -> None:
        """Show an unhandled exception instead of letting the process die.

        Called by :mod:`opensees_studio.views.error_reporting`, which is what
        ``sys.excepthook`` points at while the GUI is up. The model and the
        analysis child are untouched by a Python error in a slot, so the message
        says so and points at the Console dock, where the traceback is kept.
        """
        self._console.appendPlainText(traceback_text)
        self.statusBar().showMessage("Unexpected error — see the Console dock.", 15000)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unexpected error")
        box.setText(
            "Something went wrong in the interface. Your model and any running analysis "
            "are unaffected — save your work, then report this."
        )
        box.setDetailedText(traceback_text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        box.setModal(False)
        box.show()
        box.raise_()
        box.activateWindow()

    def _forget_failure_report(self, _result: int = 0) -> None:
        """The report is closed (and, with ``WA_DeleteOnClose``, about to be deleted)."""
        self._analysis_error_box = None

    def _on_display_options(self) -> None:
        dlg = DisplayOptionsDialog(
            show_node_labels=self._show_node_labels,
            show_element_labels=self._show_element_labels,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._show_node_labels, self._show_element_labels = dlg.values()
        self._canvas.set_display_options(
            show_node_labels=self._show_node_labels,
            show_element_labels=self._show_element_labels,
        )
        self._log(
            f"Display options updated: node labels={'on' if self._show_node_labels else 'off'}, "
            f"element labels={'on' if self._show_element_labels else 'off'}."
        )

    # ── slots: display (post-processing) ────────────────────────────
    def _on_show_deformed(self) -> None:
        if not isinstance(self._latest_results, StaticResults) or self._vm.project is None:
            QMessageBox.information(
                self,
                "Deformed Shape",
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
            src = static_to_deformation(self._vm.project, self._latest_results, scale=scale)
            self._canvas._renderer.set_mode(RendererMode.DEFORMED, src)
            self._canvas.render()

        view.scaleChanged.connect(_apply)
        view.closed.connect(self._on_back_to_model)
        view.set_units(UnitConverter.of(self._vm.project.meta))
        view.set_peak_displacement(
            peak_static_displacement(self._vm.project, self._latest_results),
        )
        _apply(suggested)  # initial frame at the suggested scale
        self._register_units_refresh(view, after=lambda: _apply(view.current_scale))

    def _on_show_mode_shape(self) -> None:
        if not isinstance(self._latest_results, ModalResults) or self._vm.project is None:
            QMessageBox.information(
                self,
                "Mode Shape",
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
            src = modal_to_deformation(
                self._vm.project, self._latest_results, mode=mode, scale=scale, phase=phase
            )
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

        path, _sel = QFileDialog.getSaveFileName(
            self,
            "Export Mode Shape Animation",
            f"mode_{animator.current_mode() + 1}.mp4",
            "MP4 Video (*.mp4);;GIF Animation (*.gif);;WebM Video (*.webm)",
        )
        if not path:
            return

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
                self,
                "Export failed",
                f"Could not write the animation:\n\n{exc}\n\n"
                "MP4 export requires FFmpeg via imageio. Try .gif as a fallback.",
            )

    def _on_show_force_diagram(self) -> None:
        if not isinstance(self._latest_results, StaticResults) or self._vm.project is None:
            QMessageBox.information(
                self,
                "Force Diagram",
                "Run a Static analysis first; force diagrams visualise its element-force output.",
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
                self._vm.project,
                self._latest_results,
                component,
            )
            if data.element_ids.size == 0:
                self._log(
                    f"Nothing to draw for {component.name}: a force diagram runs "
                    "between the two ends of a line element, and no such element "
                    "returned forces (shells and quads have no ends)."
                )
            if self._diagram_renderer is not None:
                self._diagram_renderer.render(self._vm.project, data, scale)
            self._canvas.render()

        def _on_component_changed(component: ForceComponent) -> None:
            # Recompute the suggested scale for the new component and push
            # it back into the view, which will re-emit `changed`.
            data = extract_diagram_data(
                self._vm.project,
                self._latest_results,
                component,
            )
            new_scale = force_diagram_auto_scale(self._vm.project, data)
            view.set_scale_base(new_scale)

        view.componentChanged.connect(_on_component_changed)
        view.changed.connect(_render)
        view.closed.connect(self._on_back_to_model)
        view.set_units(UnitConverter.of(self._vm.project.meta))

        # Force the first render now that everything is wired.
        view._emit_changed()
        self._register_units_refresh(
            view,
            after=lambda: _render(view.current_component(), view.current_scale),
        )

    def _on_show_shell_contours(self) -> None:
        """Display → Show Shell Contours: colour the shell faces by a field.

        The dock is the control; the canvas overlay is the renderer, and the two
        talk through `ShellContourView.changed`. The scale box starts at 0 (the
        undeformed model) because a force or moment contour is read on the
        geometry it belongs to, and warping is what makes a deformation contour
        legible.
        """
        if not isinstance(self._latest_results, StaticResults) or self._vm.project is None:
            QMessageBox.information(
                self,
                "Shell Contours",
                "Run a Static analysis first: the contour shows its displacements and "
                "its shell section resultants.",
            )
            return
        if not shell_elements(self._vm.project):
            QMessageBox.information(
                self,
                "Shell Contours",
                "This model has no shell elements. A contour paints shell faces "
                "(ShellMITC4 or quad elements).",
            )
            return

        self._tear_down_post_dock()
        view = ShellContourView(n_steps=self._latest_results.n_steps)
        dock = QDockWidget("Shell Contours", self)
        dock.setWidget(view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.resize(700, 500)
        self._post_dock = dock

        def _render(field_key: str, step: int, scale: float, directions: bool) -> None:
            if not isinstance(self._latest_results, StaticResults):
                return
            self._contour_renderer.render(
                self._vm.project,
                self._latest_results,
                field_key,
                step=step,
                scale=scale,
                show_directions=directions,
                units=view.target_units,
            )
            self._canvas.render()

        view.changed.connect(_render)
        view.closed.connect(self._on_back_to_model)
        view.set_units(UnitConverter.of(self._vm.project.meta))
        # The colour bar carries a unit, so a display-unit change repaints.
        view.unitsChanged.connect(
            lambda: _render(
                view.current_field(),
                view.current_step(),
                view.current_scale(),
                view.directions_wanted(),
            ),
        )
        view._field.setFocus()
        view.emit_changed()
        self._register_units_refresh(view)

    def _best_initial_component(self):
        """Return the (component, data) pair with the largest |force|.

        Used when first opening the diagram dock so we don't show an empty
        diagram for cases where the default component happens to be zero.
        """
        best_comp = ForceComponent.N
        best_data = extract_diagram_data(self._vm.project, self._latest_results, ForceComponent.N)
        best_max = best_data.abs_max
        for comp in (
            ForceComponent.V2,
            ForceComponent.V3,
            ForceComponent.M2,
            ForceComponent.M3,
            ForceComponent.T,
        ):
            d = extract_diagram_data(self._vm.project, self._latest_results, comp)
            if d.abs_max > best_max:
                best_max, best_comp, best_data = d.abs_max, comp, d
        return best_comp, best_data

    def _on_show_time_history(self) -> None:
        if not isinstance(self._latest_results, TransientResults) or self._vm.project is None:
            QMessageBox.information(
                self,
                "Time-History Plot",
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
        view.set_units(UnitConverter.of(self._vm.project.meta))
        self._register_units_refresh(view)

    def _on_export_th_animation(self) -> None:
        """Export the deformed shape evolution over a transient analysis."""
        if not isinstance(self._latest_results, TransientResults) or self._vm.project is None:
            QMessageBox.information(
                self,
                "Export Time-History Animation",
                "Run a Transient (time-history) analysis first.",
            )
            return
        from PySide6.QtWidgets import QFileDialog, QInputDialog

        from opensees_studio.services.animation_export import (
            export_time_history_video,
        )

        # Compute a sensible scale: peak displacement → ~10% of bbox.
        # We piggy-back on the deformation service for consistency.
        # First peek at the data so we can pick `every` such that the
        # video ends up reasonable (~150 frames target).
        n_steps = self._latest_results.n_steps
        if n_steps < 1:
            QMessageBox.information(
                self,
                "Export Time-History Animation",
                "The transient run completed no steps, so there is nothing to animate.",
            )
            return
        every, ok = QInputDialog.getInt(
            self,
            "Frame decimation",
            f"Take every Nth step ({n_steps} steps available):",
            max(1, n_steps // 150),
            1,
            n_steps,
        )
        if not ok:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Time-History Animation",
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
                self._vm.project,
                self._latest_results,
                step=step,
            )
            self._canvas._renderer.set_mode(RendererMode.DEFORMED, src)
            self._canvas.render()

        try:
            self._log(f"Exporting time-history animation → {path} …")
            export_time_history_video(
                self._canvas,
                set_step,
                Path(path),
                n_steps,
                fps=30,
                every=every,
                progress=lambda i, n: self.statusBar().showMessage(
                    f"Exporting frame {i}/{n}",
                ),
            )
            self.statusBar().clearMessage()
            self._log(f"Export complete: {path}")
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export failed",
                f"Could not write the animation:\n\n{exc}\n\n"
                "MP4 export requires FFmpeg via imageio. Try .gif as a fallback.",
            )

    def _on_show_hysteresis(self) -> None:
        if not isinstance(self._latest_results, TransientResults) or self._vm.project is None:
            QMessageBox.information(
                self,
                "Hysteresis Plot",
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
        view.set_units(UnitConverter.of(self._vm.project.meta))
        self._register_units_refresh(view)

    def _on_show_pushover(self) -> None:
        if not isinstance(self._latest_results, PushoverResults):
            QMessageBox.information(
                self,
                "Pushover Curve",
                "Run a Pushover analysis first.",
            )
            return
        self._tear_down_post_dock()
        # Plot axes follow the project's units and ndf so a kip-in / ndf=3
        # Moment-Curvature model shows "in" / "kip·in" (or "1/in") rather than
        # hard-coded SI m / N. The display conversion is applied by the view.
        units = self._vm.project.meta.units if self._vm.project is not None else UnitSystem.SI_M_N
        display = self._vm.project.meta.display_units if self._vm.project is not None else None
        ndf = self._vm.project.ndf if self._vm.project is not None else 6
        view = PushoverCurveView(units=units, ndf=ndf, display_units=display)
        view.set_results(self._latest_results)
        dock = QDockWidget("Pushover Curve", self)
        dock.setWidget(view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.resize(700, 500)
        self._post_dock = dock
        view.closed.connect(self._on_back_to_model)
        self._register_units_refresh(view)

    def _on_show_response_spectrum(self) -> None:
        if (
            not isinstance(self._latest_results, ResponseSpectrumResults)
            or self._vm.project is None
        ):
            QMessageBox.information(
                self,
                "Response Spectrum",
                "Run a Response-Spectrum analysis first.",
            )
            return
        # Find the spectrum referenced by the case so the dock can plot it.
        case_id = self._latest_results.case_id
        case = next((c for c in self._vm.project.analyses if c.id == case_id), None)
        spectrum = None
        if case is not None and case.type == "ResponseSpectrum":
            spectrum = next((s for s in self._vm.project.spectra if s.id == case.spectrum_id), None)

        self._tear_down_post_dock()
        view = ResponseSpectrumView()
        view.set_results(self._latest_results, spectrum)
        dock = QDockWidget("Response Spectrum", self)
        dock.setWidget(view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.resize(800, 600)
        self._post_dock = dock
        view.closed.connect(self._on_back_to_model)
        view.set_units(UnitConverter.of(self._vm.project.meta))
        self._register_units_refresh(view)

    def _on_back_to_model(self) -> None:
        self._tear_down_post_dock()
        if self._diagram_renderer is not None:
            self._diagram_renderer.clear()
        self._contour_renderer.clear()
        self._canvas._renderer.set_mode(RendererMode.MODEL)
        self._canvas.render()

    def _tear_down_post_dock(self) -> None:
        if self._post_dock is not None:
            self.removeDockWidget(self._post_dock)
            self._post_dock.deleteLater()
            self._post_dock = None
        self._post_units_refresh = None

    def _on_toggle_parallel(self, on: bool) -> None:
        cam = self._canvas.camera
        cam.parallel_projection = on
        self._canvas.render()

    # ── SAP2000-style view switching + working level ───────────────
    def _on_view_iso(self) -> None:
        """Isometric: clear any working plane (full 3D snap)."""
        self._canvas.clear_working_plane()
        self._canvas.view_isometric()
        self._populate_level_combo(None)

    def _on_view_top(self) -> None:
        """Top (XY): camera looks down -Z. Level = perpendicular axis Z."""
        self._canvas.view_xy()
        self._activate_working_plane("XY")

    def _on_view_front(self) -> None:
        """Front (XZ): camera looks down -Y. Level = perpendicular axis Y."""
        self._canvas.view_xz()
        self._activate_working_plane("XZ")

    def _on_view_right(self) -> None:
        """Right (YZ): camera looks down -X. Level = perpendicular axis X."""
        self._canvas.view_yz()
        self._activate_working_plane("YZ")

    def _activate_working_plane(self, plane: str) -> None:
        """Populate the Level combo from the grid and default to the first
        ordinate on the perpendicular axis. Commits the working plane to
        the canvas so snap / drawing filter by that level."""
        ordinates = self._ordinates_for_plane(plane)
        self._populate_level_combo((plane, ordinates))
        if ordinates:
            # Default to the first level (usually 0). Sets working plane.
            self._canvas.set_working_plane(plane, ordinates[0])
        else:
            # No grid on the perpendicular axis — keep the plane active at 0.
            self._canvas.set_working_plane(plane, 0.0)

    def _ordinates_for_plane(self, plane: str) -> list[float]:
        """Return the ordinate list of the axis PERPENDICULAR to ``plane``.

        Pulls from every visible CoordinateGridSystem's Global-frame
        contribution — that's a conservative superset that works even
        when multiple coord systems overlap.
        """
        if self._vm.project is None:
            return []
        axis_to_attr = {"XY": "z_lines", "XZ": "y_lines", "YZ": "x_lines"}
        attr = axis_to_attr[plane]
        acc: set[float] = set()
        for cs in self._vm.project.coord_systems:
            if not cs.grid.visible or cs.grid.hide_all:
                continue
            ords = getattr(cs.grid, attr)
            # For non-Global systems we'd need to transform through the
            # coord system's origin+rotation. For the first cut we apply
            # a simple translation (ignore rotation) since only the
            # perpendicular component matters for plan/elevation choice.
            idx = {"z_lines": 2, "y_lines": 1, "x_lines": 0}[attr]
            for o in ords:
                acc.add(round(o + cs.coord.origin[idx], 6))
        return sorted(acc)

    def _populate_level_combo(self, state: tuple[str, list[float]] | None) -> None:
        """Fill or empty the Level combo.

        ``state`` is ``(plane_name, ordinates)`` — the combo shows each
        ordinate as e.g. "Z = 3.000". Passing ``None`` empties the
        combo (iso / no working plane).
        """
        self._level_combo.blockSignals(True)
        self._level_combo.clear()
        if state is not None and state[1]:
            plane, ordinates = state
            letter = {"XY": "Z", "XZ": "Y", "YZ": "X"}[plane]
            for o in ordinates:
                self._level_combo.addItem(f"{letter} = {o:g}", o)
            self._level_combo.setEnabled(True)
        else:
            self._level_combo.setEnabled(False)
        self._level_combo.blockSignals(False)

    def _on_level_changed(self, _idx: int) -> None:
        """User picked a different level from the combo."""
        data = self._level_combo.currentData()
        if data is None:
            return
        plane = self._canvas.working_plane_type()
        if plane is None:
            return
        self._canvas.set_working_plane(plane, float(data))

    def _on_project_changed(self, project: Project | None) -> None:
        self._canvas.show_project(project)
        self._props.set_project(project)
        self._refresh_tree(project)
        self._refresh_status()
        self._sync_units_combo()
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
            self,
            "About OpenSees Studio",
            f"<h3>OpenSees Studio {__version__}</h3>"
            "<p>A modern desktop GUI for OpenSeesPy.</p>"
            "<p>GNU Affero General Public License v3.0 — see LICENSE.</p>",
        )

    def _on_set_units(self) -> None:
        """Options → Set Display Units — SAP2000 parity.

        The selection is stored in ``project.meta.display_units`` and converts
        every number a result view shows (force diagrams, displacements,
        tables, curves). The model keeps ``project.meta.units``: the values an
        engineer typed are never rewritten.
        """
        from PySide6.QtWidgets import QInputDialog

        if self._vm.project is None:
            QMessageBox.information(
                self,
                "Set Display Units",
                "Open or create a project first.",
            )
            return
        choices = [u.value for u in UnitSystem]
        current_value = self._current_display_units().value
        current_idx = choices.index(current_value)
        choice, ok = QInputDialog.getItem(
            self,
            "Set Display Units",
            "Unit system:",
            choices,
            current=current_idx,
            editable=False,
        )
        if not ok:
            return
        new_units = next(u for u in UnitSystem if u.value == choice)
        if new_units is self._current_display_units():
            return
        self._set_display_units(new_units)

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
                child.setData(0, Qt.ItemDataRole.UserRole, (cat.text(0).split(" (")[0], it.id))
                cat.addChild(child)

        if project is None:
            for cat in self._tree_categories.values():
                cat.takeChildren()
                cat.setText(0, f"{cat.text(0).split(' (')[0]} (0)")
            return

        _fill(
            self._tree_categories["Nodes"],
            project.nodes,
            lambda n: f"#{n.id}  {n.name or ''}".strip(),
        )
        _fill(
            self._tree_categories["Elements"],
            project.elements,
            lambda e: f"#{e.id}  [{e.type}]  {e.name or ''}".strip(),
        )
        _fill(
            self._tree_categories["Materials"],
            project.materials,
            lambda m: f"#{m.id}  [{m.type}]  {m.name or ''}".strip(),
        )
        _fill(
            self._tree_categories["Sections"],
            project.sections,
            lambda s: f"#{s.id}  [{s.type}]  {s.name or ''}".strip(),
        )
        _fill(
            self._tree_categories["Time Series"],
            project.time_series,
            lambda t: f"#{t.id}  [{t.type}]  {t.name or ''}".strip(),
        )
        _fill(
            self._tree_categories["Patterns"],
            project.load_patterns,
            lambda p: f"#{p.id}  [{p.type}]  {p.name or ''}".strip(),
        )
        _fill(
            self._tree_categories["Analyses"],
            project.analyses,
            lambda a: f"#{a.id}  [{a.type}]  {a.name or ''}".strip(),
        )

    def _on_tree_selection_changed(self) -> None:
        """Sync the canvas selection with every picked Node / Element row.

        Multi-select via Ctrl+click / Shift+click populates the canvas
        selection in one atomic set_selection call — so commands like
        'Zero-Length Section' (needs exactly 2 joints) can be driven
        entirely from the tree.
        """
        node_ids: set[int] = set()
        element_ids: set[int] = set()
        for item in self._tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data is None:
                continue
            kind, entity_id = data
            if kind == "Nodes":
                node_ids.add(entity_id)
            elif kind == "Elements":
                element_ids.add(entity_id)
        if node_ids or element_ids:
            self._canvas.selection.set_selection(node_ids, element_ids)

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
        has_rs = isinstance(self._latest_results, ResponseSpectrumResults)
        n_sel = len(self._canvas.selection.nodes)
        self._act_save.setEnabled(has_project)
        self._act_save_as.setEnabled(has_project)
        self._act_import_dxf.setEnabled(has_project)
        self._act_export_script.setEnabled(has_project)
        self._act_grid.setEnabled(True)
        self._act_add_node.setEnabled(True)
        self._act_create_shell.setEnabled(has_project)
        self._act_frame_wizard.setEnabled(has_project)
        self._act_check_duplicates.setEnabled(has_project)
        self._act_check_model.setEnabled(has_project)
        self._act_mesh.setEnabled(has_project)
        self._act_assign_support.setEnabled(has_project and has_selected_nodes)
        self._act_assign_masses.setEnabled(has_project and has_selected_nodes)
        self._act_assign_equal_dof.setEnabled(has_project and n_sel == 2)
        self._act_assign_load.setEnabled(has_project and has_selected_nodes)
        # Zero-length section needs exactly two selected joints.
        self._act_assign_zls.setEnabled(has_project and n_sel == 2)
        self._act_assign_bearing.setEnabled(has_project and n_sel == 2)
        self._act_assign_distributed_load.setEnabled(has_project and has_selected_elements)
        self._act_assign_hinge.setEnabled(has_project and has_selected_elements)
        self._act_assign_geom_transf.setEnabled(has_project and has_selected_elements)
        self._act_assign_integration.setEnabled(has_project and has_selected_elements)
        self._act_delete.setEnabled(has_project and has_selection)
        self._act_move.setEnabled(has_project and has_selected_nodes)
        self._act_replicate.setEnabled(has_project and has_selected_nodes)
        self._act_mirror.setEnabled(has_project and has_selected_nodes)
        self._act_tool_draw_frame.setEnabled(has_project)
        self._act_tool_draw_node.setEnabled(has_project)
        self._act_tool_draw_truss.setEnabled(has_project)
        self._act_show_deformed.setEnabled(has_static)
        self._act_show_mode_shape.setEnabled(has_modal)
        self._act_show_force_diagram.setEnabled(has_static)
        self._act_shell_contours.setEnabled(
            has_static and bool(shell_elements(self._vm.project)) if self._vm.project else False,
        )
        self._act_show_time_history.setEnabled(has_transient)
        self._act_export_th_animation.setEnabled(has_transient)
        self._act_show_hysteresis.setEnabled(has_transient)
        self._act_show_pushover.setEnabled(has_pushover)
        self._act_show_response_spectrum.setEnabled(has_rs)
        self._act_display_options.setEnabled(has_project)
        self._act_back_to_model.setEnabled(self._post_dock is not None)

    def _log(self, message: str) -> None:
        self._console.appendPlainText(message)
        self.statusBar().showMessage(message, 5000)
