"""Where every command sits in the ribbon: tab → group → command.

The tabs follow the order a model is built, SAP2000 style::

    Home · Define · Draw · Select · Assign · Loads · Analyze · Results · Design · View · Help

An entry names its action by the ``MainWindow`` attribute (``"_act_run"``), so a
renamed menu label never moves a button. ``"*"`` in front marks the group's
large button. ``"menu:File/Import"`` puts a whole submenu in one drop-down
button (dynamic lists: recent files, sections, languages…).

``tests/gui/test_ribbon.py`` checks that every menu command appears here exactly
once; a new menu command that is not added lands in an **Other** group and fails
that test.
"""

from __future__ import annotations

#: (tab id, tab label, ((group title, (entries…)), …))
RIBBON_LAYOUT: tuple[tuple[str, str, tuple[tuple[str, tuple[str, ...]], ...]], ...] = (
    (
        "home",
        "Home",
        (
            (
                "File",
                (
                    "*_act_new_model",
                    "*_act_open",
                    "*_act_save",
                    "_act_save_as",
                    "menu:File/Open Recent",
                    "_act_project_info",
                ),
            ),
            ("New", ("_act_new", "_act_new_2d", "_act_new_2d_truss")),
            ("Edit", ("*_act_undo", "*_act_redo", "_act_copy", "_act_paste", "_act_delete")),
            ("Interchange", ("menu:File/Import", "menu:File/Export", "_act_run_batch")),
            (
                "Session",
                (
                    "_act_set_units",
                    "_act_solver_settings",
                    "_act_lock_model",
                    "_act_use_ribbon",
                    "_act_dark_mode",
                    "menu:Options/Language",
                    "menu:Options/Autosave Recovery Copy",
                    "menu:Options/Keyboard Shortcuts",
                    "_act_quit",
                ),
            ),
        ),
    ),
    (
        "define",
        "Define",
        (
            ("Grid", ("*_act_grid", "_act_grid_wizard", "_act_storeys")),
            (
                "Materials",
                (
                    "*_act_material_library",
                    "_act_default_materials",
                    "_act_mc2010",
                    "_act_friction_library",
                    "_act_material_tester",
                ),
            ),
            (
                "Sections",
                (
                    "*_act_section_library",
                    "_act_concrete_section",
                    "_act_steel_deck",
                    "_act_section_designer",
                ),
            ),
            (
                "Load Patterns",
                (
                    "*_act_add_plain_pattern",
                    "menu:Define/Time Series",
                    "_act_ground_motions",
                    "_act_add_uniform_excitation",
                    "_act_add_multi_support",
                    "_act_seismic_loads",
                ),
            ),
            ("Cases", ("*_act_case_manager", "_act_load_combinations", "_act_mass_source")),
            (
                "Model Data",
                (
                    "_act_groups",
                    "_act_joint_patterns",
                    "_act_section_cuts",
                    "_act_custom_commands",
                ),
            ),
        ),
    ),
    (
        "draw",
        "Draw",
        (
            (
                "Draw",
                (
                    "*_act_tool_select",
                    "*_act_tool_draw_frame",
                    "_act_tool_quick_frame",
                    "_act_tool_draw_node",
                    "_act_tool_draw_truss",
                    "*_act_tool_draw_shell",
                    "_act_tool_quick_shell",
                    "_act_tool_measure",
                ),
            ),
            (
                "Create",
                ("_act_add_node", "_act_create_shell", "_act_frame_wizard", "_act_truss_wizard"),
            ),
            (
                "Edit Geometry",
                (
                    "_act_move",
                    "_act_replicate",
                    "_act_mirror",
                    "_act_extrude",
                    "_act_merge_joints",
                    "_act_divide_frames",
                    "_act_join_frames",
                    "_act_mesh",
                ),
            ),
            ("Tables", ("_act_table_editing", "_act_check_duplicates")),
        ),
    ),
    (
        "select",
        "Select",
        (
            (
                "Select",
                (
                    "*_act_select_all",
                    "_act_clear_selection",
                    "_act_invert_selection",
                    "_act_previous_selection",
                    "_act_select_line",
                ),
            ),
            (
                "By Property",
                (
                    "menu:Select/By Element Type",
                    "menu:Select/By Section",
                    "menu:Select/By Material",
                    "menu:Select/By Load Pattern",
                    "menu:Select/By Group",
                ),
            ),
            (
                "Joints",
                (
                    "_act_select_all_joints",
                    "_act_select_supports",
                    "_act_select_joints_with_mass",
                    "_act_select_loose_joints",
                    "_act_select_joints_in_bars",
                    "_act_select_shell_edge_joints",
                    "_act_select_joints_of_elements",
                ),
            ),
            (
                "Elements",
                (
                    "_act_select_all_elements",
                    "_act_select_weighted",
                    "_act_select_elements_within_joints",
                ),
            ),
        ),
    ),
    (
        "assign",
        "Assign",
        (
            (
                "Joint",
                (
                    "*_act_assign_support",
                    "menu:Assign/Joint/Quick Restraint",
                    "_act_assign_masses",
                    "_act_assign_springs",
                ),
            ),
            (
                "Constraints",
                (
                    "_act_assign_diaphragm",
                    "_act_assign_equal_dof",
                    "_act_assign_rigid_link",
                    "_act_remove_constraints",
                ),
            ),
            (
                "Joint Elements",
                (
                    "_act_assign_zero_length",
                    "_act_assign_zls",
                    "_act_assign_bearing",
                    "_act_assign_link",
                    "_act_assign_joint_pattern",
                ),
            ),
            (
                "Frame",
                (
                    "*_act_assign_section",
                    "_act_assign_material",
                    "_act_assign_releases",
                    "_act_assign_local_axes",
                    "_act_assign_geom_transf",
                    "_act_assign_integration",
                    "_act_assign_end_offsets",
                    "_act_assign_insertion",
                    "_act_assign_modifiers",
                    "_act_assign_auto_mesh",
                ),
            ),
            (
                "Nonlinear",
                (
                    "_act_assign_hinge",
                    "_act_assign_wall",
                    "_act_assign_line_springs",
                    "_act_assign_pile",
                ),
            ),
            (
                "Area",
                (
                    "_act_shell_formulation",
                    "_act_assign_area_springs",
                    "_act_assign_edge_springs",
                ),
            ),
            ("Groups", ("_act_assign_group",)),
        ),
    ),
    (
        "loads",
        "Loads",
        (
            ("Joint", ("*_act_assign_load", "_act_assign_imposed_displacement")),
            (
                "Frame",
                (
                    "*_act_assign_distributed_load",
                    "_act_assign_frame_point_load",
                    "_act_assign_trapezoidal_load",
                    "_act_assign_temperature_load",
                    "_act_assign_tendon",
                ),
            ),
            ("Area", ("_act_assign_surface_load", "_act_assign_floor_load")),
            ("Review", ("_act_show_load_assigns", "_act_delete_loads")),
        ),
    ),
    (
        "analyze",
        "Analyze",
        (
            ("Check", ("_act_check_model", "_act_check_stability", "_act_cancel_stability")),
            (
                "Run",
                (
                    "*_act_run",
                    "_act_run_all",
                    "_act_run_selected",
                    "_act_clear_results",
                    "_act_auto_mesh_frames",
                ),
            ),
        ),
    ),
    (
        "results",
        "Results",
        (
            (
                "Shape",
                (
                    "*_act_show_deformed",
                    "_act_show_mode_shape",
                    "_act_select_results",
                    "_act_back_to_model",
                ),
            ),
            (
                "Forces",
                (
                    "*_act_show_force_diagram",
                    "_act_shell_contours",
                    "_act_show_reactions",
                    "_act_reactions_table",
                    "_act_reactions_dialog",
                ),
            ),
            (
                "Plots",
                (
                    "_act_show_time_history",
                    "_act_show_hysteresis",
                    "_act_show_pushover",
                    "_act_show_response_spectrum",
                    "_act_influence_line",
                    "_act_export_th_animation",
                ),
            ),
            ("Options", ("_act_display_options",)),
        ),
    ),
    (
        "design",
        "Design",
        (
            (
                "Steel",
                (
                    "*_act_design_basis",
                    "_act_direct_analysis",
                    "_act_notional_loads",
                    "_act_member_classification",
                    "_act_built_up",
                ),
            ),
            ("Steel Check", ("*_act_steel_check", "_act_steel_ratios", "_act_drift_check")),
            (
                "Connections",
                (
                    "_act_joint_connections",
                    "menu:Design/Steel Connections",
                    "menu:Design/Connection Calculators",
                ),
            ),
            ("Concrete", ("*_act_concrete_check", "_act_footings", "_act_footing_pressures")),
        ),
    ),
    (
        "view",
        "View",
        (
            (
                "Zoom",
                ("*_act_zoom_extents", "_act_zoom_in", "_act_zoom_out", "_act_zoom_window"),
            ),
            (
                "Views",
                (
                    "_act_view_iso",
                    "_act_view_top",
                    "_act_view_front",
                    "_act_view_right",
                    "_act_level_up",
                    "_act_level_down",
                    "_act_grid_line_view",
                ),
            ),
            ("Camera", ("menu:View/Rotate", "_act_toggle_parallel")),
            (
                "Display",
                (
                    "menu:View/Color By",
                    "menu:View/Visibility",
                    "_act_show_extruded",
                    "_act_show_local_axes",
                    "_act_show_grids",
                    "_act_show_grid_labels",
                    "_act_view_colors",
                ),
            ),
            (
                "Objects",
                (
                    "_act_hide_selected",
                    "_act_isolate_selected",
                    "_act_invert_visible",
                    "_act_show_all_objects",
                ),
            ),
            (
                "Windows",
                (
                    "_act_new_view",
                    "_act_close_view",
                    "menu:View/Panels",
                    "_act_reset_layout",
                ),
            ),
        ),
    ),
    (
        "help",
        "Help",
        (
            (
                "Help",
                ("*_act_help_contents", "_act_shortcuts", "_act_performance", "_act_about"),
            ),
        ),
    ),
)
