"""Main application window — Phase 4a integration.

Adds on top of Phase 3:
- Edit menu (Undo / Redo / Delete) with keyboard shortcuts
- Define menu (Grid System… → AddNodesCommand)
- Assign menu (Restraints…, Loads…) — both gated by current selection
- modelMutated path: command-driven re-renders preserve camera/selection
"""

from __future__ import annotations

import contextlib
import math
from collections.abc import Callable, Iterator, Sequence
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np
import shiboken6
from PySide6.QtCore import QEvent, QPoint, QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from opensees_studio import __version__
from opensees_studio.commands import (
    AddElementLoadsCommand,
    AddElementsCommand,
    AddEqualDOFConstraintCommand,
    AddMaterialsCommand,
    AddNodalLoadsCommand,
    AddNodesCommand,
    AddPointElementLoadsCommand,
    AddSectionsCommand,
    AddTemperatureLoadsCommand,
    AddTrapezoidalElementLoadsCommand,
    AssignMaterialCommand,
    AssignSectionCommand,
    DeleteElementsCommand,
    DeleteNodesCommand,
    FixDuplicatesCommand,
    MergeJointsCommand,
    MeshCommand,
    MirrorCommand,
    MoveNodesCommand,
    ReplaceElementsCommand,
    ReplicateCommand,
    SetCoordSystemsCommand,
    SetMassCommand,
    SetRestraintCommand,
    SetSpringCommand,
)
from opensees_studio.commands.buildings import (
    AddDiaphragmCommand,
    AddRigidLinkCommand,
    RemoveConstraintsCommand,
    SetDesignSettingsCommand,
    SetMassSourceCommand,
    SetStoreysCommand,
)
from opensees_studio.commands.groups import (
    EditGroupMembersCommand,
    SetGroupsCommand,
    SetSectionCutsCommand,
)
from opensees_studio.commands.tables import ApplyModelTablesCommand
from opensees_studio.core import (
    SUPPORTED_NDF,
    ElasticSection,
    Project,
    ShellMITC4Element,
    UnitConverter,
    UnitSystem,
    build_portal_frame,
    frame_grid,
    labels_for,
    make_default_section,
    make_default_truss_material,
)
from opensees_studio.core import selection as selection_queries
from opensees_studio.core.combinations import model_fingerprint
from opensees_studio.core.connectivity import (
    joints_on_bars,
    joints_on_shell_edges,
    loose_joints,
)
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.core.duplicates import default_tolerance
from opensees_studio.core.geometry.ordering import QuadOrderError, order_quad_nodes
from opensees_studio.core.groups import Group, colour_for, group_members
from opensees_studio.core.help import ACTION_TOPICS, TOPIC_PROPERTY
from opensees_studio.core.materials.library import is_uniaxial
from opensees_studio.core.model_check import check_model
from opensees_studio.core.reactions import ReactionRow, reaction_rows
from opensees_studio.core.sections import SHELL_SECTION_CLASSES
from opensees_studio.core.self_weight import section_weight_per_length
from opensees_studio.core.view_settings import ViewSettings
from opensees_studio.diagnostics.performance import perf
from opensees_studio.services import PROJECT_FILE_SUFFIX, engines
from opensees_studio.services.batch import StoredResults, stored_results
from opensees_studio.services.combination import MissingCaseResultsError
from opensees_studio.services.deformation import (
    linear_static_auto_scale,
    modal_to_deformation,
    peak_static_displacement,
    static_to_deformation,
)
from opensees_studio.services.element_forces import (
    DiagramData,
    ForceComponent,
    envelope_diagram_data,
    extract_diagram_data,
)
from opensees_studio.services.element_forces import (
    auto_scale as force_diagram_auto_scale,
)
from opensees_studio.services.opensees_script import case_label, export_script
from opensees_studio.services.result_store import load_results
from opensees_studio.services.results import (
    CombinationResults,
    InfluenceLineResults,
    ModalResults,
    PushoverResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)
from opensees_studio.services.results_db import database_path, delete_all_results, record_results
from opensees_studio.services.shell_fields import shell_elements
from opensees_studio.services.stability import StabilityReport
from opensees_studio.services.steel_design import steel_frame_check
from opensees_studio.viewmodels import AnalysisRunner, ProjectViewModel
from opensees_studio.viewmodels.case_results import CaseResultsCache
from opensees_studio.viewmodels.stability_checker import StabilityChecker
from opensees_studio.views.canvas3d import ModelCanvas
from opensees_studio.views.canvas3d.design_ratio_renderer import DesignRatioRenderer
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
    AssignPointElementLoadDialog,
    AssignSectionDialog,
    AssignSupportDialog,
    AssignTemperatureLoadDialog,
    AssignZeroLengthSectionDialog,
    CoordinateGridSystemsDialog,
    DisplayOptionsDialog,
    DriftCheckDialog,
    DuplicatesDialog,
    DxfImportDialog,
    FrameEndOffsetsDialog,
    FrameInsertionDialog,
    FrameModifiersDialog,
    FrameReleasesDialog,
    FrameWizard,
    FrictionLibraryDialog,
    GroundMotionsDialog,
    InfluenceLineDialog,
    LinearTimeSeriesDialog,
    MaterialLibraryDialog,
    MaterialTesterDialog,
    MeshDialog,
    MirrorDialog,
    ModelCheckDialog,
    MoveDialog,
    PathTimeSeriesDialog,
    PerformanceDialog,
    PlainPatternDialog,
    ReplicateDialog,
    RunAnalysisDialog,
    S3dImportDialog,
    SectionLibraryDialog,
    SteelDesignDialog,
    TrapezoidalLoadDialog,
    UniformExcitationDialog,
    member_sections,
)
from opensees_studio.views.dialogs.area_loads import (
    FloorLoadDialog,
    ImposedDisplacementDialog,
    SurfaceLoadDialog,
)
from opensees_studio.views.dialogs.assign_springs import AssignSpringsDialog
from opensees_studio.views.dialogs.batch_run import BatchRunDialog
from opensees_studio.views.dialogs.buildings import (
    AssignDiaphragmDialog,
    AssignRigidLinkDialog,
    MassSourceDialog,
    StoreysDialog,
)
from opensees_studio.views.dialogs.connect_joints import DivideFramesDialog, MergeJointsDialog
from opensees_studio.views.dialogs.grid_line_view import GridLineViewDialog
from opensees_studio.views.dialogs.grid_wizard import GridWizardDialog
from opensees_studio.views.dialogs.groups import (
    NEW_GROUP,
    AssignGroupDialog,
    GroupsDialog,
    SectionCutsDialog,
)
from opensees_studio.views.dialogs.load_combinations import LoadCombinationsDialog
from opensees_studio.views.dialogs.model_tables import ModelTablesDialog
from opensees_studio.views.dialogs.reactions import ReactionsDialog
from opensees_studio.views.dialogs.run_cases import RunCasesDialog
from opensees_studio.views.dialogs.seismic_loads import SeismicLoadsDialog
from opensees_studio.views.dialogs.solver_settings import SolverSettingsDialog
from opensees_studio.views.dialogs.view_colors import ViewColorsDialog
from opensees_studio.views.docks import (
    DeformedShapeView,
    DesignRatioView,
    ForceDiagramView,
    HysteresisView,
    ModeShapeAnimator,
    PropertyEditorDock,
    PushoverCurveView,
    ReactionsPanel,
    ResponseSpectrumView,
    ResultsPanel,
    ShellContourView,
    TimeHistoryView,
)
from opensees_studio.views.help_window import HelpController
from opensees_studio.views.report_pdf import write_pdf
from opensees_studio.views.tools import (
    DrawFrameTool,
    DrawNodeTool,
    DrawTrussTool,
    SelectTool,
    ToolController,
)
from opensees_studio.views.view_window import ViewWindow

#: First entry of the export dialog's case list: no analysis block in the script.
EXPORT_MODEL_ONLY = "Model only"


def _add_actions(menu: QMenu, actions: Sequence[QAction | None]) -> None:
    """Add ``actions`` to ``menu``; ``None`` is a separator."""
    for action in actions:
        if action is None:
            menu.addSeparator()
        else:
            menu.addAction(action)


def _pairs_selection(pairs: list[tuple[int, int]]) -> tuple[set[int], set[int]]:
    """``(element, node)`` fault pairs as a selection: the joints and the members."""
    return {node for _, node in pairs}, {element for element, _ in pairs}


class MainWindow(QMainWindow):
    """Top-level application shell."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"OpenSees Studio v{__version__}")
        self.resize(1600, 1000)

        self._vm = ProjectViewModel(self)
        # The solver is a separate program (Options → Solver); it may be absent.
        engines.activate(engines.load_settings().package_dir)
        self._solver = engines.current_status()  # the engine that runs the cases
        self._opensees = engines.opensees_status()  # stability check, Material Tester
        self._runner = AnalysisRunner(self)
        self._stability = StabilityChecker(self)
        self._latest_results: object = None  # last analysis output (any kind)
        # Every static / response spectrum result of the session, for load combinations.
        self._case_results = CaseResultsCache()
        self._report_extra: dict[int, tuple[str, Any]] = {}
        #: View → Grid Line View: (line label, window) while active, else None.
        self._grid_view: tuple[str, float] | None = None
        self._grid_view_window: float | None = None
        self._analysis_error_box: QMessageBox | None = None  # last failure report
        self._stability_box: QMessageBox | None = None  # last stability check answer
        self._run_dialog: RunAnalysisDialog | None = None  # open while a Run dialog is shown
        self._post_dock: QDockWidget | None = None  # the active post-processing dock
        self._post_units_refresh: Callable[[], None] | None = None  # re-show the dock in new units
        self._diagram_renderer: DiagramRenderer | None = None  # built lazily once canvas exists
        self._show_node_labels = False
        self._show_element_labels = False
        self._user_close_requested = False  # File → Quit sets this before close()
        #: Top-level menus by role, so the startup gate can disable them all at
        #: once instead of grey-out every action they contain.
        self._menus: dict[str, QMenu] = {}
        #: Nesting depth of the busy cursor (see _begin_busy / _end_busy).
        self._busy_depth = 0
        #: Secondary viewports on the same project (View → New View Window).
        self._view_windows: list[ViewWindow] = []

        self._build_central_canvas()
        self._tool_controller = ToolController(self._canvas, self._vm, self)
        self._select_tool = SelectTool(self._canvas, self._vm, self)
        self._draw_frame_tool: DrawFrameTool | None = None  # lazy-created on activation
        self._draw_node_tool: DrawNodeTool | None = None
        self._draw_truss_tool: DrawTrussTool | None = None
        self._material_tester_dlg: MaterialTesterDialog | None = None  # non-modal, reused
        self._ground_motions_dlg: GroundMotionsDialog | None = None  # non-modal, reused

        self._build_docks()
        self._log(f"OpenSees Studio {__version__} started.")
        self._log_solver_status()
        self._build_actions()
        self._build_menu_bar()
        self._build_view_toolbar()
        self._build_tools_toolbar()
        self._build_status_bar()
        self._wire()
        self._refresh_action_enablement()
        self._restore_session_state()

    # ── construction ─────────────────────────────────────────────────
    def _build_central_canvas(self) -> None:
        self._main_canvas = ModelCanvas(self)
        #: The viewport the menus and the tools act on. It starts as the main
        #: one and follows focus to a secondary ViewWindow when one is active.
        self._active_canvas: ModelCanvas = self._main_canvas
        self.setCentralWidget(self._main_canvas)
        # Diagram overlay paints onto the same plotter as the model.
        self._diagram_renderer = DiagramRenderer(self._main_canvas)
        self._contour_renderer = ShellContourRenderer(self._main_canvas)
        self._ratio_renderer = DesignRatioRenderer(self._main_canvas)

    @property
    def _canvas(self) -> ModelCanvas:
        """The focused viewport: where View-menu actions and picking land."""
        return self._active_canvas

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
        self._props.on_assign_node_restraints = self._on_assign_node_restraints
        self._props.on_assign_node_masses = self._on_assign_node_masses
        self._props.on_assign_elements = self._on_assign_elements
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
        self._reactions_panel = ReactionsPanel()
        self._reactions_dock = QDockWidget("Reactions", self)
        self._reactions_dock.setWidget(self._reactions_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._reactions_dock)
        self.tabifyDockWidget(console_dock, results_dock)
        self.tabifyDockWidget(results_dock, self._reactions_dock)
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
        self._act_import_s3d = QAction("&PORTICO Model (.s3d)…", self)
        self._act_import_s2k = QAction("SAP2000 &Text (.s2k / .$2k)…", self)
        self._act_export_script = QAction("OpenSees &script (.py)…", self)
        self._act_export_ifc = QAction("&IFC (.ifc)…", self)
        self._act_export_s2k = QAction("SAP2000 &Text (.s2k)…", self)
        self._act_export_report = QAction("&Report (HTML / PDF)…", self)
        self._act_run_batch = QAction("Run &Batch…", self)
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
        self._act_table_editing = QAction("Interactive &Table Editing…", self)
        self._act_table_editing.setShortcut("Ctrl+T")

        # Select menu: queries that add to (or invert) the current selection.
        self._act_invert_selection = QAction("&Invert Selection", self, shortcut="Ctrl+I")
        self._act_previous_selection = QAction("Get &Previous Selection", self, shortcut="Ctrl+P")
        self._act_select_all_joints = QAction("All &Joints", self)
        self._act_select_all_elements = QAction("All &Elements", self)
        self._act_select_supports = QAction("&Supported Joints", self)
        self._act_select_joints_with_mass = QAction("Joints with &Mass", self)
        self._act_select_joints_of_elements = QAction("Joints of Selected Elements", self)
        self._act_select_elements_within_joints = QAction("Elements between Selected Joints", self)
        self._act_select_weighted = QAction("Elements with Self &Weight", self)
        self._act_select_loose_joints = QAction("&Loose Joints", self)
        self._act_select_joints_in_bars = QAction("Joints &Inside Members", self)
        self._act_select_shell_edge_joints = QAction("Joints on S&hell Edges", self)

        # Edit → transforms
        self._act_move = QAction("&Move…", self, shortcut="Ctrl+M")
        self._act_replicate = QAction("&Replicate…", self, shortcut="Ctrl+Shift+R")
        self._act_check_duplicates = QAction("Check Model for &Duplicates…", self)
        self._act_mesh = QAction("&Mesh…", self)
        self._act_delete_loads = QAction("Delete &Loads…", self)
        self._act_merge_joints = QAction("Merge &Joints…", self)
        self._act_divide_frames = QAction("Divide Frames at &Joints…", self)
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
        self._act_grid_wizard = QAction("Grid &Wizard…", self)
        self._act_add_node = QAction("Add &Node…", self, shortcut="Ctrl+N")
        self._act_storeys = QAction("Store&ys…", self)
        self._act_groups = QAction("&Groups…", self)
        self._act_section_cuts = QAction("Section &Cuts…", self)
        self._act_custom_commands = QAction("Custom OpenSees Co&mmands…", self)
        self._act_assign_group = QAction("Assign to &Group…", self)
        # Ctrl+G is Coordinate System/Grids: a shared shortcut fires neither.
        self._act_assign_group.setShortcut("Ctrl+Shift+G")
        self._act_mass_source = QAction("Mass S&ource…", self)
        self._act_seismic_loads = QAction("Seismic &Loads (Equivalent Lateral Force)…", self)
        self._act_create_shell = QAction("Create S&hell from 4 Nodes…", self)
        self._act_frame_wizard = QAction("Create Portal &Frame…", self)
        self._act_truss_wizard = QAction("Create &Truss…", self)
        self._act_material_library = QAction("&Material Library…", self, shortcut="Ctrl+Shift+M")
        self._act_friction_library = QAction("&Friction Models…", self)
        self._act_material_tester = QAction("Material &Tester…", self, shortcut="Ctrl+Shift+T")
        self._act_ground_motions = QAction("&Ground Motions…", self, shortcut="Ctrl+Shift+G")
        self._act_section_library = QAction("&Section Library…", self, shortcut="Ctrl+Shift+S")
        self._act_concrete_section = QAction("&Concrete Section Wizard…", self)
        self._act_section_designer = QAction("Section &Designer…", self)
        self._act_add_linear_ts = QAction("Add &Linear TimeSeries…", self)
        self._act_add_path_ts = QAction("Add &Path TimeSeries…", self)
        self._act_add_function_ts = QAction(
            "Add &Function TimeSeries (Constant, Trig, Pulse…)…", self
        )
        self._act_add_multi_support = QAction("Add &Multi-Support Excitation…", self)
        self._act_add_plain_pattern = QAction("Add &Plain Load Pattern…", self)
        self._act_add_uniform_excitation = QAction("Add &Uniform Excitation…", self)
        self._act_load_combinations = QAction("Load &Combinations…", self)

        # Assign
        # Assign — organized as Joint (nodes) / Frame (elements) for SAP2000 parity.
        self._act_assign_support = QAction("&Restraints…", self, shortcut="Ctrl+R")
        self._act_assign_masses = QAction("&Masses…", self)
        self._act_assign_springs = QAction("S&prings…", self)
        self._act_assign_equal_dof = QAction("&EqualDOF…", self)
        self._act_assign_diaphragm = QAction("&Diaphragm…", self)
        self._act_assign_rigid_link = QAction("Rigid &Link…", self)
        self._act_remove_constraints = QAction("Remove &Constraints", self)
        self._act_assign_load = QAction("&Point Loads…", self, shortcut="Ctrl+L")
        self._act_assign_imposed_displacement = QAction("Imposed &Displacement…", self)
        self._act_assign_surface_load = QAction("&Surface Load on Shells…", self)
        self._act_assign_floor_load = QAction("&Floor Load to Frames…", self)
        self._act_assign_zls = QAction("&Zero-Length Section…", self)
        self._act_assign_bearing = QAction("&Bearing…", self)
        self._act_assign_link = QAction("&Link (twoNodeLink / TFP)…", self)
        self._act_assign_distributed_load = QAction("&Distributed Load…", self)
        self._act_assign_frame_point_load = QAction("&Point Load…", self)
        self._act_assign_hinge = QAction("Plastic &Hinge…", self)
        self._act_assign_section = QAction("S&ection…", self)
        self._act_assign_material = QAction("&Material…", self)
        self._act_assign_geom_transf = QAction("&Geometric Transformation…", self)
        self._act_assign_integration = QAction("Beam &Integration…", self)
        self._act_assign_releases = QAction("&Releases/Partial Fixity…", self)
        self._act_assign_end_offsets = QAction("&End (Length) Offsets…", self)
        self._act_assign_insertion = QAction("I&nsertion Point…", self)
        self._act_assign_modifiers = QAction("Property M&odifiers…", self)
        self._act_assign_trapezoidal_load = QAction("&Trapezoidal Load…", self)
        self._act_assign_temperature_load = QAction("Te&mperature Load…", self)
        self._act_assign_wall = QAction("RC &Wall (MVLEM)…", self)

        # Display (post-processing)
        self._act_select_results = QAction("Show Results &Of…", self)
        self._act_show_deformed = QAction("Show &Deformed Shape", self)
        self._act_show_mode_shape = QAction("&Animate Mode Shape", self)
        self._act_show_force_diagram = QAction("Show &Force Diagram…", self)
        self._act_show_reactions = QAction("Show &Reactions", self)
        self._act_show_reactions.setCheckable(True)
        self._act_reactions_table = QAction("Reactions &Table", self)
        self._act_reactions_dialog = QAction("R&eactions…", self)
        self._act_shell_contours = QAction("Show Shell &Contours…", self)
        self._act_show_time_history = QAction("&Time-History Plot…", self)
        self._act_export_th_animation = QAction("Export Time-History &Animation…", self)
        self._act_show_hysteresis = QAction("&Hysteresis Plot…", self)
        self._act_show_pushover = QAction("Show &Pushover Curve…", self)
        self._act_influence_line = QAction("&Influence Line…", self)
        self._act_show_response_spectrum = QAction("Show &Response Spectrum…", self)
        self._act_display_options = QAction("Display &Options…", self)
        self._act_back_to_model = QAction("Back to &Model View", self, shortcut="Ctrl+Shift+B")

        # Analyze
        self._act_case_manager = QAction("&Cases…", self, shortcut="Ctrl+Shift+A")
        self._act_check_model = QAction("Check &Model…", self)
        self._act_check_model.setShortcut("F6")
        self._act_run = QAction("&Run…", self, shortcut="F5")
        # Batch doors: the whole model in one child process, or a ticked subset.
        self._act_run_all = QAction("Run &All Cases", self, shortcut=QKeySequence("Shift+F5"))
        self._act_run_selected = QAction("Run Se&lected Cases…", self)
        self._act_clear_results = QAction("Delete &All Results…", self)
        self._act_steel_check = QAction("&Steel Frame Check (AISC 360-16)…", self)
        self._act_drift_check = QAction("Storey &Drift Check…", self)
        self._act_steel_ratios = QAction("Display Steel &Ratios on Model", self)
        self._act_check_stability = QAction("Check Model &Stability…", self)
        self._act_cancel_stability = QAction("&Cancel Stability Check", self)

        # View
        self._act_zoom_extents = QAction("Zoom &Extents", self, shortcut="Ctrl+E")
        self._act_view_iso = QAction("&Isometric", self, shortcut="Ctrl+1")
        self._act_view_top = QAction("&Top (XY)", self, shortcut="Ctrl+2")
        self._act_view_front = QAction("&Front (XZ)", self, shortcut="Ctrl+3")
        self._act_view_right = QAction("&Right (YZ)", self, shortcut="Ctrl+4")
        # View → Rotate: the camera turns, the model does not.
        self._act_rotate_left = QAction("↺ Rotate Left", self, shortcut=QKeySequence("Alt+Left"))
        self._act_rotate_right = QAction("↻ Rotate Right", self, shortcut=QKeySequence("Alt+Right"))
        self._act_rotate_up = QAction("⤒ Tilt Up", self, shortcut=QKeySequence("Alt+Up"))
        self._act_rotate_down = QAction("⤓ Tilt Down", self, shortcut=QKeySequence("Alt+Down"))
        self._act_spin = QAction("⟳ Spin", self, checkable=True)
        for action, tip in (
            (self._act_rotate_left, "Turn the view 15° to the left about the vertical axis"),
            (self._act_rotate_right, "Turn the view 15° to the right about the vertical axis"),
            (self._act_rotate_up, "Tilt the view 15° up"),
            (self._act_rotate_down, "Tilt the view 15° down"),
            (self._act_spin, "Turn the view continuously, to present the model"),
        ):
            action.setToolTip(tip)
        self._act_toggle_parallel = QAction("&Parallel projection", self, checkable=True)
        self._act_show_extruded = QAction("Show &Extruded Sections", self, checkable=True)
        # View → Color By: one colour, or a colour per section, material or group.
        self._act_color_none = QAction("&Single Colour", self, checkable=True)
        self._act_color_section = QAction("By &Section", self, checkable=True)
        self._act_color_material = QAction("By &Material", self, checkable=True)
        self._act_color_group = QAction("By &Group", self, checkable=True)
        self._color_by_actions = {
            "none": self._act_color_none,
            "section": self._act_color_section,
            "material": self._act_color_material,
            "group": self._act_color_group,
        }
        self._color_by_group = QActionGroup(self)
        self._color_by_group.setExclusive(True)
        for action in self._color_by_actions.values():
            self._color_by_group.addAction(action)
        self._act_color_none.setChecked(True)
        self._act_show_grids = QAction("Show &Grids", self, checkable=True, checked=True)
        self._act_grid_line_view = QAction("Grid &Line View…", self)
        self._act_show_all_objects = QAction("Show &All Objects", self)
        self._act_show_all_objects.setEnabled(False)
        self._act_show_grid_labels = QAction(
            "Show Grid &Labels", self, checkable=True, checked=True
        )

        # Camera dolly. The canvas multiplies its current zoom, so holding the
        # shortcut zooms smoothly rather than jumping to a fixed scale.
        self._act_zoom_in = QAction("Zoom &In", self, shortcut=QKeySequence("Ctrl++"))
        self._act_zoom_out = QAction("Zoom &Out", self, shortcut=QKeySequence("Ctrl+-"))

        # Per-viewport hiding. These never touch the project: the ids stay in
        # the model, they are only not drawn in this one canvas.
        self._act_hide_selected = QAction("&Hide Selected", self, shortcut=QKeySequence("Ctrl+H"))
        self._act_isolate_selected = QAction(
            "&Isolate Selected", self, shortcut=QKeySequence("Ctrl+Shift+I")
        )
        self._act_invert_visible = QAction("&Invert Visible", self)
        self._act_view_colors = QAction("&Colors…", self)

        # A second (third, …) viewport on the same project, in its own window.
        self._act_new_view = QAction(
            "New View &Window", self, shortcut=QKeySequence("Ctrl+Shift+N")
        )
        self._act_close_view = QAction("Close View Window", self)
        self._act_close_view.setEnabled(False)

        # Visibility toggles, one per ViewSettings field. _sync_visibility_actions
        # keeps their ticks truthful after any change, whichever path made it.
        self._act_vis_grids = QAction("Grids", self, checkable=True, checked=True)
        self._act_vis_grid_labels = QAction("Grid Labels", self, checkable=True, checked=True)
        self._act_vis_nodes = QAction("Nodes", self, checkable=True, checked=True)
        self._act_vis_frames = QAction("Frames", self, checkable=True, checked=True)
        self._act_vis_surfaces = QAction("Shells", self, checkable=True, checked=True)
        self._act_vis_supports = QAction("Restraints", self, checkable=True, checked=True)
        self._act_vis_constraints = QAction("Constraints", self, checkable=True, checked=True)
        self._act_vis_frame_assignments = QAction(
            "Frame Assignments", self, checkable=True, checked=True
        )
        self._act_vis_releases = QAction("Releases", self, checkable=True, checked=True)
        self._act_vis_loads = QAction("Loads", self, checkable=True, checked=True)
        # Labels are off by default, matching ViewSettings.
        self._act_vis_node_labels = QAction("Node Labels", self, checkable=True)
        self._act_vis_element_labels = QAction("Element Labels", self, checkable=True)
        self._act_vis_extruded = QAction("Extruded Sections", self, checkable=True)

        self._act_about = QAction("&About OpenSees Studio…", self)
        self._act_help_contents = QAction("&Help Contents (F1)", self)
        self._act_performance = QAction("&Performance monitor…", self)
        self._act_set_units = QAction("Set Display &Units…", self)
        self._act_solver_settings = QAction("&Solver…", self)

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
        m_import.addAction(self._act_import_s3d)
        m_import.addAction(self._act_import_s2k)
        m_export = m_file.addMenu("&Export")
        m_export.addAction(self._act_export_script)
        m_export.addAction(self._act_export_ifc)
        m_export.addAction(self._act_export_s2k)
        m_export.addAction(self._act_export_report)
        m_file.addSeparator()
        m_file.addAction(self._act_run_batch)
        m_file.addSeparator()
        m_file.addAction(self._act_quit)

        m_edit = mb.addMenu("&Edit")
        m_edit.addActions([self._act_undo, self._act_redo])
        m_edit.addSeparator()
        m_edit.addActions([self._act_delete, self._act_select_all, self._act_clear_selection])
        m_edit.addSeparator()
        m_edit.addActions([self._act_move, self._act_replicate, self._act_mirror])
        m_edit.addSeparator()
        m_edit.addAction(self._act_table_editing)
        m_edit.addAction(self._act_check_duplicates)
        m_edit.addAction(self._act_merge_joints)
        m_edit.addAction(self._act_divide_frames)
        m_edit.addAction(self._act_mesh)
        m_edit.addSeparator()
        m_edit.addAction(self._act_delete_loads)

        m_select = mb.addMenu("&Select")
        self._build_select_menu(m_select)

        m_define = mb.addMenu("&Define")
        m_define.addAction(self._act_grid)
        m_define.addAction(self._act_grid_wizard)
        m_define.addAction(self._act_storeys)
        m_define.addAction(self._act_groups)
        m_define.addAction(self._act_section_cuts)
        m_define.addAction(self._act_mass_source)
        m_define.addAction(self._act_seismic_loads)
        m_define.addAction(self._act_add_node)
        m_define.addAction(self._act_create_shell)
        m_define.addAction(self._act_frame_wizard)
        m_define.addAction(self._act_truss_wizard)
        m_define.addSeparator()
        m_define.addActions(
            [
                self._act_material_library,
                self._act_friction_library,
                self._act_material_tester,
                self._act_ground_motions,
                self._act_section_library,
                self._act_concrete_section,
                self._act_section_designer,
            ]
        )
        m_define.addSeparator()
        time_series_menu = m_define.addMenu("&Time Series")
        time_series_menu.addAction(self._act_add_linear_ts)
        time_series_menu.addAction(self._act_add_path_ts)
        time_series_menu.addAction(self._act_add_function_ts)
        self._act_constant_ts = time_series_menu.addAction("Constant...", self._on_constant_ts)
        m_define.addAction(self._act_add_plain_pattern)
        m_define.addAction(self._act_add_uniform_excitation)
        m_define.addAction(self._act_add_multi_support)
        m_define.addSeparator()
        m_define.addAction(self._act_load_combinations)
        m_define.addSeparator()
        m_define.addAction(self._act_custom_commands)

        m_assign = mb.addMenu("&Assign")
        # Joint submenu — operates on selected nodes.
        # The same lists feed the right-click menu of a selection (None = separator).
        self._joint_actions: list[QAction | None] = [
            self._act_assign_support,
            self._act_assign_masses,
            self._act_assign_springs,
            self._act_assign_equal_dof,
            self._act_assign_diaphragm,
            self._act_assign_rigid_link,
            self._act_remove_constraints,
            self._act_assign_load,
            self._act_assign_imposed_displacement,
            self._act_assign_zls,
            self._act_assign_bearing,
            self._act_assign_link,
        ]
        self._frame_actions: list[QAction | None] = [
            self._act_assign_section,
            self._act_assign_material,
            self._act_assign_geom_transf,
            self._act_assign_integration,
            None,
            self._act_assign_releases,
            self._act_assign_end_offsets,
            self._act_assign_insertion,
            self._act_assign_modifiers,
            None,
            self._act_assign_distributed_load,
            self._act_assign_trapezoidal_load,
            self._act_assign_frame_point_load,
            self._act_assign_temperature_load,
            self._act_assign_hinge,
            self._act_assign_wall,
        ]
        self._area_actions: list[QAction | None] = [
            self._act_assign_surface_load,
            self._act_assign_floor_load,
        ]
        # Joint submenu — operates on selected nodes.
        _add_actions(m_assign.addMenu("&Joint"), self._joint_actions)
        # Frame submenu — operates on selected frame elements.
        _add_actions(m_assign.addMenu("&Frame"), self._frame_actions)
        _add_actions(m_assign.addMenu("A&rea"), self._area_actions)
        m_assign.addSeparator()
        m_assign.addAction(self._act_assign_group)

        m_analyze = mb.addMenu("&Analyze")
        m_analyze.addAction(self._act_case_manager)
        m_analyze.addSeparator()
        m_analyze.addAction(self._act_check_model)
        m_analyze.addAction(self._act_check_stability)
        m_analyze.addAction(self._act_cancel_stability)
        m_analyze.addAction(self._act_run)
        m_analyze.addSeparator()
        m_analyze.addAction(self._act_run_all)
        m_analyze.addAction(self._act_run_selected)
        m_analyze.addSeparator()
        m_analyze.addAction(self._act_clear_results)

        m_display = mb.addMenu("&Display")
        m_display.addAction(self._act_select_results)
        m_display.addSeparator()
        m_display.addActions([self._act_show_deformed, self._act_show_mode_shape])
        m_display.addAction(self._act_show_force_diagram)
        m_display.addActions(
            [self._act_show_reactions, self._act_reactions_table, self._act_reactions_dialog]
        )
        m_display.addAction(self._act_shell_contours)
        m_display.addSeparator()
        m_display.addAction(self._act_show_time_history)
        m_display.addAction(self._act_export_th_animation)
        m_display.addAction(self._act_show_hysteresis)
        m_display.addAction(self._act_show_pushover)
        m_display.addAction(self._act_influence_line)
        m_display.addAction(self._act_show_response_spectrum)
        m_display.addSeparator()
        m_display.addAction(self._act_display_options)
        m_display.addSeparator()
        m_display.addAction(self._act_back_to_model)

        m_design = mb.addMenu("Desi&gn")
        m_design.addAction(self._act_steel_check)
        m_design.addAction(self._act_steel_ratios)
        m_design.addAction(self._act_drift_check)

        m_view = mb.addMenu("&View")
        m_view.addAction(self._act_zoom_in)
        m_view.addAction(self._act_zoom_out)
        m_view.addAction(self._act_zoom_extents)
        m_view.addSeparator()
        m_view.addActions(
            [self._act_view_iso, self._act_view_top, self._act_view_front, self._act_view_right]
        )
        m_rotate = m_view.addMenu("&Rotate")
        m_rotate.addActions(
            [
                self._act_rotate_left,
                self._act_rotate_right,
                self._act_rotate_up,
                self._act_rotate_down,
            ]
        )
        m_rotate.addSeparator()
        m_rotate.addAction(self._act_spin)
        m_view.addSeparator()
        m_view.addAction(self._act_toggle_parallel)
        m_view.addAction(self._act_show_extruded)
        m_color = m_view.addMenu("&Color By")
        m_color.addActions(list(self._color_by_actions.values()))
        m_view.addSeparator()
        # The model's own grid (a project entity) keeps its place next to the
        # other view furniture; the per-viewport toggles live in Visibility.
        m_view.addAction(self._act_show_grids)
        m_view.addAction(self._act_show_grid_labels)
        m_view.addSeparator()
        m_visibility = m_view.addMenu("&Visibility")
        m_visibility.addActions(
            [
                self._act_vis_grids,
                self._act_vis_grid_labels,
                self._act_vis_nodes,
                self._act_vis_frames,
                self._act_vis_surfaces,
                self._act_vis_supports,
                self._act_vis_constraints,
                self._act_vis_frame_assignments,
                self._act_vis_releases,
                self._act_vis_loads,
                self._act_vis_node_labels,
                self._act_vis_element_labels,
                self._act_vis_extruded,
            ]
        )
        m_view.addSeparator()
        m_view.addAction(self._act_hide_selected)
        m_view.addAction(self._act_isolate_selected)
        m_view.addAction(self._act_invert_visible)
        m_view.addAction(self._act_show_all_objects)
        m_view.addSeparator()
        m_view.addAction(self._act_grid_line_view)
        m_view.addAction(self._act_view_colors)
        m_view.addSeparator()
        m_view.addAction(self._act_new_view)
        m_view.addAction(self._act_close_view)

        m_options = mb.addMenu("&Options")
        m_options.addAction(self._act_set_units)
        m_options.addAction(self._act_solver_settings)

        m_help = mb.addMenu("&Help")
        m_help.addAction(self._act_help_contents)
        m_help.addSeparator()
        m_help.addAction(self._act_performance)
        m_help.addAction(self._act_about)

        self._menus = {
            "file": m_file,
            "edit": m_edit,
            "select": m_select,
            "define": m_define,
            "assign": m_assign,
            "analyze": m_analyze,
            "display": m_display,
            "view": m_view,
            "options": m_options,
            "help": m_help,
        }

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
        for action in (
            self._act_rotate_left,
            self._act_rotate_right,
            self._act_rotate_up,
            self._act_rotate_down,
            self._act_spin,
        ):
            tb.addAction(action)
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
        # Which results case the viewport represents: the layers (deformed
        # shape, diagrams, reactions) follow it.
        tb.addWidget(QLabel("Case: "))
        self._case_combo = QComboBox()
        self._case_combo.setMinimumWidth(190)
        self._case_combo.setToolTip(
            "Results case shown in the viewport. Deformed shape, force diagram, "
            "contours and reactions all read this case."
        )
        self._case_combo.currentIndexChanged.connect(self._on_case_changed)
        tb.addWidget(self._case_combo)
        self._step_back = QToolButton()
        self._step_back.setText("\u25c0")
        self._step_back.setToolTip("Previous step of this case")
        self._step_back.setEnabled(False)
        self._step_back.clicked.connect(lambda: self._shift_step(-1))
        tb.addWidget(self._step_back)
        self._step_forward = QToolButton()
        self._step_forward.setText("\u25b6")
        self._step_forward.setToolTip("Next step of this case")
        self._step_forward.setEnabled(False)
        self._step_forward.clicked.connect(lambda: self._shift_step(1))
        tb.addWidget(self._step_forward)
        self._step_label = QLabel("")
        tb.addWidget(self._step_label)
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
        self._act_import_s3d.triggered.connect(self._on_import_s3d)
        self._act_import_s2k.triggered.connect(self._on_import_s2k)
        self._act_export_script.triggered.connect(self._on_export_script)
        self._act_export_ifc.triggered.connect(self._on_export_ifc)
        self._act_export_s2k.triggered.connect(self._on_export_s2k)
        self._act_export_report.triggered.connect(self._on_export_report)
        self._act_run_batch.triggered.connect(self._on_run_batch)
        self._act_quit.triggered.connect(self._on_quit)
        self._act_about.triggered.connect(self._on_about)
        self._act_help_contents.triggered.connect(self._on_help_contents)
        self._act_performance.triggered.connect(self._on_performance)
        self._act_set_units.triggered.connect(self._on_set_units)
        self._act_solver_settings.triggered.connect(self._on_solver_settings)

        # Edit
        self._act_delete.triggered.connect(self._on_delete)
        self._act_clear_selection.triggered.connect(self._on_clear_selection)
        self._act_select_all.triggered.connect(self._on_select_all)
        self._act_table_editing.triggered.connect(self._on_table_editing)
        self._act_invert_selection.triggered.connect(self._on_invert_selection)
        self._act_previous_selection.triggered.connect(self._on_previous_selection)
        q = selection_queries
        for action, query in (
            (self._act_select_all_joints, lambda p, sel: ({n.id for n in p.nodes}, set())),
            (self._act_select_all_elements, lambda p, sel: (set(), {e.id for e in p.elements})),
            (self._act_select_supports, lambda p, sel: (q.restrained_nodes(p), set())),
            (self._act_select_joints_with_mass, lambda p, sel: (q.nodes_with_mass(p), set())),
            (self._act_select_weighted, lambda p, sel: (set(), q.weighted_elements(p))),
            (
                self._act_select_joints_of_elements,
                lambda p, sel: (q.nodes_of_elements(p, sel.elements), set()),
            ),
            (
                self._act_select_elements_within_joints,
                lambda p, sel: (set(), q.elements_within_nodes(p, sel.nodes)),
            ),
            (self._act_select_loose_joints, lambda p, sel: (set(loose_joints(p)), set())),
            (
                self._act_select_joints_in_bars,
                lambda p, sel: _pairs_selection(joints_on_bars(p, default_tolerance(p))),
            ),
            (
                self._act_select_shell_edge_joints,
                lambda p, sel: _pairs_selection(joints_on_shell_edges(p, default_tolerance(p))),
            ),
        ):
            action.triggered.connect(lambda _=False, query=query: self._select_from(query))
        self._act_move.triggered.connect(self._on_move)
        self._act_replicate.triggered.connect(self._on_replicate)
        self._act_check_duplicates.triggered.connect(self._on_check_duplicates)
        self._act_mesh.triggered.connect(self._on_mesh)
        self._act_delete_loads.triggered.connect(self._on_delete_loads)
        self._act_merge_joints.triggered.connect(self._on_merge_joints)
        self._act_divide_frames.triggered.connect(self._on_divide_frames)
        self._act_mirror.triggered.connect(self._on_mirror)

        # Tools
        self._act_tool_select.triggered.connect(self._on_select_tool)
        self._act_tool_draw_node.triggered.connect(self._on_draw_node_tool)
        self._act_tool_draw_frame.triggered.connect(self._on_draw_frame_tool)
        self._act_tool_draw_truss.triggered.connect(self._on_draw_truss_tool)
        self._tool_controller.toolChanged.connect(self._on_tool_changed)

        # Define
        self._act_grid.triggered.connect(self._on_grid_system)
        self._act_grid_wizard.triggered.connect(self._on_grid_wizard)
        self._act_show_grids.triggered.connect(self._set_grids_shown)
        self._act_show_grid_labels.triggered.connect(self._set_grid_labels_shown)
        self._act_grid_line_view.triggered.connect(self._on_grid_line_view)
        self._act_show_all_objects.triggered.connect(self._clear_grid_line_view)
        self._canvas.contextMenuRequested.connect(self._on_canvas_context_menu)
        self._act_add_node.triggered.connect(self._on_add_node)
        self._act_create_shell.triggered.connect(self._on_create_shell)
        self._act_frame_wizard.triggered.connect(self._on_frame_wizard)
        self._act_truss_wizard.triggered.connect(self._on_truss_wizard)
        self._act_material_library.triggered.connect(self._on_material_library)
        self._act_friction_library.triggered.connect(self._on_friction_library)
        self._act_material_tester.triggered.connect(self._on_material_tester)
        self._act_ground_motions.triggered.connect(self._on_ground_motions)
        self._act_section_library.triggered.connect(self._on_section_library)
        self._act_concrete_section.triggered.connect(self._on_concrete_section)
        self._act_section_designer.triggered.connect(self._on_section_designer)
        self._act_add_linear_ts.triggered.connect(self._on_add_linear_ts)
        self._act_add_path_ts.triggered.connect(self._on_add_path_ts)
        self._act_add_function_ts.triggered.connect(self._on_add_function_ts)
        self._act_add_multi_support.triggered.connect(self._on_add_multi_support)
        self._act_add_plain_pattern.triggered.connect(self._on_add_plain_pattern)
        self._act_add_uniform_excitation.triggered.connect(
            self._on_add_uniform_excitation,
        )
        self._act_load_combinations.triggered.connect(self._on_load_combinations)

        # Assign
        self._act_assign_support.triggered.connect(self._on_assign_support)
        self._act_assign_masses.triggered.connect(self._on_assign_masses)
        self._act_assign_springs.triggered.connect(self._on_assign_springs)
        self._act_assign_equal_dof.triggered.connect(self._on_assign_equal_dof)
        self._act_assign_diaphragm.triggered.connect(self._on_assign_diaphragm)
        self._act_assign_rigid_link.triggered.connect(self._on_assign_rigid_link)
        self._act_remove_constraints.triggered.connect(self._on_remove_constraints)
        self._act_storeys.triggered.connect(self._on_define_storeys)
        self._act_groups.triggered.connect(self._on_define_groups)
        self._act_section_cuts.triggered.connect(self._on_define_section_cuts)
        self._act_custom_commands.triggered.connect(self._on_custom_commands)
        self._act_assign_group.triggered.connect(self._on_assign_group)
        self._act_mass_source.triggered.connect(self._on_define_mass_source)
        self._act_seismic_loads.triggered.connect(self._on_define_seismic_loads)
        self._act_assign_load.triggered.connect(self._on_assign_load)
        self._act_assign_imposed_displacement.triggered.connect(
            self._on_assign_imposed_displacement
        )
        self._act_assign_surface_load.triggered.connect(self._on_assign_surface_load)
        self._act_assign_floor_load.triggered.connect(self._on_assign_floor_load)
        self._act_assign_zls.triggered.connect(self._on_assign_zls)
        self._act_assign_bearing.triggered.connect(self._on_assign_bearing)
        self._act_assign_link.triggered.connect(self._on_assign_link)
        self._act_assign_distributed_load.triggered.connect(self._on_assign_distributed_load)
        self._act_assign_frame_point_load.triggered.connect(self._on_assign_frame_point_load)
        self._act_assign_hinge.triggered.connect(self._on_assign_hinge)
        self._act_assign_section.triggered.connect(self._on_assign_section)
        self._act_assign_material.triggered.connect(self._on_assign_material)
        self._act_assign_geom_transf.triggered.connect(self._on_assign_geom_transf)
        self._act_assign_integration.triggered.connect(self._on_assign_integration)
        self._act_assign_releases.triggered.connect(self._on_assign_releases)
        self._act_assign_end_offsets.triggered.connect(self._on_assign_end_offsets)
        self._act_assign_insertion.triggered.connect(self._on_assign_insertion)
        self._act_assign_modifiers.triggered.connect(self._on_assign_modifiers)
        self._act_assign_trapezoidal_load.triggered.connect(self._on_assign_trapezoidal_load)
        self._act_assign_temperature_load.triggered.connect(self._on_assign_temperature_load)
        self._act_assign_wall.triggered.connect(self._on_assign_wall)

        # Analyze
        self._act_case_manager.triggered.connect(self._on_case_manager)
        self._act_check_model.triggered.connect(self._on_check_model)
        self._act_run.triggered.connect(self._on_run_analysis)
        self._act_run_all.triggered.connect(self._on_run_all_cases)
        self._act_run_selected.triggered.connect(self._on_run_selected_cases)
        self._act_clear_results.triggered.connect(self._on_clear_results)
        self._act_steel_check.triggered.connect(self._on_steel_check)
        self._act_drift_check.triggered.connect(self._on_drift_check)
        self._act_steel_ratios.triggered.connect(self._on_steel_ratios)
        self._act_check_stability.triggered.connect(self._on_check_stability)
        self._act_cancel_stability.triggered.connect(self._stability.cancel)
        self._stability.log.connect(self._log)
        self._stability.progress.connect(self._on_stability_progress)
        self._stability.finished.connect(self._on_stability_report)
        self._stability.failed.connect(self._on_stability_failed)
        self._stability.runningChanged.connect(self._on_stability_running_changed)
        # The runner's own flag flips to False only after ``finished`` has been
        # handled (teardown emits it), so the batch actions would stay disabled
        # for the rest of the session without this connection.
        self._runner.runningChanged.connect(self._on_runner_running_changed)

        # Display
        self._act_select_results.triggered.connect(self._on_select_results)
        self._act_show_deformed.triggered.connect(self._on_show_deformed)
        self._act_show_mode_shape.triggered.connect(self._on_show_mode_shape)
        self._act_show_force_diagram.triggered.connect(self._on_show_force_diagram)
        self._act_show_reactions.toggled.connect(self._on_show_reactions)
        self._act_reactions_table.triggered.connect(self._on_reactions_table)
        self._act_reactions_dialog.triggered.connect(self._on_reactions_dialog)
        self._act_shell_contours.triggered.connect(self._on_show_shell_contours)
        self._act_show_time_history.triggered.connect(self._on_show_time_history)
        self._act_export_th_animation.triggered.connect(self._on_export_th_animation)
        self._act_show_hysteresis.triggered.connect(self._on_show_hysteresis)
        self._act_show_pushover.triggered.connect(self._on_show_pushover)
        self._act_influence_line.triggered.connect(self._on_influence_line)
        self._act_show_response_spectrum.triggered.connect(self._on_show_response_spectrum)
        self._act_display_options.triggered.connect(self._on_display_options)
        self._act_back_to_model.triggered.connect(self._on_back_to_model)

        # AnalysisRunner: stream log to console + show results in panel
        self._runner.log.connect(self._console.appendPlainText)
        self._runner.caseFinished.connect(self._on_case_finished)
        self._runner.finished.connect(self._on_analysis_finished)
        self._runner.failed.connect(self._on_analysis_failed)
        self._runner.cancelled.connect(lambda: self._log("Analysis cancelled."))

        # View
        self._act_zoom_extents.triggered.connect(self._canvas.reset_camera)
        self._act_view_iso.triggered.connect(self._on_view_iso)
        self._act_view_top.triggered.connect(self._on_view_top)
        self._act_view_front.triggered.connect(self._on_view_front)
        self._act_view_right.triggered.connect(self._on_view_right)
        self._act_rotate_left.triggered.connect(lambda: self._on_rotate_view(-1, 0))
        self._act_rotate_right.triggered.connect(lambda: self._on_rotate_view(1, 0))
        self._act_rotate_up.triggered.connect(lambda: self._on_rotate_view(0, 1))
        self._act_rotate_down.triggered.connect(lambda: self._on_rotate_view(0, -1))
        self._act_spin.toggled.connect(self._on_spin)
        self._act_toggle_parallel.toggled.connect(self._on_toggle_parallel)
        self._act_zoom_in.triggered.connect(self._canvas.zoom_in)
        self._act_zoom_out.triggered.connect(self._canvas.zoom_out)
        self._act_hide_selected.triggered.connect(self._on_hide_selected)
        self._act_isolate_selected.triggered.connect(self._on_isolate_selected)
        self._act_invert_visible.triggered.connect(self._on_invert_visible)
        self._act_view_colors.triggered.connect(self._on_view_colors)
        self._act_new_view.triggered.connect(self._on_new_view_window)
        self._act_close_view.triggered.connect(self._on_close_view_window)
        # "Show Extruded Sections" and its Visibility twin are the same state,
        # so both drive it and _sync_visibility_actions keeps both ticked.
        self._act_show_extruded.toggled.connect(self._on_vis_extruded)
        for mode, action in self._color_by_actions.items():
            action.triggered.connect(lambda _=False, mode=mode: self._on_color_by(mode))
        self._act_vis_extruded.toggled.connect(self._on_vis_extruded)
        for action, field in (
            (self._act_vis_grids, "show_grids"),
            (self._act_vis_grid_labels, "show_grid_labels"),
            (self._act_vis_nodes, "show_nodes"),
            (self._act_vis_frames, "show_frames"),
            (self._act_vis_surfaces, "show_surfaces"),
            (self._act_vis_supports, "show_supports"),
            (self._act_vis_constraints, "show_constraints"),
            (self._act_vis_frame_assignments, "show_frame_assignments"),
            (self._act_vis_releases, "show_releases"),
            (self._act_vis_loads, "show_loads"),
        ):
            action.toggled.connect(partial(self._on_visibility_toggle, field))
        self._act_vis_node_labels.toggled.connect(self._on_vis_node_labels)
        self._act_vis_element_labels.toggled.connect(self._on_vis_element_labels)

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
        self._vm.new_project(dead_case=True)

    def _on_new_2d(self) -> None:
        """Planar frame model — (ndm=2, ndf=3): Ux, Uz, Ry per joint, then the wizard.

        Right choice when beam-columns are in the mix; for a pure truss use
        'New 2D Truss' so the solver doesn't face unrestrained rotational DOFs.

        An empty 2D frame project is just an empty canvas, and the only plane it
        can build in is the wizard's XZ (Z up), so the wizard opens here: it is what
        turns "new 2D frame" into a frame. Cancelling leaves the empty project,
        which is still the right start for drawing by hand.
        """
        if not self._confirm_discard_changes("Creating a new 2D frame"):
            return
        self._vm.new_project(ndm=2, ndf=3, dead_case=True)
        self._log("New 2D frame project (ndm = 2, ndf = 3).")
        self._create_portal_frame(with_grid=True)

    def _on_new_2d_truss(self) -> None:
        """Planar truss model — (ndm=2, ndf=2): only Ux, Uz per joint (the X-Z plane).

        Matches OpenSees's ``model BasicBuilder -ndm 2 -ndf 2`` from
        the Basic Truss Example and keeps the stiffness matrix well
        posed (no empty rotational rows).
        """
        if not self._confirm_discard_changes("Creating a new project"):
            return
        self._vm.new_project(ndm=2, ndf=2, dead_case=True)
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
            with self._busy(f"Opening {Path(path).name}…"):
                self._vm.open(path)
            self._log(f"Opened: {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return False
        snapshot = self._vm.pending_run_snapshot()
        if snapshot is None:
            self._apply_project_view_settings()
            self._confirm_custom_commands()
            self._offer_stored_results()
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
        self._apply_project_view_settings()
        self._confirm_custom_commands()
        self._offer_stored_results()
        return True

    def _offer_stored_results(self) -> None:
        """Offer the results a batch stored for this model, so nothing has to run again."""
        stored = stored_results(self._vm.path, self._vm.project)
        if stored is None:
            return
        answer = QMessageBox.question(
            self,
            "Stored results",
            f"Results of {len(stored.entries)} case(s) from a batch run "
            f"({stored.finished_at or 'time unknown'}) are stored for this model, and the "
            "model has not changed since.\n\nLoad them to view without running again?\n\n"
            f"Folder: {stored.out_dir}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.load_stored_results(stored)

    def load_stored_results(self, stored: StoredResults) -> int:
        """Load every case of ``stored`` as if it had just run; show the last one.

        They are already in the results database, so nothing is recorded again.
        Returns how many cases loaded.
        """
        loaded = []
        for entry in stored.entries:
            try:
                results = load_results(entry, stored.out_dir)
            except Exception as exc:
                self._log(
                    f"Warning: stored results of case {entry.get('case_id')} unreadable: {exc}"
                )
                continue
            self._keep_case_results(results)
            loaded.append(results)
        if loaded:
            self._display_results(loaded[-1])
            self._log(f"Loaded {len(loaded)} stored case result(s) from {stored.out_dir}.")
        return len(loaded)

    def _on_run_batch(self) -> None:
        """File → Run Batch…"""
        start_dir = self._vm.path.parent if self._vm.path is not None else None
        dlg = BatchRunDialog(self, start_dir=start_dir)
        try:
            dlg.exec()
        finally:
            dlg.deleteLater()

    def _confirm_custom_commands(self) -> None:
        """A file's custom Python blocks run only once the user trusts them."""
        project = self._vm.project
        blocks = [b for b in project.custom_commands if b.enabled] if project is not None else []
        if not blocks:
            return
        names = ", ".join(b.name or str(b.id) for b in blocks)
        answer = QMessageBox.warning(
            self,
            "Custom OpenSees commands",
            f"This project contains {len(blocks)} custom Python block(s) ({names}) that run "
            "on this computer when the model is analysed.\n\nRun them only if you trust "
            "where the file came from. Enable them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            for block in blocks:
                block.enabled = False
            self._log(
                f"Custom command blocks disabled: {names}. "
                "Enable them in Define → Custom OpenSees Commands."
            )

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
        self._save_session_state()
        # Secondary viewports are children of the same session: they go with it.
        for window in list(self._view_windows):
            window.close()
        self._view_windows.clear()
        super().closeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        """Give the menus back to the main canvas when this window is activated."""
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            main = getattr(self, "_main_canvas", None)
            active = getattr(self, "_active_canvas", None)
            if main is not None and active is not None and active is not main:
                self._active_canvas = main
                self._act_close_view.setEnabled(False)
                self._sync_visibility_actions()
                self._refresh_action_enablement()
        super().changeEvent(event)

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
            self._store_view_settings_in_project()
            self._warn_case_references()
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
            self._store_view_settings_in_project()
            self._warn_case_references()
            out = self._vm.save(path)
            self._log(f"Saved: {out}")
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        return True

    def _on_export_ifc(self) -> None:
        """File → Export → IFC: the physical BIM model and the analytical model, IFC4."""
        from opensees_studio.services.ifc_export import IfcExportError, export_ifc

        if self._vm.project is None:
            QMessageBox.information(self, "Export IFC", "Open or create a project first.")
            return
        default = (self._vm.path.stem if self._vm.path is not None else "model") + ".ifc"
        path, _ = QFileDialog.getSaveFileName(self, "Export IFC", default, "IFC (*.ifc)")
        if not path:
            return
        if not path.lower().endswith(".ifc"):
            path += ".ifc"
        try:
            report = export_ifc(self._vm.project, path)
        except (IfcExportError, OSError, ValueError) as exc:
            QMessageBox.critical(self, "Export IFC failed", str(exc))
            return
        self._log(report.summary())
        if report.notes:
            QMessageBox.information(self, "Export IFC", report.summary())

    def _on_export_s2k(self) -> None:
        """File → Export → SAP2000 Text: the frame model as SAP2000 text tables."""
        from opensees_studio.services.sap2000_text import Sap2000TextError, export_s2k

        if self._vm.project is None:
            QMessageBox.information(self, "Export SAP2000 Text", "Open or create a project first.")
            return
        default = (self._vm.path.stem if self._vm.path is not None else "model") + ".s2k"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SAP2000 Text", default, "SAP2000 text (*.s2k *.$2k)"
        )
        if not path:
            return
        if not path.lower().endswith((".s2k", ".$2k")):
            path += ".s2k"
        try:
            report = export_s2k(self._vm.project, path)
        except Sap2000TextError as exc:
            QMessageBox.critical(self, "Export SAP2000 Text failed", str(exc))
            return
        self._log(f"Exported {Path(path).name}: {report.summary()}")
        if report.skipped:
            QMessageBox.information(self, "Export SAP2000 Text", report.summary())

    def report_results(self) -> list[Any]:
        """The results the report includes: every current case, plus the one on screen."""
        project = self._vm.project
        if project is None:
            return []
        current = dict(self._case_results.current(project))
        fingerprint = model_fingerprint(project)
        for case_id, (fp, results) in self._report_extra.items():
            if fp == fingerprint:
                current.setdefault(case_id, results)
        return list(current.values())

    def _on_export_report(self) -> None:
        """File → Export → Report: model, loads, cases and current results as HTML or PDF."""
        from opensees_studio.services.report import build_report

        project = self._vm.project
        if project is None:
            QMessageBox.information(self, "Export report", "Open or create a project first.")
            return
        default = (self._vm.path.stem if self._vm.path is not None else "model") + "-report.pdf"
        path, chosen = QFileDialog.getSaveFileName(
            self, "Export report", default, "PDF (*.pdf);;HTML page (*.html)"
        )
        if not path:
            return
        as_html = path.lower().endswith((".html", ".htm")) or (
            "HTML" in chosen and not path.lower().endswith(".pdf")
        )
        if not path.lower().endswith((".pdf", ".html", ".htm")):
            path += ".html" if as_html else ".pdf"
        results = self.report_results()
        page = build_report(project, results)
        try:
            if as_html:
                Path(path).write_text(page, encoding="utf-8")
            else:
                write_pdf(page, path)
        except OSError as exc:
            QMessageBox.critical(self, "Export report failed", str(exc))
            return
        self._log(f"Report written: {path} ({len(results)} result set(s)).")

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
    def _warn_case_references(self) -> None:
        project = self._vm.project
        if project is None:
            return
        errors = [
            error for case in project.analyses for error in project.case_reference_errors(case)
        ]
        if errors:
            QMessageBox.warning(self, "Saving with invalid case references", "\n".join(errors))

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

    def _on_table_editing(self) -> None:
        """Edit → Interactive Table Editing: joints, elements and joint loads as tables."""
        project = self._vm.project
        if project is None:
            return
        dlg = ModelTablesDialog(project, self)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.edited is None:
            return
        try:
            self._vm.apply_command(ApplyModelTablesCommand(self._vm, dlg.edited))
            self._log(
                f"Tables applied: {len(project.nodes)} joint(s), "
                f"{len(project.elements)} element(s)."
            )
        except Exception as exc:
            QMessageBox.critical(self, "Interactive Table Editing failed", str(exc))

    def _on_select_all(self) -> None:
        """Select all nodes AND all elements in the project."""
        if self._vm.project is None:
            return
        node_ids = {n.id for n in self._vm.project.nodes}
        elem_ids = {e.id for e in self._vm.project.elements}
        self._canvas.selection.set_selection(node_ids, elem_ids)

    # ── slots: select menu ──────────────────────────────────────────
    def _build_select_menu(self, menu: Any) -> None:
        """Select: everything, by property, by load pattern, inverted or the previous one.

        The "By …" submenus list what the model holds when the menu opens, and
        every query *adds* to the current selection (SAP2000 style), so "frames
        of section A" then "frames of section B" selects both.
        """
        menu.addActions([self._act_select_all, self._act_clear_selection])
        menu.addActions([self._act_invert_selection, self._act_previous_selection])
        menu.addSeparator()
        menu.addActions([self._act_select_all_joints, self._act_select_all_elements])
        self._menu_select_by_type = menu.addMenu("By Element &Type")
        self._menu_select_by_section = menu.addMenu("By Se&ction")
        self._menu_select_by_material = menu.addMenu("By Mate&rial")
        self._menu_select_by_pattern = menu.addMenu("By &Load Pattern")
        self._menu_select_by_group = menu.addMenu("By &Group")
        menu.addSeparator()
        menu.addActions(
            [
                self._act_select_supports,
                self._act_select_joints_with_mass,
                self._act_select_weighted,
            ]
        )
        menu.addSeparator()
        menu.addActions(
            [
                self._act_select_loose_joints,
                self._act_select_joints_in_bars,
                self._act_select_shell_edge_joints,
            ]
        )
        menu.addSeparator()
        menu.addActions(
            [self._act_select_joints_of_elements, self._act_select_elements_within_joints]
        )
        for submenu, fill in (
            (self._menu_select_by_type, self._fill_select_by_type),
            (self._menu_select_by_section, self._fill_select_by_section),
            (self._menu_select_by_material, self._fill_select_by_material),
            (self._menu_select_by_pattern, self._fill_select_by_pattern),
            (self._menu_select_by_group, self._fill_select_by_group),
        ):
            submenu.aboutToShow.connect(lambda submenu=submenu, fill=fill: fill(submenu))
        menu.aboutToShow.connect(self._refresh_select_menu)

    def _refresh_select_menu(self) -> None:
        project = self._vm.project
        has = project is not None
        self._act_invert_selection.setEnabled(has)
        self._act_previous_selection.setEnabled(has and any(self._canvas.selection.previous))
        sel = self._canvas.selection
        self._act_select_joints_of_elements.setEnabled(has and bool(sel.elements))
        self._act_select_elements_within_joints.setEnabled(has and bool(sel.nodes))
        for submenu in (
            self._menu_select_by_type,
            self._menu_select_by_section,
            self._menu_select_by_material,
            self._menu_select_by_pattern,
            self._menu_select_by_group,
        ):
            submenu.setEnabled(has)

    def _fill_submenu(self, submenu: Any, entries: list[tuple[str, Callable[[], None]]]) -> None:
        submenu.clear()
        if not entries:
            submenu.addAction("(none in the model)").setEnabled(False)
            return
        for label, callback in entries:
            # ``triggered`` passes ``checked``; keep it away from the callback.
            submenu.addAction(label).triggered.connect(lambda _checked=False, cb=callback: cb())

    def _fill_select_by_type(self, submenu: Any) -> None:
        project = self._vm.project
        if project is None:
            return
        entries = []
        for element_type in selection_queries.element_types(project):
            ids = selection_queries.elements_of_type(project, element_type)
            entries.append(
                (
                    f"{element_type} ({len(ids)})",
                    lambda ids=ids: self._add_to_selection(elements=ids),
                )
            )
        self._fill_submenu(submenu, entries)

    def _fill_select_by_section(self, submenu: Any) -> None:
        project = self._vm.project
        if project is None:
            return
        entries = []
        for section in selection_queries.sections_in_use(project):
            ids = selection_queries.elements_with_section(project, section.id)
            entries.append(
                (
                    f"#{section.id} {section.name or section.type} ({len(ids)})",
                    lambda ids=ids: self._add_to_selection(elements=ids),
                )
            )
        self._fill_submenu(submenu, entries)

    def _fill_select_by_material(self, submenu: Any) -> None:
        project = self._vm.project
        if project is None:
            return
        entries = []
        for material in selection_queries.materials_in_use(project):
            ids = selection_queries.elements_with_material(project, material.id)
            entries.append(
                (
                    f"#{material.id} {material.name or material.type} ({len(ids)})",
                    lambda ids=ids: self._add_to_selection(elements=ids),
                )
            )
        self._fill_submenu(submenu, entries)

    def _fill_select_by_pattern(self, submenu: Any) -> None:
        project = self._vm.project
        if project is None:
            return
        entries = []
        for pattern in project.load_patterns:
            nodes, elements = selection_queries.loaded_by_pattern(project, pattern.id)
            if not nodes and not elements:
                continue
            entries.append(
                (
                    f"#{pattern.id} {pattern.name or pattern.type} "
                    f"({len(nodes)} joint(s), {len(elements)} element(s))",
                    lambda nodes=nodes, elements=elements: self._add_to_selection(
                        nodes=nodes, elements=elements
                    ),
                )
            )
        self._fill_submenu(submenu, entries)

    def _fill_select_by_group(self, submenu: Any) -> None:
        project = self._vm.project
        if project is None:
            return
        entries: list[tuple[str, Callable[[], None]]] = []
        for group in project.groups:
            nodes, elements = group_members(project, group.id)
            entries.append(
                (
                    f"{group.name} ({len(nodes)} joint(s), {len(elements)} element(s))",
                    partial(self._add_to_selection, nodes=nodes, elements=elements),
                )
            )
        self._fill_submenu(submenu, entries)

    def _select_from(self, query: Callable[[Project, Any], tuple[set[int], set[int]]]) -> None:
        """Add what ``query(project, selection)`` returns to the selection."""
        if self._vm.project is None:
            return
        nodes, elements = query(self._vm.project, self._canvas.selection)
        self._add_to_selection(nodes=nodes, elements=elements)

    def _add_to_selection(
        self, *, nodes: set[int] | None = None, elements: set[int] | None = None
    ) -> None:
        """Add ``nodes`` / ``elements`` to what is selected and report the count."""
        if self._vm.project is None:
            return
        sel = self._canvas.selection
        new_nodes = set(sel.nodes) | set(nodes or ())
        new_elements = set(sel.elements) | set(elements or ())
        sel.set_selection(new_nodes, new_elements)
        self.statusBar().showMessage(
            f"Selected {len(new_nodes)} joint(s), {len(new_elements)} element(s).", 4000
        )

    def _on_invert_selection(self) -> None:
        if self._vm.project is None:
            return
        sel = self._canvas.selection
        nodes, elements = selection_queries.invert(self._vm.project, sel.nodes, sel.elements)
        sel.set_selection(nodes, elements)

    def _on_previous_selection(self) -> None:
        nodes, elements = self._canvas.selection.previous
        if self._vm.project is None:
            return
        # Drop ids deleted since (the previous selection can outlive them).
        node_ids = {n.id for n in self._vm.project.nodes}
        element_ids = {e.id for e in self._vm.project.elements}
        self._canvas.selection.set_selection(set(nodes) & node_ids, set(elements) & element_ids)

    def _on_clear_selection(self) -> None:
        """Esc: clear selection AND reset any in-progress tool gesture."""
        self._canvas.selection.clear()
        self._tool_controller.cancel()

    # ── slots: edit → transforms ────────────────────────────────────
    def _selection_nodes(self) -> set[int]:
        """Selected nodes, plus the joints of every selected element.

        A frame is defined by its joints, so selecting members and asking to
        move, copy or mirror them means acting on those joints: the user does
        not have to pick the nodes first. A joint shared with a member that is
        not selected still moves, which is how a joint edit behaves in a frame
        program — the connected member follows its joint.
        """
        project = self._vm.project
        if project is None:
            return set(self._canvas.selection.nodes)
        return selection_queries.implied_node_ids(
            project,
            self._canvas.selection.nodes,
            self._canvas.selection.elements,
        )

    def _on_move(self) -> None:
        sel_nodes = self._selection_nodes()
        if not sel_nodes:
            QMessageBox.information(self, "Move", "Select nodes or frame elements first.")
            return
        dlg = MoveDialog(len(sel_nodes), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(MoveNodesCommand(self._vm, sel_nodes, dlg.offset()))
        except Exception as exc:
            QMessageBox.critical(self, "Move failed", str(exc))

    def _on_replicate(self) -> None:
        sel_nodes = self._selection_nodes()
        sel_elements = set(self._canvas.selection.elements)
        if not sel_nodes:
            QMessageBox.information(self, "Replicate", "Select nodes or frame elements first.")
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
        sel_nodes = self._selection_nodes()
        sel_elements = set(self._canvas.selection.elements)
        if not sel_nodes:
            QMessageBox.information(self, "Mirror", "Select nodes or frame elements first.")
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
        return any(cs.grid.shown for cs in project.coord_systems)

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
        plate_sections = [s for s in project.sections if isinstance(s, SHELL_SECTION_CLASSES)]
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

    def _on_import_s3d(self) -> None:
        """File → Import → PORTICO Model: a ``.s3d`` file as a new, unsaved project.

        The whole model is replaced, so this asks about unsaved changes like Open
        does. What the file has and the import cannot carry is written to the log.
        """
        if not self._confirm_discard_changes("Importing a PORTICO model"):
            return
        dialog = S3dImportDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        imported = dialog.imported()
        if imported is None:
            return
        self._vm.adopt(imported.project)
        self._apply_project_view_settings()
        source = dialog.source()
        self._log(
            f"Imported {source.name if source else 'the PORTICO model'} "
            f"({imported.source_units} → {imported.project.meta.units.value}): "
            f"{imported.summary()}"
        )
        for note in imported.notes:
            self._log(note)

    def _on_import_s2k(self) -> None:
        """File → Import → SAP2000 Text: a ``.s2k`` / ``.$2k`` file as a new, unsaved project.

        The whole model is replaced, so this asks about unsaved changes like Open
        does. What the file has and the import cannot carry is written to the log.
        """
        from opensees_studio.services.sap2000_text import (
            Sap2000TextError,
            import_s2k,
            read_s2k,
        )

        if not self._confirm_discard_changes("Importing a SAP2000 text file"):
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import SAP2000 Text",
            "",
            "SAP2000 text (*.s2k *.$2k *.S2K *.$2K);;All files (*)",
        )
        if not path:
            return
        subdivisions: int | None = None
        try:
            if read_s2k(path).rows("FRAME SECTION PROPERTIES 05 - NONPRISMATIC"):
                subdivisions, ok = QInputDialog.getInt(
                    self,
                    "Nonprismatic members",
                    "Pieces per nonprismatic member (minimum 12):",
                    12,
                    12,
                    200,
                )
                if not ok:
                    return
        except Sap2000TextError as exc:
            QMessageBox.critical(self, "Import SAP2000 Text failed", str(exc))
            return
        try:
            with perf.span("ui.import_s2k"):
                imported = import_s2k(path, nonprismatic_subdivisions=subdivisions)
        except Sap2000TextError as exc:
            QMessageBox.critical(self, "Import SAP2000 Text failed", str(exc))
            return
        self._vm.adopt(imported.project)
        self._apply_project_view_settings()
        self._log(
            f"Imported {Path(path).name} ({imported.source_units} → "
            f"{imported.project.meta.units.value}): {imported.summary()}"
        )
        for note in imported.notes:
            self._log(note)

    def _on_influence_line(self) -> None:
        """Display → Influence Line: one response of the influence-line case on screen."""
        results = self._latest_results
        if not isinstance(results, InfluenceLineResults) or self._vm.project is None:
            QMessageBox.information(
                self,
                "Influence Line",
                "Run an influence-line case first (Analyze → Cases… → Add → InfluenceLine).",
            )
            return
        dialog = InfluenceLineDialog(self._vm.project, results, parent=self)
        dialog.exec()

    def _on_steel_check(self) -> None:
        """Design → Steel Frame Check: AISC 360-16 ratios over this session's results.

        The dialog reads the case results cache and runs nothing itself; its
        settings are stored on OK with one undoable command.
        """
        project = self._vm.project
        if project is None:
            return
        dialog = SteelDesignDialog(
            project,
            dict(self._case_results.current(project)),
            selected_elements=frozenset(self._canvas.selection.elements),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        settings = dialog.settings()
        if settings != project.design:
            self._vm.apply_command(SetDesignSettingsCommand(self._vm, settings))
        report = dialog.report()
        if report is not None:
            self._log(f"Steel frame check (AISC 360-16, {settings.method}): {report.summary()}")
            for note in report.notes:
                self._log(note)
        if dialog.select_failing_requested:
            failing = dialog.failing_elements()
            self._canvas.selection.set_selection(set(), failing)
            self.statusBar().showMessage(f"Selected {len(failing)} failing member(s).", 4000)
        if dialog.show_ratios_requested and report is not None:
            self._show_design_ratios(report, settings)

    def _on_steel_ratios(self) -> None:
        """Design → Display Steel Ratios: paint the members by the stored check's ratios.

        Runs the AISC 360-16 check with the project's design settings (the
        defaults when none were stored) over this session's results, as the
        Steel Frame Check dialog would, and shows the overlay with its legend.
        """
        project = self._vm.project
        if project is None:
            return
        settings = project.design or DesignSettings()
        report = steel_frame_check(project, dict(self._case_results.current(project)), settings)
        if not any(m.status != "not designed" for m in report.members):
            reason = " ".join(report.notes) or (
                "No frame member has an AISC section the check covers."
            )
            QMessageBox.information(self, "Display Steel Ratios", reason)
            return
        self._log(f"Steel frame check (AISC 360-16, {settings.method}): {report.summary()}")
        self._show_design_ratios(report, settings)

    def _show_design_ratios(self, report: Any, settings: DesignSettings) -> None:
        """The ratio overlay and its legend dock; Back to model clears both."""
        self._on_back_to_model()
        self._ratio_renderer.render(self._vm.project, report.members, limit=settings.ratio_limit)
        view = DesignRatioView()
        view.set_report(report, method=settings.method, limit=settings.ratio_limit)
        dock = QDockWidget("Steel Ratios", self)
        dock.setWidget(view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._post_dock = dock
        failing = {m.element_id for m in report.failing}

        def _select_failing() -> None:
            self._canvas.selection.set_selection(set(), failing)
            self.statusBar().showMessage(f"Selected {len(failing)} failing member(s).", 4000)

        view.selectFailing.connect(_select_failing)
        view.closed.connect(self._on_back_to_model)
        self._set_result_caption(f"Steel ratios · AISC 360-16 {settings.method}")
        self._canvas.render()

    def _on_drift_check(self) -> None:
        """Design → Storey Drift Check: amplified drift ratios against the allowable one."""
        project = self._vm.project
        if project is None:
            return
        dialog = DriftCheckDialog(project, dict(self._case_results.current(project)), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        settings = dialog.settings()
        if settings != project.design:
            self._vm.apply_command(SetDesignSettingsCommand(self._vm, settings))

    def _on_delete_loads(self) -> None:
        """Edit → Delete Loads: remove loads by type, pattern and selection, one undo step."""
        from opensees_studio.commands import DeleteLoadsCommand
        from opensees_studio.core.load_removal import KINDS_BY_KEY
        from opensees_studio.views.dialogs.delete_loads import DeleteLoadsDialog

        project = self._vm.project
        if project is None:
            return
        dialog = DeleteLoadsDialog(
            project,
            selected_nodes=set(self._canvas.selection.nodes),
            selected_elements=set(self._canvas.selection.elements),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        command = DeleteLoadsCommand(self._vm, dialog.kinds(), dialog.scope())
        try:
            self._vm.apply_command(command)
        except Exception as exc:
            QMessageBox.critical(self, "Could not delete the loads", str(exc))
            return
        done = [f"{n} {KINDS_BY_KEY[k].label.lower()}" for k, n in command.removed.items() if n]
        self._log("Delete Loads: " + (", ".join(done) if done else "nothing removed") + ".")

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

    def _on_merge_joints(self) -> None:
        """Edit → Merge Joints: joints closer than a tolerance become one, one undo step."""
        project = self._vm.project
        if project is None:
            return
        dialog = MergeJointsDialog(
            project, selected_nodes=set(self._canvas.selection.nodes), parent=self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        command = MergeJointsCommand(
            self._vm, tolerance=dialog.tolerance(), node_ids=dialog.scope_ids()
        )
        try:
            self._vm.apply_command(command)
        except Exception as exc:
            QMessageBox.critical(self, "Could not merge the joints", str(exc))
            return
        self._canvas.selection.clear()
        report = command.report
        self._log(
            f"Merge Joints: {report.merged_node_groups} group(s), {report.removed_nodes} "
            f"joint(s) removed, {report.removed_elements} repeated member(s) removed."
        )

    def _on_divide_frames(self) -> None:
        """Edit → Divide Frames at Joints: split members at the joints inside them."""
        project = self._vm.project
        if project is None:
            return
        dialog = DivideFramesDialog(
            project, selected_elements=set(self._canvas.selection.elements), parent=self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        plan = dialog.plan()
        if plan.is_empty:
            return
        try:
            self._vm.apply_command(MeshCommand(self._vm, plan))
        except Exception as exc:
            QMessageBox.critical(self, "Could not divide the frames", str(exc))
            return
        self._canvas.selection.set_selection(set(), {e.id for e in plan.new_elements})
        self._log(f"Divide Frames at Joints: {plan.summary()}")

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

        # The wizard builds ElasticBeamColumns directly; a nonprismatic template
        # is assigned afterwards, when it can subdivide the member and its loads.
        sections = [s for s in project.sections if isinstance(s, ElasticSection)]
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
                # A 2D model has one plane, X-Z: show it face on.
                self._on_view_front()

    def _on_truss_wizard(self) -> None:
        """Define → Create Truss: a parametric plane truss, one undo step.

        The geometry comes from ``core.trusses``; this collects it, resolves the
        material (creating the default truss steel *inside* the macro when the
        project has no uniaxial material) and inserts the result.
        """
        from opensees_studio.core import TRUSS_NDF, build_truss
        from opensees_studio.views.dialogs.truss_wizard import TrussWizard

        project = self._vm.project
        if project is None:
            QMessageBox.information(self, "Truss", "Open or create a project first.")
            return
        if (project.ndm, project.ndf) not in TRUSS_NDF:
            QMessageBox.information(
                self,
                "Truss",
                "A plane truss needs ndm = 2 (ndf 2 or 3) or ndm = 3 (ndf 3 or 6); "
                f"this project is ndm = {project.ndm}, ndf = {project.ndf}.",
            )
            return
        materials = [m for m in project.materials if is_uniaxial(m)]
        wizard = TrussWizard(
            materials,
            ndm=project.ndm,
            ndf=project.ndf,
            length_unit=labels_for(project.meta.units).length,
            parent=self,
        )
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return
        material_id = wizard.material_choice()

        self._vm.undo_stack.beginMacro("Create truss")
        try:
            if material_id is None:
                material = make_default_truss_material(project.next_material_id())
                self._vm.apply_command(AddMaterialsCommand(self._vm, [material]))
                material_id = material.id
            truss = build_truss(
                wizard.spec(material_id=material_id),
                ndm=project.ndm,
                ndf=project.ndf,
                first_node_id=project.next_node_id(),
                first_element_id=project.next_element_id(),
            )
            self._vm.apply_command(AddNodesCommand(self._vm, truss.nodes))
            self._vm.apply_command(AddElementsCommand(self._vm, truss.elements))
        except Exception as exc:
            QMessageBox.critical(self, "Cannot create the truss", str(exc))
            return
        finally:
            self._vm.undo_stack.endMacro()

        self._canvas.selection.set_selection(
            {node.id for node in truss.nodes}, {element.id for element in truss.elements}
        )
        self._log(f"{truss.summary()} Left selected.")

    def _on_grid_wizard(self) -> None:
        """Define → Grid Wizard: a regular Cartesian or radial grid, one undo step."""
        if self._vm.project is None:
            self._on_new()
        project = self._vm.project
        assert project is not None
        dlg = GridWizardDialog(project.coord_systems, ndm=project.ndm, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        target = dlg.target()
        if target:
            systems = [
                cs.model_copy(update={"grid": dlg.grid_system()}) if cs.name == target else cs
                for cs in project.coord_systems
            ]
            name = target
        else:
            new = dlg.system()
            systems = [*project.coord_systems, new]
            name = new.name
        self._vm.apply_command(SetCoordSystemsCommand(self._vm, systems))
        self._log(f"Grid Wizard: grid of '{name}' set.")

    def _set_grids_shown(self, shown: bool, name: str | None = None) -> None:
        """Show or hide the grids (all, or the system called ``name``): an undo step.

        The same flag as the Hide All Grid Lines box of the grid dialog.
        """
        project = self._vm.project
        if project is None:
            return
        systems = [
            cs.model_copy(update={"grid": cs.grid.model_copy(update={"hide_all": not shown})})
            if name is None or cs.name == name
            else cs
            for cs in project.coord_systems
        ]
        if systems != project.coord_systems:
            self._vm.apply_command(SetCoordSystemsCommand(self._vm, systems))
        self._sync_grid_actions()

    def _set_grid_labels_shown(self, shown: bool) -> None:
        project = self._vm.project
        if project is None:
            return
        systems = [
            cs.model_copy(update={"grid": cs.grid.model_copy(update={"show_labels": shown})})
            for cs in project.coord_systems
        ]
        if systems != project.coord_systems:
            self._vm.apply_command(SetCoordSystemsCommand(self._vm, systems))
        self._sync_grid_actions()

    def _sync_grid_actions(self) -> None:
        """Tick View → Show Grids / Labels from the project (checked when any shows)."""
        project = self._vm.project
        systems = project.coord_systems if project is not None else []
        self._act_show_grids.setChecked(any(not cs.grid.hide_all for cs in systems))
        self._act_show_grid_labels.setChecked(any(cs.grid.show_labels for cs in systems))

    # ── View → zoom, hiding and per-viewport settings ───────────────
    def _apply_view_settings(self, **changes: object) -> None:
        """Apply ``changes`` to this viewport's settings and resync the ticks."""
        self._canvas.set_view_settings(self._canvas.view_settings.with_changes(**changes))
        self._sync_visibility_actions()

    def _sync_visibility_actions(self) -> None:
        """Tick every visibility action from the canvas without re-firing it."""
        settings = self._canvas.view_settings
        pairs: tuple[tuple[QAction, bool], ...] = (
            (self._act_vis_grids, settings.show_grids),
            (self._act_vis_grid_labels, settings.show_grid_labels),
            (self._act_vis_nodes, settings.show_nodes),
            (self._act_vis_frames, settings.show_frames),
            (self._act_vis_surfaces, settings.show_surfaces),
            (self._act_vis_supports, settings.show_supports),
            (self._act_vis_constraints, settings.show_constraints),
            (self._act_vis_frame_assignments, settings.show_frame_assignments),
            (self._act_vis_releases, settings.show_releases),
            (self._act_vis_loads, settings.show_loads),
            (self._act_vis_node_labels, settings.show_node_labels),
            (self._act_vis_element_labels, settings.show_element_labels),
            (self._act_vis_extruded, settings.show_extruded),
            # "Show Extruded Sections" is the same field, so it ticks too.
            (self._act_show_extruded, settings.show_extruded),
        )
        for action, checked in pairs:
            action.blockSignals(True)
            action.setChecked(checked)
            action.blockSignals(False)
        color_by = self._color_by_actions[settings.color_by]
        color_by.blockSignals(True)
        color_by.setChecked(True)
        color_by.blockSignals(False)

    def _on_visibility_toggle(self, field: str, checked: bool) -> None:
        """Apply one Visibility-menu toggle to the viewport."""
        self._apply_view_settings(**{field: checked})

    def _on_vis_node_labels(self, checked: bool) -> None:
        """Node labels, keeping the Display Options dialog's state in step."""
        self._show_node_labels = checked
        self._apply_view_settings(show_node_labels=checked)

    def _on_vis_element_labels(self, checked: bool) -> None:
        """Element labels, keeping the Display Options dialog's state in step."""
        self._show_element_labels = checked
        self._apply_view_settings(show_element_labels=checked)

    def _on_color_by(self, mode: str) -> None:
        """View → Color By: paint frames and shells by section, material or group."""
        self._apply_view_settings(color_by=mode)

    def _on_vis_extruded(self, checked: bool) -> None:
        """Show Extruded Sections, from either of its two actions."""
        self._apply_view_settings(show_extruded=checked)

    def _on_hide_selected(self) -> None:
        """Hide the selection in this viewport; the project keeps the entities."""
        selection = self._canvas.selection
        hidden_nodes, hidden_elements = self._canvas.hidden
        self._canvas.set_hidden(
            nodes=set(hidden_nodes) | set(selection.nodes),
            elements=set(hidden_elements) | set(selection.elements),
        )
        self._refresh_action_enablement()

    def _on_isolate_selected(self) -> None:
        """Show only the selection (and the joints of selected elements)."""
        project = self._vm.project
        selection = self._canvas.selection
        if project is None or selection.is_empty:
            return
        selected_elements = set(selection.elements)
        visible_nodes = set(selection.nodes)
        for element in project.elements:
            if element.id in selected_elements:
                visible_nodes.update(element.nodes)
        all_nodes = {node.id for node in project.nodes}
        all_elements = {element.id for element in project.elements}
        self._canvas.set_hidden(
            nodes=all_nodes - visible_nodes,
            elements=all_elements - selected_elements,
        )
        self._refresh_action_enablement()
        parts = []
        if visible_nodes:
            parts.append(f"{len(visible_nodes)} joint(s)")
        if selected_elements:
            parts.append(f"{len(selected_elements)} element(s)")
        self.statusBar().showMessage(
            f"Isolated {', '.join(parts)}. View > Show All Objects to restore.",
            5000,
        )

    def _sync_show_all_action(self) -> None:
        """Enable Show All when a viewport filter or a hidden set is active."""
        hidden_nodes, hidden_elements = self._canvas.hidden
        self._act_show_all_objects.setEnabled(
            self._grid_view is not None or bool(hidden_nodes) or bool(hidden_elements)
        )

    def _on_invert_visible(self) -> None:
        """Swap what this viewport shows: hidden becomes visible and vice versa."""
        project = self._vm.project
        if project is None:
            return
        hidden_nodes, hidden_elements = self._canvas.hidden
        self._canvas.set_hidden(
            nodes={n.id for n in project.nodes} - hidden_nodes,
            elements={e.id for e in project.elements} - hidden_elements,
        )
        self._refresh_action_enablement()

    def _on_view_colors(self) -> None:
        """View → Colors: edit the six viewport colours in one dialog."""
        dialog = ViewColorsDialog(self._canvas.view_settings, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_view_settings(**dialog.colors())

    # ── View → secondary windows ────────────────────────────────────
    def _on_new_view_window(self) -> None:
        """Open another viewport on the same project, in its own window."""
        window = ViewWindow(self._main_canvas.selection, self._active_canvas.view_settings, self)
        window.activated.connect(self._on_view_window_activated)
        window.closed.connect(self._on_view_window_closed)
        # The right-click menu is the main window's, so every viewport gets the
        # same actions (assign, hide, delete) on the shared selection.
        window.canvas.contextMenuRequested.connect(self._on_canvas_context_menu)
        self._view_windows.append(window)
        window.show_project(self._vm.project)
        window.show()
        self._on_view_window_activated(window)

    def _on_close_view_window(self) -> None:
        """Close the viewport the menu targets; the main canvas never closes."""
        if self._active_canvas is self._main_canvas:
            return
        for window in list(self._view_windows):
            if window.canvas is self._active_canvas:
                window.close()
                return

    def _on_view_window_activated(self, window: object) -> None:
        """Follow focus: the View menu now acts on that window's canvas."""
        if not isinstance(window, ViewWindow):
            return
        self._active_canvas = window.canvas
        self._act_close_view.setEnabled(True)
        self._sync_visibility_actions()
        self._refresh_action_enablement()

    def _on_view_window_closed(self, window: object) -> None:
        """Forget a closed window and hand the menus back to the main canvas."""
        if not isinstance(window, ViewWindow):
            return
        if window in self._view_windows:
            self._view_windows.remove(window)
        if self._active_canvas is window.canvas:
            self._active_canvas = self._main_canvas
        self._act_close_view.setEnabled(False)
        self._sync_visibility_actions()

    def _refresh_view_windows(self, project: Project | None) -> None:
        """Re-render every secondary viewport, keeping its camera where it was."""
        for window in list(self._view_windows):
            window.refresh(project)

    # ── View settings that live in the project file ─────────────────
    def _apply_project_view_settings(self) -> None:
        """Adopt the display settings the project carries."""
        project = self._vm.project
        stored = project.view if project is not None else None
        self._main_canvas.set_view_settings(stored if stored is not None else ViewSettings())
        self._sync_visibility_actions()

    def _store_view_settings_in_project(self) -> None:
        """Write the primary viewport's settings into the model before saving.

        A viewport that was never customised stores ``None``, so the file stays
        byte-identical to one written before this feature existed.
        """
        project = self._vm.project
        if project is None:
            return
        settings = self._main_canvas.view_settings
        project.view = None if settings == ViewSettings() else settings

    # ── display state that outlives the process ─────────────────────
    def _restore_session_state(self) -> None:
        """Restore last session's geometry and default viewport."""
        settings = QSettings()
        geometry = settings.value("window/geometry")
        if geometry is not None:
            with contextlib.suppress(Exception):  # a corrupt stored value
                self.restoreGeometry(geometry)
        raw = settings.value("view/default")
        if isinstance(raw, str) and raw:
            with contextlib.suppress(Exception):  # a settings format change
                self._main_canvas.set_view_settings(ViewSettings.model_validate_json(raw))

    def _save_session_state(self) -> None:
        """Persist the geometry and the default viewport for the next launch."""
        settings = QSettings()
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue("view/default", self._main_canvas.view_settings.model_dump_json())

    def _on_canvas_context_menu(self, pos: QPoint) -> None:
        """Right-click on the model view: grid visibility, labels and grid editing."""
        menu = self._canvas_context_menu()
        menu.exec(pos)
        menu.deleteLater()

    def _canvas_context_menu(self) -> QMenu:
        """What the right-click shows: the selection's options, or grids and view."""
        selection = self._canvas.selection
        if not selection.is_empty:
            return self._selection_context_menu(selection.nodes, selection.elements)
        menu = QMenu(self)
        project = self._vm.project
        if project is not None:
            self._sync_grid_actions()
            menu.addAction(self._act_show_grids)
            if len(project.coord_systems) > 1:
                per_system = menu.addMenu("Grids by system")
                for cs in project.coord_systems:
                    action = per_system.addAction(cs.name)
                    action.setCheckable(True)
                    action.setChecked(not cs.grid.hide_all)
                    action.triggered.connect(
                        lambda checked, name=cs.name: self._set_grids_shown(checked, name)
                    )
            menu.addAction(self._act_show_grid_labels)
            menu.addSeparator()
        menu.addAction(self._act_grid)
        menu.addAction(self._act_grid_wizard)
        menu.addSeparator()
        menu.addAction(self._act_grid_line_view)
        menu.addAction(self._act_show_all_objects)
        menu.addSeparator()
        menu.addActions(
            [self._act_view_iso, self._act_view_top, self._act_view_front, self._act_view_right]
        )
        menu.addAction(self._act_zoom_extents)
        return menu

    def _selection_context_menu(self, nodes: frozenset[int], elements: frozenset[int]) -> QMenu:
        """Right-click with something selected: what can be assigned or edited on it."""
        from opensees_studio.core.geometry import (
            FRAME_ELEMENT_CLASSES,
            QuadElement,
            ShellMITC4Element,
        )

        self._refresh_action_enablement()
        menu = QMenu(self)
        project = self._vm.project
        kinds = [
            type(e) for e in (project.elements if project is not None else []) if e.id in elements
        ]
        frames = sum(1 for k in kinds if issubclass(k, FRAME_ELEMENT_CLASSES))
        areas = sum(1 for k in kinds if issubclass(k, QuadElement | ShellMITC4Element))
        parts = [f"{len(nodes)} joint(s)"] if nodes else []
        if elements:
            parts.append(f"{len(elements)} element(s)")
        header = menu.addAction(", ".join(parts) + " selected")
        header.setEnabled(False)
        menu.addSeparator()
        groups = [
            ("Joint", self._joint_actions, bool(nodes)),
            ("Frame", self._frame_actions, frames > 0),
            ("Area", self._area_actions, areas > 0),
        ]
        wanted = [(title, actions) for title, actions, on in groups if on]
        for title, actions in wanted:
            # One kind selected: its options straight in the menu; several: a submenu each.
            _add_actions(menu if len(wanted) == 1 else menu.addMenu(title), actions)
        if wanted:
            menu.addSeparator()
        menu.addAction(self._act_assign_group)
        menu.addSeparator()
        menu.addActions([self._act_move, self._act_replicate, self._act_mirror])
        menu.addSeparator()
        if elements:
            hide = menu.addAction("Hide Selected Elements")
            hide.triggered.connect(self._on_hide_selected)
        menu.addAction(self._act_isolate_selected)
        if self._act_show_all_objects.isEnabled():
            menu.addAction(self._act_show_all_objects)
        menu.addSeparator()
        menu.addAction(self._act_delete)
        menu.addAction(self._act_clear_selection)
        return menu

    # ── View → Grid Line View ───────────────────────────────────────
    def _on_grid_line_view(self) -> None:
        """Show only the objects on one grid line (± a window) and look at it face on."""
        project = self._vm.project
        if project is None:
            return
        current = self._grid_view[0] if self._grid_view is not None else None
        dlg = GridLineViewDialog(
            project, current=current, window=self._grid_view_window, parent=self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.line() is None:
            return
        ref = dlg.line()
        assert ref is not None
        self._grid_view_window = dlg.tolerance()
        self._grid_view = (ref.label, self._grid_view_window)
        self._apply_grid_line_view()
        self._face_grid_line(ref)

    def _apply_grid_line_view(self) -> None:
        """(Re)install the canvas filter for the current grid line view, if any."""
        from opensees_studio.core.grid_view import (
            filtered_project,
            find_grid_line,
            objects_on_line,
        )

        project = self._vm.project
        state = self._grid_view
        ref = find_grid_line(project, state[0]) if project is not None and state else None
        if state is None or ref is None:
            if state is not None:
                self._log(f"Grid line view: '{state[0]}' no longer exists, showing everything.")
            self._grid_view = None
            self._canvas.set_view_filter(None)
            self._sync_show_all_action()
            return
        window = state[1]

        def keep(full: Project) -> Project:
            nodes, elements = objects_on_line(full, ref, window)
            return filtered_project(full, nodes, elements)

        self._canvas.set_view_filter(keep)
        self._sync_show_all_action()
        nodes, elements = objects_on_line(project, ref, window)  # type: ignore[arg-type]
        self.statusBar().showMessage(
            f"Grid line view {ref.label} ± {window:g}: {len(nodes)} joint(s), "
            f"{len(elements)} element(s). View → Show All Objects to see everything."
        )

    def _face_grid_line(self, ref: Any) -> None:
        """Look at a plane line face on, with its level as the working plane."""
        if ref.cylindrical and ref.axis != 2:
            self._on_view_iso()
            return
        plane = ("YZ", "XZ", "XY")[ref.axis]
        project = self._vm.project
        system = next(cs for cs in project.coord_systems if cs.name == ref.system)  # type: ignore[union-attr]
        point = [0.0, 0.0, 0.0]
        point[ref.axis] = ref.ordinate
        offset = system.coord.local_to_world((point[0], point[1], point[2]))[ref.axis]
        {"YZ": self._on_view_right, "XZ": self._on_view_front, "XY": self._on_view_top}[plane]()
        index = next(
            (
                i
                for i in range(self._level_combo.count())
                if abs(float(self._level_combo.itemData(i)) - offset) < 1e-6
            ),
            -1,
        )
        if index >= 0:
            self._level_combo.setCurrentIndex(index)
        else:
            self._canvas.set_working_plane(plane, offset)
        self._canvas.reframe()

    def _clear_grid_line_view(self) -> None:
        self._grid_view = None
        self._canvas.set_view_filter(None)
        self._canvas.set_hidden(nodes=set(), elements=set())
        self._canvas.reframe()
        self._refresh_action_enablement()
        self.statusBar().showMessage("Showing all objects.", 3000)

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

    def _on_constant_ts(self) -> None:
        if self._vm.project is None:
            return
        from opensees_studio.views.dialogs.constant_time_series import ConstantTimeSeriesDialog

        ConstantTimeSeriesDialog(self._vm, self).exec()

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

    def _on_add_function_ts(self) -> None:
        """Define → Add Function TimeSeries: Constant, Trig, Triangle, Rectangular, Pulse."""
        from opensees_studio.commands import AddTimeSeriesCommand
        from opensees_studio.views.dialogs.function_time_series import FunctionTimeSeriesDialog

        if self._vm.project is None:
            self._on_new()
        proj = self._vm.project
        assert proj is not None
        dlg = FunctionTimeSeriesDialog(next_ts_id=proj.next_time_series_id(), parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            ts = dlg.time_series()
            self._vm.apply_command(AddTimeSeriesCommand(self._vm, ts))
            self._log(f"Added {ts.type} TimeSeries #{ts.id} '{ts.name}'.")
        except Exception as exc:
            QMessageBox.critical(self, "Add TimeSeries failed", str(exc))

    def _on_add_multi_support(self) -> None:
        """Define → Add Multi-Support Excitation: imposed motion of the selected supports."""
        from opensees_studio.commands import AddLoadPatternCommand
        from opensees_studio.views.dialogs.uniform_excitation import MultiSupportExcitationDialog

        proj = self._vm.project
        if proj is None:
            return
        nodes = sorted(self._canvas.selection.nodes)
        if not nodes:
            QMessageBox.information(
                self, "Multi-Support Excitation", "Select the supports to drive first."
            )
            return
        if not proj.time_series:
            QMessageBox.information(
                self,
                "Multi-Support Excitation",
                "Define a displacement time series first (Define → Add Path TimeSeries…).",
            )
            return
        dlg = MultiSupportExcitationDialog(proj, proj.next_pattern_id(), nodes, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            pat = dlg.pattern()
            self._vm.apply_command(AddLoadPatternCommand(self._vm, pat))
            self._log(
                f"Added MultipleSupport pattern #{pat.id} '{pat.name}' on "
                f"{len(pat.node_ids)} support(s), DOF {pat.direction}."
            )
        except Exception as exc:
            QMessageBox.critical(self, "Add Multi-Support Excitation failed", str(exc))

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
        dlg = AssignEqualDOFDialog(
            sel, ndf=self._vm.project.ndf, parent=self, ndm=self._vm.project.ndm
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(AddEqualDOFConstraintCommand(self._vm, dlg.constraint()))
            self._log(f"Added equalDOF constraint between nodes {sel[0]} and {sel[1]}.")
        except Exception as exc:
            QMessageBox.critical(self, "Assign EqualDOF failed", str(exc))

    # ── building: storeys, mass source, diaphragms, rigid links ─────
    def _on_define_storeys(self) -> None:
        project = self._vm.project
        if project is None:
            return
        dlg = StoreysDialog(project, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(SetStoreysCommand(self._vm, dlg.storeys()))
            self._log(f"Storeys set: {len(project.storeys)}.")
        except Exception as exc:
            QMessageBox.critical(self, "Define Storeys failed", str(exc))

    def _on_define_groups(self) -> None:
        """Define → Groups: add, rename, recolour or remove groups."""
        project = self._vm.project
        if project is None:
            return
        dlg = GroupsDialog(project, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(SetGroupsCommand(self._vm, dlg.groups()))
            self._log(f"Groups set: {len(project.groups)}.")
        except Exception as exc:
            QMessageBox.critical(self, "Define Groups failed", str(exc))

    def _on_define_section_cuts(self) -> None:
        """Define → Section Cuts: resultant forces through a group."""
        project = self._vm.project
        if project is None:
            return
        dlg = SectionCutsDialog(project, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(SetSectionCutsCommand(self._vm, dlg.section_cuts()))
            self._log(f"Section cuts set: {len(project.section_cuts)}. Re-run static cases.")
        except Exception as exc:
            QMessageBox.critical(self, "Define Section Cuts failed", str(exc))

    def _on_custom_commands(self) -> None:
        """Define → Custom OpenSees Commands: Python blocks run while the model is built."""
        from opensees_studio.commands import SetCustomCommandsCommand
        from opensees_studio.views.dialogs.custom_commands import CustomCommandsDialog

        project = self._vm.project
        if project is None:
            return
        dlg = CustomCommandsDialog(project, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(SetCustomCommandsCommand(self._vm, dlg.blocks()))
            enabled = sum(1 for b in project.custom_commands if b.enabled)
            self._log(f"Custom command blocks: {len(project.custom_commands)} ({enabled} enabled).")
        except Exception as exc:
            QMessageBox.critical(self, "Custom OpenSees Commands failed", str(exc))

    def _on_assign_group(self) -> None:
        """Assign → Assign to Group: add the selection to a group, remove it, or replace."""
        project = self._vm.project
        if project is None:
            return
        sel = self._canvas.selection
        nodes, elements = sorted(sel.nodes), sorted(sel.elements)
        if not nodes and not elements:
            QMessageBox.information(self, "Assign to Group", "Select joints or elements first.")
            return
        dlg = AssignGroupDialog(project, len(nodes), len(elements), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        group_id, mode = dlg.group_id, dlg.mode
        try:
            self._vm.undo_stack.beginMacro("Assign to group")
            try:
                if group_id == NEW_GROUP:
                    group_id = project.next_group_id()
                    group = Group(
                        id=group_id,
                        name=dlg.new_name.text().strip(),
                        colour=colour_for(len(project.groups)),
                    )
                    self._vm.apply_command(SetGroupsCommand(self._vm, [*project.groups, group]))
                self._vm.apply_command(
                    EditGroupMembersCommand(self._vm, group_id, nodes, elements, mode=mode)
                )
            finally:
                self._vm.undo_stack.endMacro()
            group = next(g for g in project.groups if g.id == group_id)
            self._log(
                f"Group {group.name}: {len(group.node_ids)} joint(s), "
                f"{len(group.element_ids)} element(s)."
            )
        except Exception as exc:
            QMessageBox.critical(self, "Assign to Group failed", str(exc))

    def _on_define_seismic_loads(self) -> None:
        """Define → Seismic Loads: ELF base shear and storey forces as load patterns."""
        if self._vm.project is None:
            return
        dlg = SeismicLoadsDialog(self._vm, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.written:
            self._log(
                "Seismic loads written: " + ", ".join(dlg.written) + ". " + dlg.summary.text()
            )

    def _on_define_mass_source(self) -> None:
        project = self._vm.project
        if project is None:
            return
        dlg = MassSourceDialog(project, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(SetMassSourceCommand(self._vm, dlg.mass_source()))
            self._log("Mass source updated.")
        except Exception as exc:
            QMessageBox.critical(self, "Define Mass Source failed", str(exc))

    def _on_assign_diaphragm(self) -> None:
        project = self._vm.project
        if project is None:
            return
        dlg = AssignDiaphragmDialog(project, sorted(self._canvas.selection.nodes), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            diaphragm, retained = dlg.diaphragm()
            self._vm.apply_command(AddDiaphragmCommand(self._vm, diaphragm, retained))
            where = f"new node {retained.id}" if retained else f"node {diaphragm.retained_node}"
            self._log(f"Added rigid diaphragm {diaphragm.name or diaphragm.id}, retained {where}.")
        except Exception as exc:
            QMessageBox.critical(self, "Assign Diaphragm failed", str(exc))

    def _on_assign_rigid_link(self) -> None:
        sel = sorted(self._canvas.selection.nodes)
        if len(sel) != 2 or self._vm.project is None:
            QMessageBox.information(self, "Assign Rigid Link", "Select exactly two nodes first.")
            return
        dlg = AssignRigidLinkDialog(sel, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            link = dlg.link()
            self._vm.apply_command(AddRigidLinkCommand(self._vm, link))
            self._log(
                f"Added rigid {link.kind} link {link.retained_node} -> {link.constrained_node}."
            )
        except Exception as exc:
            QMessageBox.critical(self, "Assign Rigid Link failed", str(exc))

    def _on_remove_constraints(self) -> None:
        sel = set(self._canvas.selection.nodes)
        if not sel or self._vm.project is None:
            return
        self._vm.apply_command(RemoveConstraintsCommand(self._vm, sel))
        self._log(f"Removed the constraints of {len(sel)} node(s).")

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
        command = self._convert_command({element_id}, new_type)
        if command is None:
            return
        try:
            self._vm.apply_command(command)
            self._log(f"Element {element_id} → {new_type}.")
        except Exception as exc:
            QMessageBox.critical(self, "Convert element failed", str(exc))

    def _convert_command(self, element_ids: set[int], new_type: str) -> Any:
        """The command converting ``element_ids`` to ``new_type``, None if it cannot."""
        from opensees_studio.commands import ConvertElementTypeCommand

        project = self._vm.project
        if project is None:
            return None
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
                return None
            defaults["material_id"] = mat.id
            defaults["area"] = 0.001
        elif new_type in ("ElasticBeamColumn", "ForceBeamColumn", "DispBeamColumn"):
            if not project.sections:
                QMessageBox.warning(
                    self,
                    "Convert element",
                    f"Define a section before converting to {new_type}.",
                )
                return None
            defaults["section_id"] = project.sections[0].id
        return ConvertElementTypeCommand(self._vm, element_ids, new_type, defaults=defaults)

    # ── property editor: multi-selection edits (one undo step each) ──
    def _on_assign_node_restraints(self, restraints: dict[int, tuple[bool, ...]]) -> None:
        self._apply_grouped(restraints, SetRestraintCommand, "Edit restraints")

    def _on_assign_node_masses(self, masses: dict[int, tuple[float, ...]]) -> None:
        self._apply_grouped(masses, SetMassCommand, "Edit masses")

    def _apply_grouped(self, values: dict[int, Any], command: Any, text: str) -> None:
        """One command per distinct value, all in one undo step."""
        groups: dict[Any, set[int]] = {}
        for node_id, value in values.items():
            groups.setdefault(tuple(value), set()).add(node_id)
        stack = self._vm.undo_stack
        stack.beginMacro(f"{text} of {len(values)} joint(s)")
        try:
            for value, ids in groups.items():
                self._vm.apply_command(command(self._vm, ids, value))
        except Exception as exc:
            QMessageBox.critical(self, text, str(exc))
        finally:
            stack.endMacro()

    def _on_assign_elements(self, edit: Any) -> None:
        """Properties dock, several elements: type, section, material and fields at once."""
        from opensees_studio.commands import AssignElementFieldsCommand

        ids = set(edit.element_ids)
        convert = None
        if edit.new_type is not None:
            convert = self._convert_command(ids, edit.new_type)
            if convert is None:
                return
        stack = self._vm.undo_stack
        stack.beginMacro(f"Edit {len(ids)} element(s)")
        try:
            # The type first: the other edits then apply to what the elements became.
            if convert is not None:
                self._vm.apply_command(convert)
            project = self._vm.project
            assert project is not None
            has = {
                key: {e.id for e in project.elements if e.id in ids and hasattr(e, key)}
                for key in ("section_id", "material_id")
            }
            if edit.material_id is not None and has["material_id"]:
                self._vm.apply_command(
                    AssignMaterialCommand(self._vm, has["material_id"], edit.material_id)
                )
            for key, value in edit.fields.items():
                # One field at a time: each lands on the elements that have it.
                self._vm.apply_command(AssignElementFieldsCommand(self._vm, ids, {key: value}))
            if edit.per_element:
                self._vm.apply_command(
                    AssignElementFieldsCommand(
                        self._vm, set(edit.per_element), {}, per_element=edit.per_element
                    )
                )
            # The section goes last: assigning a nonprismatic template splits the
            # member into pieces, and it must see the other edits on the frame.
            if edit.section_id is not None and has["section_id"]:
                self._vm.apply_command(
                    AssignSectionCommand(self._vm, has["section_id"], edit.section_id)
                )
            self._log(f"Edited {len(ids)} element(s) from the Properties panel.")
        except Exception as exc:
            QMessageBox.critical(self, "Edit elements failed", str(exc))
        finally:
            stack.endMacro()

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

    def _on_assign_link(self) -> None:
        """Assign > Joint > Link: a twoNodeLink or a Triple Friction Pendulum between two joints."""
        from opensees_studio.commands import AddElementsCommand
        from opensees_studio.views.dialogs.assign_link import AssignLinkDialog

        sel = sorted(self._canvas.selection.nodes)
        project = self._vm.project
        if len(sel) != 2 or project is None:
            QMessageBox.information(self, "Assign Link", "Select exactly two joints first.")
            return
        dlg = AssignLinkDialog(project, (sel[0], sel[1]), parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            element = dlg.build_element(project.next_element_id())
            self._vm.apply_command(AddElementsCommand(self._vm, [element]))
            self._log(f"Created {element.type} {element.id} between joints {sel[0]}-{sel[1]}.")
        except Exception as exc:
            QMessageBox.critical(self, "Assign Link failed", str(exc))

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
        dlg = AssignMassesDialog(
            len(sel_nodes), ndf=self._vm.project.ndf, ndm=self._vm.project.ndm, parent=self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(SetMassCommand(self._vm, sel_nodes, dlg.mass_vector()))
            self._log(f"Assigned mass to {len(sel_nodes)} node(s).")
        except Exception as exc:
            QMessageBox.critical(self, "Assign Masses failed", str(exc))

    def _on_assign_springs(self) -> None:
        """Assign → Joint → Springs: elastic support springs on every selected joint."""
        project = self._vm.project
        sel_nodes = set(self._canvas.selection.nodes)
        if not sel_nodes or project is None:
            QMessageBox.information(self, "Assign Springs", "Select one or more joints first.")
            return
        first = next(n for n in project.nodes if n.id in sel_nodes)
        labels = labels_for(project.meta.units)
        dlg = AssignSpringsDialog(
            len(sel_nodes),
            project.ndm,
            project.ndf,
            current=first.spring,
            units=(f"{labels.force}/{labels.length}", f"{labels.moment}/rad"),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(SetSpringCommand(self._vm, sel_nodes, dlg.spring_vector()))
            self._log(f"Assigned support springs to {len(sel_nodes)} joint(s).")
        except Exception as exc:
            QMessageBox.critical(self, "Assign Springs failed", str(exc))

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

    def _on_assign_temperature_load(self) -> None:
        """Assign → Frame → Temperature Load: uniform ΔT and gradients on the selected members.

        Every selected member is checked before anything changes: the method needs
        elastic members without releases or end offsets (see ``core.thermal``).
        """
        from opensees_studio.core import TemperatureLoad
        from opensees_studio.core.thermal import ThermalLoadError, fixed_end_forces

        project = self._vm.project
        selected = set(self._canvas.selection.elements)
        if project is None or not selected:
            QMessageBox.information(
                self, "Assign Temperature Load", "Select one or more frame members first."
            )
            return
        refused = []
        for element_id in sorted(selected):
            try:
                fixed_end_forces(project, TemperatureLoad(element_id=element_id, alpha=1.0))
            except ThermalLoadError as exc:
                refused.append(str(exc))
        if refused:
            QMessageBox.warning(self, "Assign Temperature Load", "\n".join(refused[:8]))
            return
        dialog = AssignTemperatureLoadDialog(len(selected), ndm=project.ndm, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            values = dialog.values()
            self._vm.apply_command(
                AddTemperatureLoadsCommand(
                    self._vm,
                    selected,
                    alpha=values["alpha"],
                    uniform=values["uniform"],
                    gradient_y=values["gradient_y"],
                    gradient_z=values["gradient_z"],
                )
            )
        except Exception as exc:
            QMessageBox.critical(self, "Assign Temperature Load failed", str(exc))

    def _on_assign_frame_point_load(self) -> None:
        """Assign → Frame → Point Load: a concentrated load inside each selected frame."""
        from opensees_studio.core import FRAME_ELEMENT_CLASSES
        from opensees_studio.views.dialogs.point_element_load import RELATIVE

        project = self._vm.project
        selected = set(self._canvas.selection.elements)
        if project is None or not selected:
            QMessageBox.information(
                self, "Assign Frame Point Load", "Select one or more frame elements first."
            )
            return
        frames = [
            el
            for el in project.elements
            if el.id in selected and isinstance(el, FRAME_ELEMENT_CLASSES)
        ]
        if not frames:
            QMessageBox.information(
                self,
                "Assign Frame Point Load",
                "None of the selected elements is a frame (beam-column) element.",
            )
            return
        dlg = AssignPointElementLoadDialog(len(frames), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        py, pz, px = dlg.values()

        positions: dict[int, float] = {}
        too_short: list[int] = []
        coords = {node.id: node.coords for node in project.nodes}
        for el in frames:
            if dlg.mode() == RELATIVE:
                positions[el.id] = dlg.distance()
                continue
            length = math.dist(coords[el.nodes[0]], coords[el.nodes[1]])
            if length <= 0.0 or dlg.distance() > length:
                too_short.append(el.id)
                continue
            positions[el.id] = dlg.distance() / length
        if not positions:
            QMessageBox.warning(
                self,
                "Assign Frame Point Load",
                "The distance is longer than every selected element.",
            )
            return
        try:
            self._vm.apply_command(
                AddPointElementLoadsCommand(self._vm, positions, py=py, pz=pz, px=px),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Assign Frame Point Load failed", str(exc))
            return
        skipped = len(selected) - len(frames)
        message = f"Assigned a point load to {len(positions)} frame element(s)."
        if skipped:
            message += f" Skipped {skipped} element(s) that are not frames."
        if too_short:
            message += " Skipped element(s) shorter than the distance: " + ", ".join(
                str(eid) for eid in too_short
            )
        self._log(message)

    def _on_assign_wall(self) -> None:
        """Assign → Frame → RC Wall: selected vertical members to MVLEM, one undo step."""
        from opensees_studio.commands import AddMaterialsCommand, ReplaceElementsCommand
        from opensees_studio.views.dialogs.assign_wall import AssignWallDialog

        project = self._vm.project
        selected = set(self._canvas.selection.elements)
        if project is None or not selected:
            QMessageBox.information(
                self, "RC Wall", "Select the vertical members of the wall first."
            )
            return
        dialog = AssignWallDialog(project, selected, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        conversion = dialog.conversion()
        if conversion is None or not conversion.elements:
            return
        stack = self._vm.undo_stack
        stack.beginMacro("Assign RC wall")
        try:
            if conversion.materials:
                self._vm.apply_command(AddMaterialsCommand(self._vm, conversion.materials))
            self._vm.apply_command(ReplaceElementsCommand(self._vm, conversion.elements))
        finally:
            stack.endMacro()
        self._log(
            f"RC wall: {len(conversion.elements)} member(s) became MVLEM segments"
            + (f", {len(conversion.skipped)} left as they were." if conversion.skipped else ".")
        )

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
                        # Keep the member's weight per length: gamma on the new A.
                        unit_weight=section_weight_per_length(
                            self._vm.project, getattr(el, "section_id", 0)
                        )
                        / vals["A"],
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

    def _on_concrete_section(self) -> None:
        """Define → Concrete Section Wizard: materials and sections in one undo step."""
        from opensees_studio.views.dialogs.concrete_section import ConcreteSectionDialog

        if self._vm.project is None:
            self._on_new()
        project = self._vm.project
        if project is None:
            return
        dialog = ConcreteSectionDialog(project, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        result = dialog.built_section()
        if result is None:
            return
        sections = [s for s in (result.fiber, result.elastic) if s is not None]
        self._add_materials_and_sections("Concrete section", result.materials, sections)

    def _on_section_designer(self) -> None:
        """Define → Section Designer: a drawn or imported section, added in one undo step."""
        from opensees_studio.views.dialogs.section_designer import SectionDesignerDialog

        if self._vm.project is None:
            self._on_new()
        project = self._vm.project
        if project is None:
            return
        dialog = SectionDesignerDialog(project, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        section = dialog.built_section()
        if section is not None:
            self._add_materials_and_sections("Designed section", [], [section])

    def _add_materials_and_sections(
        self, text: str, materials: list[Any], sections: list[Any]
    ) -> None:
        """Add ``materials`` then ``sections`` as one undo step, and say what was added."""
        from opensees_studio.commands import AddMaterialsCommand

        stack = self._vm.undo_stack
        stack.beginMacro(text)
        try:
            if materials:
                self._vm.apply_command(AddMaterialsCommand(self._vm, materials))
            if sections:
                self._vm.apply_command(AddSectionsCommand(self._vm, sections))
        finally:
            stack.endMacro()
        names = ", ".join(f"#{s.id} {s.name}" for s in sections)
        self._log(f"{text}: added {len(materials)} material(s) and section(s) {names}.")

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

    def _frame_option_dialog(self, title: str, field: str) -> tuple[set[int], Any] | None:
        """Selected frame members and the value of ``field`` they share (None when they differ)."""
        from opensees_studio.core import FrameMember

        project = self._vm.project
        selected = set(self._canvas.selection.elements)
        frames = (
            []
            if project is None
            else [
                el for el in project.elements if el.id in selected and isinstance(el, FrameMember)
            ]
        )
        if not frames:
            QMessageBox.information(self, title, "Select one or more frame elements first.")
            return None
        values = [getattr(el, field) for el in frames]
        shared = values[0] if all(v == values[0] for v in values) else None
        return {el.id for el in frames}, shared

    # ── area loads and imposed displacements ─────────────────────────
    def _on_assign_surface_load(self) -> None:
        """Assign > Area > Surface Load on Shells: a uniform pressure on the selected shells."""
        from opensees_studio.core import SurfaceLoad

        project = self._vm.project
        if project is None:
            return
        selected = set(self._canvas.selection.elements)
        shells = sorted(
            el.id
            for el in project.elements
            if el.id in selected and isinstance(el, ShellMITC4Element)
        )
        if not shells:
            QMessageBox.information(self, "Surface Load", "Select one or more shells first.")
            return
        dlg = SurfaceLoadDialog(len(shells), project, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        values = dlg.values()
        loads = [SurfaceLoad(element_id=eid, **values) for eid in shells]
        self._apply_pattern_loads("surface_loads", loads, dlg.pattern_id(), "Surface Load")
        self._log(
            f"Surface load {values['value']:g} ({values['direction']}) on {len(shells)} shell(s)."
        )

    def _on_assign_floor_load(self) -> None:
        """Assign > Area > Floor Load to Frames: every bay the selected joints frame."""
        from opensees_studio.core.area_loads import floor_panels

        project = self._vm.project
        if project is None:
            return
        panels = floor_panels(project, set(self._canvas.selection.nodes))
        if not panels:
            QMessageBox.information(
                self,
                "Floor Load",
                "Select the joints of a floor: the load goes to every rectangular bay whose "
                "four corners are selected and whose four sides are framed by beams.",
            )
            return
        dlg = FloorLoadDialog(panels, project, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        loads = dlg.loads()
        self._apply_pattern_loads("floor_loads", loads, dlg.pattern_id(), "Floor Load")
        self._log(f"Floor load on {len(loads)} bay(s).")

    def _on_assign_imposed_displacement(self) -> None:
        """Assign > Joint > Imposed Displacement: a static settlement of the selected joints."""
        project = self._vm.project
        nodes = sorted(self._canvas.selection.nodes)
        if project is None or not nodes:
            return
        dlg = ImposedDisplacementDialog(len(nodes), project, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_pattern_loads(
            "imposed_displacements", dlg.loads(nodes), dlg.pattern_id(), "Imposed Displacement"
        )
        self._log(f"Imposed displacement on {len(nodes)} joint(s).")

    def _apply_pattern_loads(
        self, list_name: str, loads: list[Any], pattern_id: int | None, title: str
    ) -> None:
        from opensees_studio.commands import AddPatternLoadsCommand

        try:
            self._vm.apply_command(AddPatternLoadsCommand(self._vm, list_name, loads, pattern_id))
        except Exception as exc:
            QMessageBox.critical(self, f"{title} failed", str(exc))

    def _on_assign_releases(self) -> None:
        """Assign > Frame > Releases/Partial Fixity."""
        picked = self._frame_option_dialog("Frame Releases", "releases")
        if picked is None or self._vm.project is None:
            return
        ids, current = picked
        dlg = FrameReleasesDialog(len(ids), self._vm.project.ndm, current, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._assign_element_fields("Frame Releases", ids, {"releases": dlg.releases()})

    def _on_assign_end_offsets(self) -> None:
        """Assign > Frame > End (Length) Offsets."""
        picked = self._frame_option_dialog("Frame End Offsets", "end_offsets")
        if picked is None:
            return
        ids, current = picked
        dlg = FrameEndOffsetsDialog(len(ids), current, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        offsets = dlg.offsets()
        if not dlg.automatic:
            self._assign_element_fields("Frame End Offsets", ids, {"end_offsets": offsets})
            return
        from opensees_studio.commands import AssignElementFieldsCommand
        from opensees_studio.core.frame_members import connectivity_offsets

        project = self._vm.project
        assert project is not None
        try:
            per_element = {}
            for i in ids:
                li, lj = connectivity_offsets(project, i)
                per_element[i] = {
                    "end_offsets": offsets.model_copy(update={"length_i": li, "length_j": lj})
                }
            self._vm.apply_command(
                AssignElementFieldsCommand(
                    self._vm,
                    ids,
                    {"end_offsets": offsets},
                    per_element=per_element,
                    text=f"Assign automatic end offsets to {len(ids)} element(s)",
                )
            )
            self._log(f"Frame End Offsets (from connectivity) on {len(ids)} element(s).")
        except Exception as exc:
            QMessageBox.critical(self, "Frame End Offsets failed", str(exc))

    def _on_assign_insertion(self) -> None:
        """Assign > Frame > Insertion Point."""
        picked = self._frame_option_dialog("Frame Insertion Point", "insertion")
        if picked is None or self._vm.project is None:
            return
        ids, current = picked
        dlg = FrameInsertionDialog(len(ids), self._vm.project.ndm, current, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._assign_element_fields(
                "Frame Insertion Point", ids, {"insertion": dlg.insertion()}
            )

    def _on_assign_modifiers(self) -> None:
        """Assign > Frame > Property Modifiers."""
        picked = self._frame_option_dialog("Frame Property Modifiers", "modifiers")
        if picked is None:
            return
        ids, current = picked
        dlg = FrameModifiersDialog(len(ids), current, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._assign_element_fields(
                "Frame Property Modifiers", ids, {"modifiers": dlg.modifiers()}
            )

    def _on_assign_trapezoidal_load(self) -> None:
        """Assign > Frame > Trapezoidal Load: a linearly varying load over part of each member."""
        picked = self._frame_option_dialog("Frame Trapezoidal Load", "releases")
        if picked is None or self._vm.project is None:
            return
        ids, _ = picked
        dlg = TrapezoidalLoadDialog(len(ids), self._vm.project.ndm, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._vm.apply_command(AddTrapezoidalElementLoadsCommand(self._vm, ids, dlg.values()))
        except Exception as exc:
            QMessageBox.critical(self, "Assign Frame Trapezoidal Load failed", str(exc))
            return
        self._log(f"Assigned a trapezoidal load to {len(ids)} frame element(s).")

    # ── slots: analyze ──────────────────────────────────────────────
    def _on_check_stability(self) -> None:
        """Analyze → Check Model Stability: look for mechanisms before solving anything."""
        project = self._vm.project
        if project is None:
            return
        if not project.nodes:
            QMessageBox.information(self, "Check Model Stability", "The model has no joints yet.")
            return
        self._stability.check(project, self._vm.path)

    def _on_stability_progress(self, phase: str, message: str) -> None:
        """Show the coarse stability phase in the status bar and console."""
        self._log(f"Stability [{phase}]: {message}")

    def _on_stability_report(self, report: StabilityReport) -> None:
        summary = report.summary()
        self._log(summary)
        if report.nodes:
            # Show where the mechanisms are: their joints become the selection.
            self._canvas.selection.set_selection(set(report.nodes), set())
            self._refresh_action_enablement()
        box = QMessageBox(self)
        box.setWindowTitle("Check Model Stability")
        box.setIcon(QMessageBox.Icon.Information if report.stable else QMessageBox.Icon.Warning)
        if report.completion != "complete":
            headline = "The stability check is incomplete."
        elif report.classification == "no_free_equations":
            headline = "The model is fully restrained."
        elif report.stable:
            headline = "The model is statically stable."
        else:
            headline = "The model is not statically stable."
        box.setText(headline)
        box.setInformativeText(
            summary + ("\n\nThe joints that move are selected." if report.nodes else "")
        )
        box.open()
        self._stability_box = box

    def _on_stability_failed(self, message: str) -> None:
        self._log(message)
        box = QMessageBox(self)
        box.setWindowTitle("Check Model Stability")
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText("The stability check could not finish.")
        box.setInformativeText(message)
        box.open()
        self._stability_box = box

    def _on_case_manager(self) -> None:
        if self._vm.project is None:
            self._on_new()
        AnalysisCaseManagerDialog(self._vm, self).exec()

    def _on_run_all_cases(self) -> None:
        """Analyze → Run All Cases: every case, in one child process."""
        project = self._vm.project
        if project is None or self._runner.is_running:
            return
        if not project.analyses:
            self._log("No analysis cases. Define one in Analyze → Cases…")
            return
        self._log(f"Running all {len(project.analyses)} case(s).")
        self._start_batch(list(project.analyses))

    def _on_run_selected_cases(self) -> None:
        """Analyze → Run Selected Cases: tick the cases, then run them together."""
        project = self._vm.project
        if project is None or self._runner.is_running:
            return
        if not project.analyses:
            self._log("No analysis cases. Define one in Analyze → Cases…")
            return
        dialog = RunCasesDialog(project, self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            chosen = set(dialog.selected_case_ids())
        finally:
            dialog.deleteLater()
        cases = [case for case in project.analyses if case.id in chosen]
        if not cases:
            self._log("No case selected.")
            return
        self._log(f"Running {len(cases)} selected case(s).")
        self._start_batch(cases)

    def _start_batch(self, cases: list[Any]) -> None:
        """Hand a set of cases to the runner in one child process."""
        project = self._vm.project
        if project is None:
            return
        try:
            self._runner.run_cases(project, cases, project_path=self._vm.path)
        except Exception as exc:
            self._log(f"Could not start: {exc}")

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
        if not report.is_complete:
            # A partial check is not a pass: say what was left out.
            for finding in report.infos:
                self._log(finding.summary())
            self._log(report.summary())
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
        dlg = RunAnalysisDialog(self._vm, self._runner, self, case_results=self._case_results)
        combination_finished = getattr(dlg, "combinationFinished", None)
        if combination_finished is not None:
            combination_finished.connect(self._on_analysis_finished)
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
        self._display_results(results)
        self._log(f"Analysis complete: {type(results).__name__}.")
        if isinstance(results, TransientResults) and results.early_stop:
            self._log(f"Warning: transient run did not converge ({results.steps_summary()}).")
        if isinstance(results, ResponseSpectrumResults | CombinationResults):
            for warning in results.warnings:
                self._log(f"Warning: {warning}")
        self._set_result_caption(self._caption_for(results))
        self._refresh_action_enablement()

    def _on_case_finished(self, results: object) -> None:
        """Keep each case result of a run for the load combinations."""
        self._keep_case_results(results)
        self._record_case_results(results)

    def _keep_case_results(self, results: object) -> None:
        if self._vm.project is not None and not self._case_results.put(self._vm.project, results):
            # Modal, pushover and transient results: kept for the report only.
            case_id = getattr(results, "case_id", None)
            if case_id is not None:
                self._report_extra[case_id] = (model_fingerprint(self._vm.project), results)

    # ── what the viewport is showing ────────────────────────────────
    def _caption_for(self, results: object) -> str:
        """One line naming the results on screen, for the viewport's top-left."""
        if isinstance(results, CombinationResults):
            kind = "envelope" if not results.single_valued else "combination"
            return f"{results.combination_name}  ·  {kind}"
        name = getattr(results, "case_name", "") or f"case {getattr(results, 'case_id', '?')}"
        kind = type(results).__name__.removesuffix("Results")
        return f"{name}  ·  {kind}"

    def _set_result_caption(self, text: str | None) -> None:
        """Put ``text`` in every viewport: the main one and each view window."""
        canvases = [self._main_canvas, *(window.canvas for window in self._view_windows)]
        for canvas in canvases:
            canvas.set_result_label(text)

    def _on_clear_results(self) -> None:
        """Analyze → Delete All Results: forget every stored result."""
        project = self._vm.project
        db_path = database_path(self._vm.path)
        answer = QMessageBox.question(
            self,
            "Delete All Results",
            "Delete every stored result?\n\n"
            "  • the results of this session\n"
            f"  • {db_path}\n\n"
            "The model, its analysis cases and any other project's database are "
            "not touched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._case_results.clear()
        self._report_extra.clear()
        self._latest_results = None
        self._refresh_reactions()
        self._refresh_case_combo()
        self._on_back_to_model()
        self._results_panel.show_results(None, project)
        removed = delete_all_results(db_path)
        self._log(
            "All results deleted."
            if removed
            else "All results deleted (the database was already empty)."
        )
        self._refresh_action_enablement()

    def _record_case_results(self, results: object) -> None:
        """Append this case's results to the project's queryable database.

        A failure here must never fail the analysis: the run already happened,
        so the database is reported as a warning and the results stay in memory.
        """
        try:
            run_id = record_results(results, project_path=self._vm.path, project=self._vm.project)
        except Exception as exc:
            self._log(f"Warning: the results database was not written: {exc}")
            return
        if run_id is not None:
            self._log(f"Results recorded in {database_path(self._vm.path)} (run {run_id}).")

    # ── slots: load combinations ────────────────────────────────────
    def _on_load_combinations(self) -> None:
        """Define → Load Combinations…"""
        if self._vm.project is None:
            self._on_new()
        dlg = LoadCombinationsDialog(self._vm, self)
        try:
            dlg.exec()
        finally:
            dlg.deleteLater()

    def _result_choices(self) -> list[tuple[str, str]]:
        """``(label, key)`` for every result Display can show without running anything.

        Case results still current for the model (``case:<id>``), then every load
        combination (``combination:<id>``), whether or not its cases have run.
        """
        project = self._vm.project
        if project is None:
            return []
        current = self._case_results.current(project)
        names = {c.id: c.name for c in project.analyses}
        choices = [
            (f"Case: {names.get(cid, cid)}  [{type(r).__name__}]", f"case:{cid}")
            for cid, r in sorted(current.items())
        ]
        choices += [(f"Combination: {c.name}", f"combination:{c.id}") for c in project.combinations]
        return choices

    def show_results_of(self, key: str) -> bool:
        """Make ``case:<id>`` or ``combination:<id>`` the results Display shows.

        A combination is combined from the current case results; when some of its
        cases have none, the message says to run it from Analyze → Run.
        """
        project = self._vm.project
        if project is None:
            return False
        kind, _, raw_id = key.partition(":")
        ref_id = int(raw_id)
        if kind == "case":
            results = self._case_results.current(project).get(ref_id)
            if results is None:
                self._log(f"Case {ref_id} has no current results: run it first.")
                return False
        else:
            try:
                results = self._case_results.combine(project, ref_id)
            except (MissingCaseResultsError, ValueError, KeyError) as exc:
                QMessageBox.information(
                    self,
                    "Show Results Of",
                    f"{exc}\n\nAnalyze → Run, then pick the combination: it runs only the "
                    "cases without current results.",
                )
                return False
        self._on_back_to_model()
        self._on_analysis_finished(results)
        return True

    def _on_select_results(self) -> None:
        """Display → Show Results Of…: switch between stored case and combination results."""
        choices = self._result_choices()
        if not choices:
            QMessageBox.information(
                self,
                "Show Results Of",
                "No results yet: run a case (Analyze → Run) or define a load combination.",
            )
            return
        label, ok = QInputDialog.getItem(
            self, "Show Results Of", "Results:", [c[0] for c in choices], 0, False
        )
        if ok:
            self.show_results_of(dict(choices)[label])

    def _static_result(self, bound: str = "max") -> StaticResults | None:
        """The static result Display draws: a static case, or one bound of a combination."""
        results = self._latest_results
        if isinstance(results, StaticResults):
            return results
        if isinstance(results, CombinationResults):
            return results.bound(bound)
        return None

    def _is_envelope(self) -> bool:
        """True when the shown result has a maximum and a minimum (two diagrams, two shapes)."""
        results = self._latest_results
        return isinstance(results, CombinationResults) and not results.single_valued

    def _diagram_data(self, component: ForceComponent) -> DiagramData:
        """Diagram data of the shown result; an envelope draws its max and min together."""
        project = self._vm.project
        results = self._latest_results
        if project is not None and isinstance(results, CombinationResults) and self._is_envelope():
            return envelope_diagram_data(project, results.max, results.min, component)
        static = self._static_result()
        if project is None or static is None:
            return DiagramData(component, np.zeros(0, dtype=int), np.zeros(0), np.zeros(0), 0.0)
        # Stations read the case's loads back: only for a case's own results, not a combination's.
        return extract_diagram_data(
            project, static, component, stations=isinstance(self._latest_results, StaticResults)
        )

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
            view_settings=self._canvas.view_settings,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._show_node_labels, self._show_element_labels = dlg.values()
        settings = dlg.view_settings()
        self._canvas.set_view_settings(settings)
        self._sync_visibility_actions()
        self._log(
            f"Display options updated: node labels={'on' if self._show_node_labels else 'off'}, "
            f"element labels={'on' if self._show_element_labels else 'off'}, "
            f"node size={settings.node_size_percent:g}% of the view height."
        )

    # ── slots: display (post-processing) ────────────────────────────
    def _on_show_deformed(self) -> None:
        static = self._static_result()
        if static is None or self._vm.project is None:
            QMessageBox.information(
                self,
                "Deformed Shape",
                "Run a Static analysis or a load combination first (Display works on the "
                "latest results).",
            )
            return
        self._tear_down_post_dock()
        suggested = linear_static_auto_scale(self._vm.project, static)
        view = DeformedShapeView(suggested_scale=suggested)
        view.show_bounds(self._is_envelope())
        dock = QDockWidget("Deformed Shape", self)
        dock.setWidget(view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._post_dock = dock

        def _apply(scale: float) -> None:
            current = self._static_result(view.current_bound())
            if current is None or self._vm.project is None:
                return
            src = static_to_deformation(self._vm.project, current, scale=scale)
            self._canvas._renderer.set_mode(RendererMode.DEFORMED, src)
            self._canvas.render()

        def _on_bound(bound: str) -> None:
            current = self._static_result(bound)
            if current is not None and self._vm.project is not None:
                view.set_peak_displacement(peak_static_displacement(self._vm.project, current))
            _apply(view.current_scale)

        view.scaleChanged.connect(_apply)
        view.boundChanged.connect(_on_bound)
        view.closed.connect(self._on_back_to_model)
        view.set_units(UnitConverter.of(self._vm.project.meta))
        view.set_peak_displacement(peak_static_displacement(self._vm.project, static))
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

    def _reaction_rows(self) -> list[ReactionRow]:
        """The reactions of the case on screen, or none when there are no results."""
        project = self._vm.project
        results = self._latest_results
        if project is None or results is None:
            return []
        return reaction_rows(project, getattr(results, "node_reaction", None))

    def _refresh_reactions(self) -> None:
        """Keep the table and the overlay on the same case, and enable the actions."""
        rows = self._reaction_rows()
        self._reactions_panel.set_rows(rows)
        self._canvas.set_reactions(rows, show=self._act_show_reactions.isChecked())
        enabled = bool(rows)
        self._act_show_reactions.setEnabled(enabled)
        self._act_reactions_table.setEnabled(enabled)
        self._act_reactions_dialog.setEnabled(enabled)
        if not enabled and self._act_show_reactions.isChecked():
            self._act_show_reactions.setChecked(False)

    def _on_show_reactions(self, checked: bool) -> None:
        self._canvas.set_reactions(self._reaction_rows(), show=checked)

    def _on_reactions_dialog(self) -> None:
        dialog = ReactionsDialog(self._reaction_rows(), self)
        dialog.exec()

    def _on_reactions_table(self) -> None:
        self._reactions_dock.show()
        self._reactions_dock.raise_()

    def _refresh_case_combo(self) -> None:
        """List the cases that still hold results for this model, newest order."""
        project = self._vm.project
        entries = self._case_results.current(project) if project is not None else {}
        current = getattr(self._latest_results, "case_id", None)
        self._case_combo.blockSignals(True)
        self._case_combo.clear()
        for case_id, results in sorted(entries.items()):
            kind = type(results).__name__.removesuffix("Results")
            name = getattr(results, "case_name", None) or f"Case {case_id}"
            self._case_combo.addItem(f"{name} · {kind}", case_id)
        if current is not None:
            index = self._case_combo.findData(current)
            if index >= 0:
                self._case_combo.setCurrentIndex(index)
        self._case_combo.blockSignals(False)
        self._case_combo.setEnabled(bool(entries))
        self._refresh_step_buttons()

    def _on_case_changed(self, index: int) -> None:
        """Show the chosen case; the layers read it from `_latest_results`."""
        case_id = self._case_combo.itemData(index)
        project = self._vm.project
        if case_id is None or project is None:
            return
        results = self._case_results.current(project).get(case_id)
        if results is not None and results is not self._latest_results:
            self._display_results(results)

    def _display_results(self, results: object) -> None:
        """Point the whole window at one results case."""
        self._latest_results = results
        self._results_panel.show_results(results, self._vm.project)
        self._refresh_reactions()
        self._refresh_case_combo()
        self._set_result_caption(self._caption_for(results))
        self._refresh_action_enablement()
        self._refresh_step_buttons()

    def _refresh_step_buttons(self) -> None:
        """Enable the step arrows only when the shown case has more than one."""
        steps = int(getattr(self._latest_results, "n_steps", 1) or 1)
        # Only a layer that knows how to redraw itself at another step registers
        # an applier; until one does, the arrows must not pretend to work.
        steppable = steps > 1 and getattr(self, "_step_apply", None) is not None
        self._step_index = min(getattr(self, "_step_index", 0), max(steps - 1, 0))
        self._step_back.setEnabled(steppable)
        self._step_forward.setEnabled(steppable)
        if steps > 1:
            self._step_label.setText(f"Step {self._step_index + 1}/{steps}")
        else:
            self._step_label.setText("")

    def _shift_step(self, delta: int) -> None:
        steps = int(getattr(self._latest_results, "n_steps", 1) or 1)
        if steps <= 1:
            return
        target = min(max(self._step_index + delta, 0), steps - 1)
        if target == self._step_index:
            return
        self._step_index = target
        self._refresh_step_buttons()
        self._apply_step()

    def _apply_step(self) -> None:
        """Re-draw the step-based layer at the current step, if one is showing."""
        apply = getattr(self, "_step_apply", None)
        if apply is not None:
            apply(self._step_index)

    def _on_show_force_diagram(self) -> None:
        if self._static_result() is None or self._vm.project is None:
            QMessageBox.information(
                self,
                "Force Diagram",
                "Run a Static analysis or a load combination first; force diagrams visualise "
                "its element-force output.",
            )
            return
        if self._is_envelope():
            self._log(
                "The force diagram draws both bounds of the combination: the maximum and the "
                "minimum diagram, labelled at their extreme values."
            )
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
            if self._static_result() is None:
                return
            data = self._diagram_data(component)
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
            data = self._diagram_data(component)
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
        static = self._static_result()
        if static is None or self._vm.project is None:
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
        if self._is_envelope():
            self._log(
                "Shell contours paint one value per face: they show the maximum bound of "
                "the combination."
            )
        view = ShellContourView(n_steps=static.n_steps)
        dock = QDockWidget("Shell Contours", self)
        dock.setWidget(view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.resize(700, 500)
        self._post_dock = dock

        def _render(field_key: str, step: int, scale: float, directions: bool) -> None:
            current = self._static_result()
            if current is None or self._vm.project is None:
                return
            self._contour_renderer.render(
                self._vm.project,
                current,
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
        best_data = self._diagram_data(ForceComponent.N)
        best_max = best_data.abs_max
        for comp in (
            ForceComponent.V2,
            ForceComponent.V3,
            ForceComponent.M2,
            ForceComponent.M3,
            ForceComponent.T,
        ):
            d = self._diagram_data(comp)
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
            with self._busy("Exporting animation…"):
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
        self._set_result_caption(None)
        self._tear_down_post_dock()
        if self._diagram_renderer is not None:
            self._diagram_renderer.clear()
        self._contour_renderer.clear()
        self._ratio_renderer.clear()
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
    def _leave_plane_view(self) -> None:
        """Turning the camera leaves a plan or elevation: back to full 3D snapping."""
        self._canvas.clear_working_plane()
        self._populate_level_combo(None)

    def _on_rotate_view(self, left_right: int, up_down: int) -> None:
        """View → Rotate: turn the camera one step (15°) about the model."""
        self._leave_plane_view()
        step = self._canvas.ROTATE_STEP_DEG
        self._canvas.orbit(azimuth=left_right * step, elevation=up_down * step)

    def _on_spin(self, on: bool) -> None:
        """View → Spin: turn the view continuously until switched off."""
        if on:
            self._leave_plane_view()
        self._canvas.set_spinning(on)

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
            if not cs.grid.shown or (cs.grid.is_cylindrical and plane != "XY"):
                # A cylindrical grid has levels (Z) but no X or Y lines.
                continue
            ords = cs.grid.visible_ordinates()[{"x_lines": 0, "y_lines": 1, "z_lines": 2}[attr]]
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
        self._sync_grid_actions()
        # Another project: its grid lines are not the ones being viewed.
        self._grid_view = None
        self._grid_view_window = None
        self._main_canvas.set_view_filter(None)
        # Another project has its own ids; do not carry this viewport's hidden
        # set into it.
        self._main_canvas.set_hidden(nodes=set(), elements=set())
        self._act_show_all_objects.setEnabled(False)
        # Results of another project (or of the closed one) never feed a combination.
        self._case_results.clear()
        self._report_extra.clear()
        self._set_result_caption(None)
        self._main_canvas.show_project(project)
        self._refresh_view_windows(project)
        if project is not None and project.ndm == 2:
            # A 2D model lives in the X-Z plane (core.plane): face on, drawing at y = 0.
            self._on_view_front()
        self._props.set_project(project)
        self._refresh_tree(project)
        self._refresh_status()
        self._sync_units_combo()
        self._refresh_action_enablement()

    def _on_model_mutated(self) -> None:
        # Same project, contents changed: re-render but DON'T reset camera.
        # We still clear and re-add actors, which loses selection — but the
        # selection state persists, so highlights re-apply.
        if self._grid_view is not None:
            # The line may have moved or gone: re-resolve it (this redraws).
            self._apply_grid_line_view()
        elif self._vm.project is not None:
            self._canvas._renderer.render(self._vm.project)
            self._canvas.render()
        self._sync_grid_actions()
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

    def _on_performance(self) -> None:
        """Help → Performance monitor: opt-in timings, memory and cProfile."""
        dialog = getattr(self, "_performance_dialog", None)
        if dialog is None:
            dialog = PerformanceDialog(self._vm, self)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.destroyed.connect(lambda _=None: setattr(self, "_performance_dialog", None))
            self._performance_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About OpenSees Studio",
            f"<h3>OpenSees Studio {__version__}</h3>"
            "<p>A modern desktop GUI for OpenSeesPy.</p>"
            "<p>GNU Affero General Public License v3.0 — see LICENSE.</p>",
        )

    def _log_solver_status(self) -> None:
        if self._solver.available:
            self._log(f"Solver: {self._solver.summary()}.")
        else:
            self._log(
                f"No solver: {self._solver.message} Modeling, export and reports work; "
                "running an analysis needs one (Options → Solver)."
            )

    def _on_solver_settings(self) -> None:
        """Options → Solver: where OpenSeesPy is installed."""
        dialog = SolverSettingsDialog(engines.load_settings(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        settings = dialog.settings()
        try:
            engines.save_settings(settings)
        except OSError as exc:
            QMessageBox.critical(self, "Solver", f"Could not save the setting: {exc}")
            return
        engines.activate(settings.package_dir)
        self._solver = engines.current_status(settings)
        self._opensees = engines.opensees_status(settings)
        self._log_solver_status()
        self._refresh_action_enablement()

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
        has_static = self._static_result() is not None
        has_modal = isinstance(self._latest_results, ModalResults)
        has_transient = isinstance(self._latest_results, TransientResults)
        has_pushover = isinstance(self._latest_results, PushoverResults)
        has_rs = isinstance(self._latest_results, ResponseSpectrumResults)
        n_sel = len(self._canvas.selection.nodes)
        self._act_save.setEnabled(has_project)
        self._act_save_as.setEnabled(has_project)
        self._act_import_dxf.setEnabled(has_project)
        self._act_export_script.setEnabled(has_project)
        self._act_export_ifc.setEnabled(has_project)
        self._act_export_s2k.setEnabled(has_project)
        self._act_export_report.setEnabled(has_project)
        self._act_grid.setEnabled(True)
        self._act_add_node.setEnabled(True)
        self._act_create_shell.setEnabled(has_project)
        self._act_frame_wizard.setEnabled(has_project)
        self._act_truss_wizard.setEnabled(has_project)
        self._act_check_duplicates.setEnabled(has_project)
        self._act_table_editing.setEnabled(has_project)
        has_cases = has_project and bool(self._vm.project and self._vm.project.analyses)
        # Without a solver the model is still built, exported and reported; only
        # what calls OpenSees waits for one (Options → Solver).
        solver = self._solver.available
        opensees = self._opensees.available
        self._act_run.setEnabled(solver)
        self._act_run.setStatusTip("" if solver else self._solver.summary())
        self._act_run_batch.setEnabled(solver)
        self._act_run_batch.setStatusTip("" if solver else self._solver.summary())
        # The Material Tester and the stability check call OpenSees itself,
        # whatever engine runs the cases.
        self._act_material_tester.setEnabled(opensees)
        self._act_material_tester.setStatusTip("" if opensees else self._opensees.summary())
        batch_enabled = has_cases and solver and not self._runner.is_running
        self._act_run_all.setEnabled(batch_enabled)
        self._act_run_selected.setEnabled(batch_enabled)
        project_now = self._vm.project
        stored = project_now is not None and (
            bool(self._case_results.current(project_now)) or bool(self._report_extra)
        )
        db_there = has_project and database_path(self._vm.path).exists()
        self._act_clear_results.setEnabled(bool(has_project and (stored or db_there)))
        self._act_steel_check.setEnabled(has_project)
        self._act_drift_check.setEnabled(has_project)
        self._act_steel_ratios.setEnabled(has_project)
        self._act_check_stability.setEnabled(
            has_project
            and opensees
            and not self._stability.is_running
            and not self._runner.is_running
        )
        self._act_cancel_stability.setEnabled(self._stability.is_running)
        self._act_check_model.setEnabled(has_project)
        self._act_mesh.setEnabled(has_project)
        self._act_delete_loads.setEnabled(has_project)
        self._act_merge_joints.setEnabled(has_project)
        self._act_divide_frames.setEnabled(has_project)
        self._act_assign_support.setEnabled(has_project and has_selected_nodes)
        self._act_add_multi_support.setEnabled(has_project and has_selected_nodes)
        self._act_assign_masses.setEnabled(has_project and has_selected_nodes)
        self._act_assign_springs.setEnabled(has_project and has_selected_nodes)
        self._act_assign_equal_dof.setEnabled(has_project and n_sel == 2)
        self._act_assign_diaphragm.setEnabled(has_project)
        self._act_assign_rigid_link.setEnabled(has_project and n_sel == 2)
        self._act_remove_constraints.setEnabled(has_project and has_selected_nodes)
        self._act_storeys.setEnabled(has_project)
        self._act_groups.setEnabled(has_project)
        self._act_section_cuts.setEnabled(has_project)
        self._act_custom_commands.setEnabled(has_project)
        self._act_assign_group.setEnabled(has_project and has_selection)
        self._act_mass_source.setEnabled(has_project)
        self._act_seismic_loads.setEnabled(has_project)
        self._act_assign_load.setEnabled(has_project and has_selected_nodes)
        self._act_assign_imposed_displacement.setEnabled(has_project and has_selected_nodes)
        self._act_assign_surface_load.setEnabled(has_project)
        self._act_assign_floor_load.setEnabled(
            has_project
            and has_selected_nodes
            and self._vm.project is not None
            and self._vm.project.ndm == 3
        )
        # Zero-length section needs exactly two selected joints.
        self._act_assign_zls.setEnabled(has_project and n_sel == 2)
        self._act_assign_bearing.setEnabled(has_project and n_sel == 2)
        self._act_assign_link.setEnabled(has_project and n_sel == 2)
        self._act_assign_distributed_load.setEnabled(has_project and has_selected_elements)
        self._act_assign_frame_point_load.setEnabled(has_project and has_selected_elements)
        self._act_assign_hinge.setEnabled(has_project and has_selected_elements)
        self._act_assign_geom_transf.setEnabled(has_project and has_selected_elements)
        self._act_assign_integration.setEnabled(has_project and has_selected_elements)
        for action in (
            self._act_assign_releases,
            self._act_assign_end_offsets,
            self._act_assign_insertion,
            self._act_assign_modifiers,
            self._act_assign_trapezoidal_load,
            self._act_assign_temperature_load,
            self._act_assign_wall,
        ):
            action.setEnabled(has_project and has_selected_elements)
        self._act_delete.setEnabled(has_project and has_selection)
        self._act_hide_selected.setEnabled(has_project and has_selection)
        self._act_isolate_selected.setEnabled(has_project and has_selection)
        self._act_invert_visible.setEnabled(has_project)
        self._act_move.setEnabled(has_project and has_selection)
        self._act_replicate.setEnabled(has_project and has_selection)
        self._act_mirror.setEnabled(has_project and has_selection)
        self._act_tool_draw_frame.setEnabled(has_project)
        self._act_tool_draw_node.setEnabled(has_project)
        self._act_tool_draw_truss.setEnabled(has_project)
        self._act_select_results.setEnabled(has_project)
        self._act_load_combinations.setEnabled(True)
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
        self._act_influence_line.setEnabled(isinstance(self._latest_results, InfluenceLineResults))
        self._act_show_response_spectrum.setEnabled(has_rs)
        self._act_display_options.setEnabled(has_project)
        self._act_back_to_model.setEnabled(self._post_dock is not None)
        # Startup gate: with no project open only File and Help stay usable. The
        # whole menu is disabled rather than every action inside it, so it cannot
        # open onto a wall of grey entries.
        for role in (
            "edit",
            "select",
            "define",
            "assign",
            "analyze",
            "display",
            "view",
            "options",
        ):
            menu = self._menus.get(role)
            if menu is not None:
                menu.setEnabled(has_project)
        self._sync_visibility_actions()
        self._sync_show_all_action()

    # ── busy cursor ─────────────────────────────────────────────────
    def _begin_busy(self, message: str = "") -> None:
        """Show the wait cursor; nested calls are counted, not stacked."""
        if self._busy_depth == 0:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._busy_depth += 1
        if message:
            self.statusBar().showMessage(message)

    def _end_busy(self) -> None:
        """Drop one busy level; the cursor returns when the last one goes."""
        if self._busy_depth == 0:
            return
        self._busy_depth -= 1
        if self._busy_depth == 0:
            QApplication.restoreOverrideCursor()

    @contextlib.contextmanager
    def _busy(self, message: str = "") -> Iterator[None]:
        """Wait cursor for a synchronous operation, restored even on error."""
        self._begin_busy(message)
        try:
            yield
        finally:
            self._end_busy()

    def _on_runner_running_changed(self, running: bool) -> None:
        """Wait cursor while the solver runs; the environment stays responsive."""
        if running:
            self._begin_busy("Running analysis…")
        else:
            self._end_busy()
        self._refresh_action_enablement()

    def _on_stability_running_changed(self, running: bool) -> None:
        """Wait cursor while the stability check runs."""
        if running:
            self._begin_busy("Checking model stability…")
        else:
            self._end_busy()
        self._refresh_action_enablement()

    def _log(self, message: str) -> None:
        self._console.appendPlainText(message)
        self.statusBar().showMessage(message, 5000)
