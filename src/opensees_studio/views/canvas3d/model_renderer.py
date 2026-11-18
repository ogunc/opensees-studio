"""Project → PyVista renderer (high-performance, single-actor strategy).

- Nodes:    one ``pv.PolyData`` of N points + sphere glyph filter → one actor
- Frames:   one ``pv.PolyData`` of N line cells → one actor
- Selection: per-cell scalar (0=normal, 1=selected) + 2-color LUT;
  toggling rewrites the scalar array — no actor rebuild.

Mode-aware: MODEL / DEFORMED / MODAL change only the points array.
"""

from __future__ import annotations

import contextlib
import enum
from collections.abc import Callable
from typing import Any, ClassVar

import numpy as np
import pyvista as pv

from opensees_studio.core import (
    BEARING_CLASSES,
    BeamWithHingesElement,
    CorotTrussElement,
    DispBeamColumn,
    ElasticBeamColumn,
    ForceBeamColumn,
    FrameMember,
    MVLEMElement,
    NodalLoad,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    QuadElement,
    ShellMITC4Element,
    TrapezoidalElementLoad,
    TrussElement,
    UniformElementLoad,
    ZeroLengthElement,
)
from opensees_studio.core.area_loads import AreaLoadError, pattern_distributed_loads
from opensees_studio.core.color_by import Categories, element_categories
from opensees_studio.core.diaphragms import constrained_node_ids
from opensees_studio.core.frame_members import member_layout
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.plane import dof_indices as plane_dof_indices
from opensees_studio.core.reactions import (
    ReactionRow,
    largest_force,
    largest_moment,
)
from opensees_studio.core.view_settings import ViewSettings
from opensees_studio.diagnostics.performance import perf
from opensees_studio.services.deformation import DeformationSource
from opensees_studio.views.canvas3d.style import RenderStyle


class RendererMode(enum.Enum):
    MODEL = "model"
    DEFORMED = "deformed"
    MODAL = "modal"


#: Colours of the origin reference: the usual X red, Y green, Z blue.
_TRIAD_COLORS: tuple[str, str, str] = ("#d0402f", "#2f9e4f", "#2f5fcf")

#: Arrow length as a fraction of the model's extent, so it reads at any zoom.
_TRIAD_LENGTH_FRACTION = 0.08

#: Elements drawn as surfaces (a filled face) rather than as lines.
#: The Color By legend lists at most this many categories.
LEGEND_MAX_ENTRIES = 15

_SURFACE_CLASSES = (
    QuadElement,
    ShellMITC4Element,
)


_FRAME_CLASSES = (
    ElasticBeamColumn,
    DispBeamColumn,
    ForceBeamColumn,
    BeamWithHingesElement,
    TrussElement,
    CorotTrussElement,
    ZeroLengthElement,
    MVLEMElement,
    *BEARING_CLASSES,
)


def _classify_support(restraint: tuple[bool, ...], dof_idx: tuple[int, ...]) -> str:
    flags = [restraint[i] for i in dof_idx]
    if all(flags):
        return "fix"
    trans_flags = [flags[k] for k, idx in enumerate(dof_idx) if idx < 3]
    rot_flags = [flags[k] for k, idx in enumerate(dof_idx) if idx >= 3]
    if trans_flags and all(trans_flags) and not any(rot_flags):
        return "pin"
    if sum(flags) == 1:
        return "roller"
    return "custom"


def _dof_indices(ndm: int, ndf: int) -> tuple[int, ...]:
    """Restraint slots a model uses (core.plane); every slot for an unknown layout."""
    try:
        return plane_dof_indices(ndm, ndf)
    except ValueError:
        return tuple(range(ndf))


class ModelRenderer:
    """Glyphed-PolyData renderer with mode-aware deformation support."""

    @staticmethod
    def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
        r, g, b = (round(x * 255) for x in rgb)
        return f"#{r:02x}{g:02x}{b:02x}"

    _NODE_LUT: ClassVar[list[str]] = ["#d9d9d9", "#00ffff"]  # gray normal, cyan selected
    _FRAME_LUT: ClassVar[list[str]] = ["#338cd9", "#00ffff"]  # blue normal, cyan selected
    _SURFACE_LUT: ClassVar[list[str]] = ["#a8b6c4", "#00ffff"]  # steel grey, cyan selected

    def __init__(
        self,
        plotter: Any,
        style: RenderStyle | None = None,
        settings: ViewSettings | None = None,
    ) -> None:
        self._plotter = plotter
        self._style = style or RenderStyle()
        #: Visibility/colour settings of the viewport that owns this renderer.
        self._settings = settings or ViewSettings()
        #: Ids the user hid in this viewport (View → Hide Selected / Invert).
        self._hidden_nodes: set[int] = set()
        self._hidden_elements: set[int] = set()
        self._project: Project | None = None
        #: The project as given, before :attr:`_view_filter` (View → Grid Line View).
        self._source_project: Project | None = None
        #: Reactions of the case on screen, drawn when ``show_reactions`` is on.
        self._reactions: list[ReactionRow] = []
        self._show_reactions = False
        self._view_filter: Callable[[Project], Project] | None = None
        self._mode = RendererMode.MODEL
        self._deformation: DeformationSource | None = None

        self._node_pd: pv.PolyData | None = None
        self._node_actor: Any = None
        self._node_ids_ordered: list[int] = []
        self._node_id_to_row: dict[int, int] = {}
        self._node_original_points: np.ndarray | None = None
        self._node_point_size: float = 0.0

        self._frame_pd: pv.PolyData | None = None
        self._frame_actor: Any = None
        self._frame_ids_ordered: list[int] = []
        self._frame_id_to_row: dict[int, int] = {}

        self._triad_actors: list[Any] = []
        self._surface_pd: pv.PolyData | None = None
        self._surface_actor: Any = None
        self._surface_ids_ordered: list[int] = []
        self._surface_id_to_row: dict[int, int] = {}
        self._node_label_actor: Any = None
        self._element_label_actor: Any = None

        self._aux_actors: list[Any] = []
        #: Overlays whose world size is derived from the camera (supports, loads,
        #: reactions, masses). They are rebuilt, not the whole scene, when the
        #: viewport settles after a zoom.
        self._screen_actors: list[Any] = []
        self._screen_key: tuple[float, ...] | None = None
        self._hover_actor: Any = None  # single yellow-ring snap marker
        # SAP2000-style working plane: when set, the grid renders ONLY
        # the lines / intersections lying on this plane so a user in
        # plan view at Z=3 doesn't see the Z=0 grid cluttering the view.
        self._working_plane: tuple[str, float] | None = None

        with contextlib.suppress(Exception):
            self._plotter.enable_anti_aliasing("ssaa")

    # ── public API ───────────────────────────────────────────────────
    def render(self, project: Project | None) -> None:
        """Full render: rebuild everything. Call when topology changes."""
        if perf.enabled:
            with perf.span("render.build"):
                self._render(project)
        else:
            self._render(project)

    def _timed_build(
        self, label: str, builder: Callable[[Project], None], project: Project
    ) -> None:
        if perf.enabled:
            with perf.span(f"render.{label}"):
                builder(project)
        else:
            builder(project)

    def _render(self, project: Project | None) -> None:
        self._source_project = project
        if project is not None and self._view_filter is not None:
            project = self._view_filter(project)
        self._project = project
        self._teardown_all()
        if project is None:
            perf.gauge("render.nodes", 0)
            perf.gauge("render.elements", 0)
            return
        perf.gauge("render.nodes", len(project.nodes))
        perf.gauge("render.elements", len(project.elements))
        # Grid renders even when there are no nodes yet - so the user sees
        # the grid before they place any geometry.
        if self._settings.show_grids:
            self._timed_build("grid", self._build_grid, project)
        self._timed_build("origin_triad", self._build_origin_triad, project)
        if not project.nodes:
            return
        if self._settings.show_nodes:
            self._timed_build("nodes", self._build_node_polydata, project)
        if self._settings.show_frames:
            self._timed_build("frames", self._build_frame_polydata, project)
        if self._settings.show_surfaces:
            self._timed_build("surfaces", self._build_surface_polydata, project)
        self._timed_build("color_legend", self._build_color_legend, project)
        if self._settings.show_supports:
            self._timed_build("supports", self._build_supports, project)
        if self._settings.show_constraints:
            self._timed_build("constraints", self._build_constraints, project)
        if self._settings.show_frame_assignments:
            self._timed_build("frame_assignments", self._build_frame_assignments, project)
        if self._settings.show_releases:
            self._timed_build("releases", self._build_releases, project)
        if self._settings.show_loads:
            self._timed_build("loads", self._build_loads, project)
            self._timed_build("reactions", self._build_reactions, project)
        if self._settings.show_masses:
            self._timed_build("masses", self._build_masses, project)
        if self._settings.show_extruded:
            self._timed_build("extrusions", self._build_section_extrusions, project)
        if perf.enabled:
            with perf.span("render.apply_mode"):
                self._apply_mode_to_points()
            with perf.span("render.labels"):
                self._rebuild_labels()
        else:
            self._apply_mode_to_points()
            self._rebuild_labels()
        actors = getattr(self._plotter, "actors", None)
        if actors is not None:
            with contextlib.suppress(Exception):
                perf.gauge("render.actors", len(actors))
        mesh_calls = getattr(self._plotter, "meshes", None)
        if isinstance(mesh_calls, int):
            perf.gauge("render.mesh_calls", mesh_calls)
        self._screen_key = self._screen_size_key()

    def set_view_filter(self, view_filter: Callable[[Project], Project] | None) -> None:
        """Draw only what ``view_filter(project)`` keeps (None: everything); re-renders."""
        self._view_filter = view_filter
        if self._source_project is not None:
            self.render(self._source_project)

    def set_display_options(self, *, show_node_labels: bool, show_element_labels: bool) -> None:
        """Toggle viewport labels (kept for the Display Options dialog)."""
        self.set_settings(
            self._settings.with_changes(
                show_node_labels=show_node_labels,
                show_element_labels=show_element_labels,
            )
        )

    def set_show_section_extrusions(self, on: bool) -> None:
        """Toggle the SAP2000-style "Show Extruded View" overlay."""
        self.set_settings(self._settings.with_changes(show_extruded=on))

    @property
    def settings(self) -> ViewSettings:
        """The visibility/colour settings this renderer draws with."""
        return self._settings

    def set_settings(self, settings: ViewSettings) -> None:
        """Adopt ``settings`` and redraw (no-op when the instance is unchanged)."""
        if settings is self._settings:
            return
        self._settings = settings
        if self._source_project is not None:
            self.render(self._source_project)

    def set_hidden(self, nodes: set[int], elements: set[int]) -> None:
        """Hide these ids in this viewport and redraw.

        Hiding is a per-viewport concern: it never touches the project, so the
        model tree, the other viewports and the analysis are unaffected.
        """
        if nodes == self._hidden_nodes and elements == self._hidden_elements:
            return
        self._hidden_nodes = set(nodes)
        self._hidden_elements = set(elements)
        if self._source_project is not None:
            self.render(self._source_project)

    @property
    def hidden(self) -> tuple[frozenset[int], frozenset[int]]:
        """``(nodes, elements)`` hidden in this viewport."""
        return frozenset(self._hidden_nodes), frozenset(self._hidden_elements)

    def set_working_plane(self, plane: tuple[str, float] | None) -> None:
        """Update the working-plane filter and rebuild the grid overlay.

        Passing ``None`` restores full-3D rendering (all grid lines on
        every Z / Y / X). Passing ``("XY", 3.0)`` restricts the grid
        overlay (and its intersection dots) to the Z=3 plane. Node and
        element actors are NOT filtered — they stay visible so the user
        still sees the whole model, just with a clean grid backdrop.
        """
        if self._working_plane == plane:
            return
        self._working_plane = plane
        if self._project is not None:
            self.render(self._source_project)

    def update_selection(self, node_ids: frozenset[int], element_ids: frozenset[int]) -> None:
        """In-place selection update — no full re-render."""
        if self._node_pd is not None and self._node_ids_ordered:
            states = np.zeros(len(self._node_ids_ordered), dtype=np.int8)
            for nid in node_ids:
                row = self._node_id_to_row.get(nid)
                if row is not None:
                    states[row] = 1
            self._node_pd["_oss_state"] = states
            self._apply_node_states(states)

        if self._frame_pd is not None and self._frame_ids_ordered:
            # Each cell keeps its Color By category; a selected one takes the
            # last entry of the colour table.
            frame_states = self._frame_base.copy()
            for eid in element_ids:
                row = self._frame_id_to_row.get(eid)
                if row is not None:
                    frame_states[row] = self._frame_selected
            self._frame_pd.cell_data["_oss_state"] = frame_states
            self._frame_pd.Modified()

        if self._surface_pd is not None and self._surface_ids_ordered:
            surface_states = self._surface_base.copy()
            for eid in element_ids:
                row = self._surface_id_to_row.get(eid)
                if row is not None:
                    surface_states[row] = self._surface_selected
            self._surface_pd.cell_data["_oss_state"] = surface_states
            self._surface_pd.Modified()

    def set_mode(self, mode: RendererMode, deformation: DeformationSource | None = None) -> None:
        self._mode = mode
        self._deformation = deformation
        self._apply_mode_to_points()

    def set_hover_snap(self, world_point: tuple[float, float, float] | None) -> None:
        """Show / hide the yellow snap-target indicator.

        Passing ``None`` removes the marker. Passing a world point
        renders (or repositions) a single yellow sphere at that point —
        the visual cue telling the user where a click would land.
        """
        # Remove any previous marker.
        if self._hover_actor is not None:
            with contextlib.suppress(Exception):
                self._plotter.remove_actor(self._hover_actor, render=False)
            self._hover_actor = None

        if world_point is None:
            return

        radius = 0.5 * self._screen_size(self._settings.node_size_percent * 1.6, minimum=1e-9)
        sphere = pv.Sphere(
            center=tuple(float(v) for v in world_point),
            radius=radius,
            theta_resolution=16,
            phi_resolution=16,
        )
        self._hover_actor = self._plotter.add_mesh(
            sphere,
            color=(1.0, 0.85, 0.0),  # amber-yellow
            opacity=0.85,
            pickable=False,
            lighting=False,
        )

    # ── builders ────────────────────────────────────────────────────
    def _viewport_height_px(self) -> float:
        """Height of the render target in device pixels.

        VTK point/glyph sizes and the camera conversion both use physical
        pixels, so this is the height of the render window, not the Qt logical
        widget (they differ at 125-200 % scaling).
        """
        try:
            size = self._plotter.window_size
            if isinstance(size, (tuple, list)) and len(size) == 2 and float(size[1]) > 0:
                return float(size[1])
        except Exception:
            # Recording plotters have no render window; try the next source.
            pass
        try:
            width_height = self._plotter.render_window.GetSize()
            if len(width_height) == 2 and float(width_height[1]) > 0:
                return float(width_height[1])
        except Exception:
            # A viewport can exist before VTK has created its render window.
            pass
        return 800.0

    def _world_per_pixel(self) -> float:
        """World units covered by one device pixel at the camera target.

        Parallel projection is exact. Perspective uses the distance to the focal
        point, which is the right approximation for a structural model: markers
        behind or in front of it change by a few percent, not by the whole
        zoom range.
        """
        height = max(self._viewport_height_px(), 1.0)
        try:
            camera = self._plotter.camera
            if bool(camera.GetParallelProjection()):
                return max(2.0 * float(camera.GetParallelScale()) / height, 1e-12)
            position = np.asarray(camera.GetPosition(), dtype=float)
            focal = np.asarray(camera.GetFocalPoint(), dtype=float)
            distance = float(np.linalg.norm(position - focal))
            angle = np.radians(float(camera.GetViewAngle()))
            tangent = float(np.tan(angle / 2.0))
            return max(2.0 * distance * tangent / height, 1e-12)
        except Exception:
            # Recording plotters and a viewport before its camera exists.
            if self._node_original_points is not None and len(self._node_original_points):
                diagonal = float(self._diag_of_points(self._node_original_points))
                return max(diagonal / height, 1e-12)
            return 1.0 / height

    def _screen_size(self, percent: float, minimum: float = 1e-12) -> float:
        """World size of ``percent`` of the viewport height."""
        return max(percent / 100.0 * self._viewport_height_px() * self._world_per_pixel(), minimum)

    def _screen_node_point_size(self) -> float:
        """Node diameter in device pixels (a VTK point size is screen-space)."""
        return max(2.0, self._settings.node_size_percent / 100.0 * self._viewport_height_px())

    def _screen_size_key(self) -> tuple[float, ...]:
        """Everything that changes the world size of a screen-relative overlay."""
        return (
            round(self._world_per_pixel(), 12),
            round(self._viewport_height_px(), 3),
            self._settings.support_size_percent,
            self._settings.load_size_percent,
            self._settings.reaction_size_percent,
            self._settings.mass_size_percent,
        )

    def _add_screen_actor(self, actor: Any) -> None:
        self._aux_actors.append(actor)
        self._screen_actors.append(actor)

    def _screen_key_changed(self, key: tuple[float, ...]) -> bool:
        """True when the camera moved enough to be worth rebuilding glyphs.

        A 2 % change in the world-per-pixel value is below the visual threshold
        for an arrow or support, and avoiding those rebuilds keeps a wheel zoom
        responsive on models with thousands of loads. The height/settings tail
        of the key is compared exactly.
        """
        old = self._screen_key
        if old is None:
            return True
        if old[1:] != key[1:]:
            return True
        scale = max(abs(old[0]), abs(key[0]), 1e-12)
        return abs(key[0] - old[0]) / scale > 0.02

    def refresh_screen_sizes(self) -> bool:
        """Rebuild only the overlays whose size depends on the camera.

        Called after the viewport settles from a zoom, pan or resize. The node
        cloud is just one property write; supports, load arrows, reactions and
        mass markers need their glyph geometry rebuilt, and only those actors
        are touched. Returns True when the scene changed and needs a draw.
        """
        if self._project is None or self._node_pd is None:
            return False
        self._refresh_node_point_size()
        key = self._screen_size_key()
        if not self._screen_key_changed(key):
            return False
        self._screen_key = key
        for actor in self._screen_actors:
            with contextlib.suppress(Exception):
                self._plotter.remove_actor(actor, render=False)
            with contextlib.suppress(ValueError):
                self._aux_actors.remove(actor)
        self._screen_actors.clear()
        if self._settings.show_supports:
            self._build_supports(self._project)
        if self._settings.show_loads:
            self._build_loads(self._project)
            self._build_reactions(self._project)
        if self._settings.show_masses:
            self._build_masses(self._project)
        return True

    def _build_node_polydata(self, project: Project) -> None:
        visible = [n for n in project.nodes if n.id not in self._hidden_nodes]
        ids = [n.id for n in visible]
        coords = np.array([n.coords for n in visible], dtype=float)
        self._node_ids_ordered = ids
        self._node_id_to_row = {nid: i for i, nid in enumerate(ids)}
        self._node_original_points = coords.copy()

        pd = pv.PolyData(coords)
        pd["_oss_id"] = np.array(ids, dtype=np.int64)
        pd["_oss_kind"] = np.array(["node"] * len(ids), dtype=object)
        pd["_oss_state"] = np.zeros(len(ids), dtype=np.int8)
        self._node_pd = pd
        self._node_point_size = self._screen_node_point_size()
        # One point per joint, drawn as a screen-space sphere. Unlike a glyph
        # of a sphere template this costs no per-node geometry, and zooming only
        # changes one actor property: the joint stays the same size on screen.
        self._node_actor = self._plotter.add_mesh(
            pd,
            scalars="_oss_state",
            cmap=self._settings.node_lut,
            clim=[0, 1],
            show_scalar_bar=False,
            pickable=True,
            lighting=False,
            point_size=self._node_point_size,
            render_points_as_spheres=True,
        )

    def _apply_node_states(self, states: np.ndarray) -> None:
        """Recolour the point cloud in place: selecting never rebuilds the actor."""
        if self._node_pd is None:
            return
        self._node_pd["_oss_state"] = states
        self._node_pd.Modified()

    def _refresh_node_point_size(self) -> None:
        """Keep the node marker at ``node_size_percent`` of the viewport height."""
        self._node_point_size = self._screen_node_point_size()
        actor = self._node_actor
        if actor is not None:
            with contextlib.suppress(Exception):
                actor.GetProperty().SetPointSize(self._node_point_size)
        if self._node_pd is not None:
            self._node_pd.Modified()

    def _build_frame_polydata(self, project: Project) -> None:
        frames = [
            el
            for el in project.elements
            if isinstance(el, _FRAME_CLASSES) and el.id not in self._hidden_elements
        ]
        if not frames or self._node_original_points is None:
            return
        cells: list[int] = []
        ids: list[int] = []
        for el in frames:
            try:
                i = self._node_id_to_row[el.nodes[0]]
                j = self._node_id_to_row[el.nodes[1]]
            except KeyError:
                continue
            cells.extend([2, i, j])
            ids.append(el.id)
        if not ids:
            return
        pd = pv.PolyData()
        pd.points = self._node_original_points.copy()
        pd.lines = np.array(cells, dtype=np.int64)
        pd.cell_data["_oss_id"] = np.array(ids, dtype=np.int64)
        pd.cell_data["_oss_kind"] = np.array(["element"] * len(ids), dtype=object)
        categories = self._categories(project, self._settings.frame_color)
        base = np.array([categories.index.get(eid, 0) for eid in ids], dtype=np.int32)
        pd.cell_data["_oss_state"] = base.copy()

        self._frame_pd = pd
        self._frame_ids_ordered = ids
        self._frame_id_to_row = {eid: i for i, eid in enumerate(ids)}
        self._frame_base = base
        self._frame_selected = len(categories.colors)
        self._frame_actor = self._plotter.add_mesh(
            pd,
            scalars="_oss_state",
            cmap=[*categories.colors, self._settings.selected_color],
            clim=[0, len(categories.colors)],
            show_scalar_bar=False,
            line_width=3.0,
            pickable=True,
            lighting=False,
        )

    def _build_surface_polydata(self, project: Project) -> None:
        """Faces for the surface elements (quads and shells).

        Same contract as the frame path: one PolyData with a cell per element,
        carrying ``_oss_id``/``_oss_kind``/``_oss_state`` so picking and
        selection work the same way, and points shared with the node cloud so
        a deformed shape moves the faces with it.
        """
        surfaces = [
            el
            for el in project.elements
            if isinstance(el, _SURFACE_CLASSES) and el.id not in self._hidden_elements
        ]
        if not surfaces or self._node_original_points is None:
            return
        cells: list[int] = []
        ids: list[int] = []
        for el in surfaces:
            try:
                rows = [self._node_id_to_row[nid] for nid in el.nodes[:4]]
            except KeyError:
                continue
            if len(rows) != 4:
                continue
            cells.extend([4, *rows])  # a quad cell: size then the four corners
            ids.append(el.id)
        if not ids:
            return
        pd = pv.PolyData()
        pd.points = self._node_original_points.copy()
        pd.faces = np.array(cells, dtype=np.int64)
        pd.cell_data["_oss_id"] = np.array(ids, dtype=np.int64)
        pd.cell_data["_oss_kind"] = np.array(["element"] * len(ids), dtype=object)
        categories = self._categories(project, self._settings.surface_color)
        base = np.array([categories.index.get(eid, 0) for eid in ids], dtype=np.int32)
        pd.cell_data["_oss_state"] = base.copy()

        self._surface_pd = pd
        self._surface_ids_ordered = ids
        self._surface_id_to_row = {eid: i for i, eid in enumerate(ids)}
        self._surface_base = base
        self._surface_selected = len(categories.colors)
        self._surface_actor = self._plotter.add_mesh(
            pd,
            scalars="_oss_state",
            cmap=[*categories.colors, self._settings.selected_color],
            clim=[0, len(categories.colors)],
            show_scalar_bar=False,
            show_edges=True,
            edge_color="#5b6b7c",
            line_width=1.0,
            lighting=True,
            pickable=True,
        )

    def _origin_triad_length(self, project: Project) -> float:
        """How long the reference arrows should be for this model.

        A fraction of the model's own extent, so they stay small next to a 100 m
        frame and still visible next to a 100 mm one. An empty project falls
        back to the grid it is showing, and a completely empty one to 1.
        """
        reference = 0.0
        if project.nodes:
            points = np.asarray([node.coords for node in project.nodes], dtype=float)
            reference = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))
        if reference <= 0.0:
            for cs in project.coord_systems:
                for lines in (cs.grid.x_grid_lines, cs.grid.y_grid_lines, cs.grid.z_grid_lines):
                    for line in lines:
                        reference = max(reference, abs(line.ordinate))
        if reference <= 0.0:
            return 1.0
        return reference * _TRIAD_LENGTH_FRACTION

    def _build_origin_triad(self, project: Project) -> None:
        """A small X/Y/Z reference at the world origin (0, 0, 0).

        Three arrows with their labels, in the colours everyone expects, scaled
        to the model. Drawn as scene geometry rather than as a corner widget
        because the question it answers — "which way is +Y here?" — is about the
        model, and the answer has to sit next to the elements being looked at.
        Not pickable: it is a reference, not part of the structure.
        """
        length = self._origin_triad_length(project)
        origin = np.zeros(3)
        for axis, color in enumerate(_TRIAD_COLORS):
            direction = np.zeros(3)
            direction[axis] = 1.0
            arrow = pv.Arrow(
                start=origin,
                direction=direction,
                scale=length,
                tip_length=0.3,
                tip_radius=0.075,
                shaft_radius=0.018,
            )
            self._triad_actors.append(
                self._plotter.add_mesh(arrow, color=color, pickable=False, lighting=False)
            )
        tips = np.eye(3, dtype=float) * length * 1.35
        self._triad_actors.append(
            self._plotter.add_point_labels(
                tips,
                ["X", "Y", "Z"],
                font_size=self._settings.label_size_px,
                text_color="black",
                shape=None,
                always_visible=True,
                pickable=False,
            )
        )

    def _build_grid(self, project: Project) -> None:
        """Draw every :class:`CoordinateGridSystem` as reference geometry.

        Each system's local grid is transformed to world coordinates using
        its ``CoordinateSystem.local_to_world``. Invisible systems are
        skipped. Global uses a warm palette, derived systems step through
        a cool palette so they're visually distinguishable.
        """
        coord_systems = getattr(project, "coord_systems", None)
        if not coord_systems:
            return

        # SAP2000-style: grids are near-black on the light viewport.
        # Intersection dots use a warm accent so they read against the lines.
        derived_palette = [
            ((0.08, 0.08, 0.08), (0.85, 0.55, 0.00)),  # Global (black/amber)
            ((0.20, 0.35, 0.55), (0.85, 0.55, 0.00)),  # navy
            ((0.20, 0.55, 0.30), (0.85, 0.55, 0.00)),  # forest
            ((0.55, 0.20, 0.40), (0.85, 0.55, 0.00)),  # burgundy
            ((0.35, 0.20, 0.55), (0.85, 0.55, 0.00)),  # indigo
        ]

        for idx, cs in enumerate(coord_systems):
            grid = cs.grid
            if not grid.shown:
                continue

            palette_idx = 0 if cs.is_global() else (idx % (len(derived_palette) - 1)) + 1
            grid_color, intersection_color = derived_palette[palette_idx]

            # Active-plane check: lines on the current level are drawn bold and
            # the others dim, without dropping them (keeps scene bounds stable).
            plane_axis: int | None = None
            plane_offset_local: float | None = None
            if self._working_plane is not None:
                plane_name, plane_off = self._working_plane
                plane_axis = {"XY": 2, "XZ": 1, "YZ": 0}[plane_name]
                plane_offset_local = plane_off - cs.coord.origin[plane_axis]

            def _on_active_plane(
                local_pt: tuple[float, float, float],
                *,
                _axis: int | None = plane_axis,
                _offset: float | None = plane_offset_local,
            ) -> bool:
                if _axis is None or _offset is None:
                    return True
                return abs(local_pt[_axis] - _offset) < 1e-6

            active_pts: list[tuple[float, float, float]] = []
            dim_pts: list[tuple[float, float, float]] = []
            for p1, p2 in grid.segments():
                if plane_axis is not None and p1[2] != p2[2] and plane_axis == 2:
                    # Verticals add only clutter while a plan level is active.
                    continue
                bucket = active_pts if _on_active_plane(p1) and _on_active_plane(p2) else dim_pts
                bucket.append(cs.coord.local_to_world(p1))
                bucket.append(cs.coord.local_to_world(p2))

            for pts, width, opacity in ((dim_pts, 0.8, 0.18), (active_pts, 1.8, 1.0)):
                if not pts:
                    continue
                n = len(pts) // 2
                pd = pv.PolyData()
                pd.points = np.array(pts, dtype=float)
                pd.lines = np.column_stack(
                    [np.full(n, 2), np.arange(0, 2 * n, 2), np.arange(1, 2 * n, 2)]
                ).ravel()
                self._aux_actors.append(
                    self._plotter.add_mesh(
                        pd,
                        color=grid_color,
                        line_width=width,
                        opacity=opacity,
                        pickable=False,
                        lighting=False,
                    )
                )

            # Intersection dots — active level bright, others dim.
            active_dots: list[tuple[float, float, float]] = []
            dim_dots: list[tuple[float, float, float]] = []
            for local in grid.intersections():
                world = cs.coord.local_to_world(local)
                (active_dots if _on_active_plane(local) else dim_dots).append(world)
            if dim_dots:
                self._aux_actors.append(
                    self._plotter.add_mesh(
                        pv.PolyData(np.array(dim_dots, dtype=float)),
                        color=(0.6, 0.6, 0.6),
                        point_size=4.0,
                        render_points_as_spheres=True,
                        opacity=0.35,
                        pickable=False,
                        lighting=False,
                    )
                )
            if active_dots:
                self._aux_actors.append(
                    self._plotter.add_mesh(
                        pv.PolyData(np.array(active_dots, dtype=float)),
                        color=intersection_color,
                        point_size=7.0,
                        render_points_as_spheres=True,
                        pickable=False,
                        lighting=False,
                    )
                )

            # Bubble labels: grid id and/or coordinate at the end(s) of each line.
            labels = grid.labels()
            if labels:
                self._aux_actors.append(
                    self._plotter.add_point_labels(
                        np.array([cs.coord.local_to_world(a) for a, _ in labels], dtype=float),
                        [text for _, text in labels],
                        font_size=grid.label_size,
                        text_color=grid.label_color,
                        shape="rounded_rect",
                        shape_color="white",
                        shape_opacity=0.85,
                        show_points=False,
                        always_visible=True,
                        pickable=False,
                    )
                )

    def _build_section_extrusions(self, project: Project) -> None:
        """View → Show Extruded Sections: each member's true section swept along it.

        The outline comes from ``core.section_outline`` (shape hints, fibre
        patches, else the equivalent rectangle) in the member's solver local
        axes, placed on its insertion point. Two actors in all: the surfaces and
        their outline edges.
        """
        from opensees_studio.core.section_outline import member_regions
        from opensees_studio.views.canvas3d.extrusion import SweptMeshes, Template, build_template

        templates: dict[tuple[Any, ...], Template | None] = {}
        swept = SweptMeshes.empty()
        for el in project.elements:
            if not isinstance(el, _FRAME_CLASSES) or len(el.nodes) != 2:
                continue
            try:
                layout = member_layout(project, el)
                regions = member_regions(project, el)
            except (ValueError, KeyError):
                continue
            if layout is None or not regions:
                continue
            key = tuple(regions)
            if key not in templates:
                templates[key] = build_template(regions)
            template = templates[key]
            if template is None:
                continue
            swept.add(template, layout.joint_i + layout.transverse, layout.rotation, layout.length)

        meshes = swept.meshes()
        if meshes is None:
            return
        surface, outline = meshes
        self._aux_actors.append(
            self._plotter.add_mesh(
                surface,
                color=(0.62, 0.68, 0.76),  # steel grey
                opacity=0.55,
                pickable=False,
                lighting=True,
                smooth_shading=False,
            )
        )
        self._aux_actors.append(
            self._plotter.add_mesh(
                outline,
                color=(0.15, 0.22, 0.35),
                line_width=1.0,
                pickable=False,
                lighting=False,
            )
        )

    def _build_supports(self, project: Project) -> None:
        if not project.nodes or self._node_original_points is None:
            return
        ndf = project.ndf
        dof_idx = _dof_indices(project.ndm, ndf)
        size = self._screen_size(self._settings.support_size_percent, minimum=1e-9)
        support_color = (1.0, 0.5, 0.1)
        # One actor per support kind, not one per support: a glyph filter places
        # every copy in a single PolyData, which is what keeps the draw calls
        # flat on a model with hundreds of restrained joints.
        buckets: dict[str, list[np.ndarray]] = {}
        for node in project.nodes:
            if not any(node.restraint[i] for i in dof_idx):
                continue
            kind = _classify_support(node.restraint, dof_idx)
            buckets.setdefault(kind, []).append(np.asarray(node.coords, dtype=float))
        for kind, points in buckets.items():
            cloud = pv.PolyData(np.asarray(points, dtype=float))
            glyphs = cloud.glyph(geom=self._support_glyph(kind, size), scale=False, orient=False)
            actor = self._plotter.add_mesh(
                glyphs, color=support_color, pickable=False, lighting=True
            )
            self._add_screen_actor(actor)
        sprung = [n for n in project.nodes if any(n.spring[i] > 0 for i in dof_idx)]
        if sprung:
            zigzags = pv.merge([self._spring_glyph(size).translate(n.coords) for n in sprung])
            actor = self._plotter.add_mesh(
                zigzags, color=(0.1, 0.6, 0.2), line_width=2, pickable=False, name="support_springs"
            )
            self._add_screen_actor(actor)

    def _build_masses(self, project: Project) -> None:
        """A small diamond at every joint with lumped mass (off by default)."""
        masses = [n for n in project.nodes if any(abs(value) > 0.0 for value in n.mass)]
        if not masses:
            return
        size = self._screen_size(self._settings.mass_size_percent, minimum=1e-9)
        cloud = pv.PolyData(np.asarray([n.coords for n in masses], dtype=float))
        glyphs = cloud.glyph(geom=pv.Octahedron(radius=size), scale=False, orient=False)
        actor = self._plotter.add_mesh(
            glyphs,
            color=self._style.mass_color,
            pickable=False,
            lighting=True,
            name="joint_masses",
        )
        self._add_screen_actor(actor)

    @staticmethod
    def _spring_glyph(size: float) -> pv.PolyData:
        """A zigzag hanging below the joint: a support spring."""
        zs = np.linspace(0.0, -2.5 * size, 8)
        xs = [0.0, 0.0] + [(-1) ** k * 0.5 * size for k in range(4)] + [0.0, 0.0]
        return pv.MultipleLines(np.column_stack([xs, np.zeros(8), zs]))

    #: Actor names of the constraint overlays (``plotter.actors`` keys).
    DIAPHRAGM_ACTOR = "rigid_diaphragms"
    RETAINED_ACTOR = "diaphragm_retained_nodes"
    RIGID_LINK_ACTOR = "rigid_links"

    def _build_constraints(self, project: Project) -> None:
        """Rigid diaphragms as spokes from the retained node, rigid links as thick bars.

        Static overlays like the supports: they mark the model, they are not
        moved with a deformed shape.
        """
        if self._node_original_points is None:
            return
        coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}

        def lines(pairs: list[tuple[int, int]]) -> pv.PolyData | None:
            pairs = [(a, b) for a, b in pairs if a in coords and b in coords]
            if not pairs:
                return None
            points = np.array([coords[nid] for pair in pairs for nid in pair])
            cells = np.hstack([[2, 2 * k, 2 * k + 1] for k in range(len(pairs))])
            return pv.PolyData(points, lines=cells)

        spokes = [
            (d.retained_node, nid)
            for d in project.diaphragms
            for nid in constrained_node_ids(project, d)
        ]
        mesh = lines(spokes)
        if mesh is not None:
            self._aux_actors.append(
                self._plotter.add_mesh(
                    mesh,
                    color=(0.85, 0.25, 0.85),
                    line_width=1.0,
                    opacity=0.6,
                    pickable=False,
                    name=self.DIAPHRAGM_ACTOR,
                )
            )
        retained = [
            coords[d.retained_node] for d in project.diaphragms if d.retained_node in coords
        ]
        if retained:
            size = max(self._diag_of_points(self._node_original_points) * 0.012, 1e-6)
            marker = pv.PolyData(np.array(retained)).glyph(
                geom=pv.Cube(x_length=size, y_length=size, z_length=size), scale=False, orient=False
            )
            self._aux_actors.append(
                self._plotter.add_mesh(
                    marker,
                    color=(0.85, 0.25, 0.85),
                    pickable=False,
                    name=self.RETAINED_ACTOR,
                )
            )
        mesh = lines([(k.retained_node, k.constrained_node) for k in project.rigid_links])
        if mesh is not None:
            self._aux_actors.append(
                self._plotter.add_mesh(
                    mesh,
                    color=(0.9, 0.35, 0.1),
                    line_width=5.0,
                    pickable=False,
                    name=self.RIGID_LINK_ACTOR,
                )
            )

    #: Per-release colours. A full release is one dot per released action;
    #: partial fixity keeps the SAP2000 yellow so it reads as a spring.
    _RELEASE_COLORS: ClassVar[dict[str, str]] = {
        "T": "#b05cff",
        "M2": "#ff9d2e",
        "M3": "#ff4d4d",
    }
    _PARTIAL_RELEASE_COLOR = "#ffd60a"

    def _build_releases(self, project: Project) -> None:
        """Colored dots on the member ends that carry a release.

        One dot per released action, staggered a little along the bar so a
        torsion and a bending release at the same end do not hide each other.
        Full releases use their action colour (T violet, M2 orange, M3 red);
        partial fixity uses yellow, as SAP2000 does for the spring. The dots are
        screen-space points, so their size is independent of the model scale.
        """
        if self._node_original_points is None:
            return
        point_size = max(
            3.0, self._settings.release_size_percent / 100.0 * self._viewport_height_px()
        )
        by_color: dict[str, list[np.ndarray]] = {}
        for element in project.elements:
            if not isinstance(element, FrameMember) or not element.releases.any:
                continue
            try:
                layout = member_layout(project, element)
            except (ValueError, KeyError):
                continue
            if layout is None:
                continue
            for end, face, inward in (
                ("i", layout.face_i, layout.x),
                ("j", layout.face_j, -layout.x),
            ):
                release = element.releases.end(end)
                if not release.released:
                    continue
                step = 0.08 * layout.clear_length
                stagger = 0.04 * layout.clear_length
                for index, dof in enumerate(release.released):
                    if release.spring(dof) > 0.0:
                        color = self._PARTIAL_RELEASE_COLOR
                    else:
                        color = self._RELEASE_COLORS.get(dof, "#ffffff")
                    by_color.setdefault(color, []).append(face + inward * (step + index * stagger))
        for color, points in by_color.items():
            cloud = pv.PolyData(np.asarray(points, dtype=float))
            actor = self._plotter.add_mesh(
                cloud,
                color=color,
                point_size=point_size,
                render_points_as_spheres=True,
                pickable=False,
                lighting=False,
                name=f"releases_{color.lstrip('#')}",
            )
            self._aux_actors.append(actor)

    def _build_frame_assignments(self, project: Project) -> None:
        """Grey bars for the rigid part of end offsets and insertion-point offsets.

        Releases are a separate overlay (``_build_releases``), with their own
        Visibility toggle; this method only draws the rigid zones.
        """
        if self._node_original_points is None:
            return
        arms: list[tuple[np.ndarray, np.ndarray]] = []
        for element in project.elements:
            if not isinstance(element, FrameMember):
                continue
            if not (
                element.end_offsets.rigid_i
                or element.end_offsets.rigid_j
                or not element.insertion.is_default()
            ):
                continue
            try:
                layout = member_layout(project, element)
            except (ValueError, KeyError):
                continue
            if layout is None:
                continue
            if layout.has_offset("i"):
                arms.append((layout.joint_i, layout.face_i))
            if layout.has_offset("j"):
                arms.append((layout.joint_j, layout.face_j))
        if arms:
            arm_points = np.asarray([p for arm in arms for p in arm], dtype=float)
            lines = np.hstack([[2, 2 * k, 2 * k + 1] for k in range(len(arms))])
            actor = self._plotter.add_mesh(
                pv.PolyData(arm_points, lines=lines),
                color=(0.35, 0.35, 0.35),
                line_width=6.0,
                pickable=False,
                lighting=False,
            )
            self._aux_actors.append(actor)

    def set_reactions(self, rows: list[ReactionRow], *, show: bool) -> None:
        """Set the reactions of the shown case and whether to draw them."""
        self._reactions = rows
        self._show_reactions = show
        if self._source_project is not None:
            self.render(self._source_project)

    def _build_reactions(self, project: Project) -> None:
        """Force arrows and moment arcs at the restrained nodes, to scale.

        Both come from the same ``ReactionRow`` list as the table, so a number
        and the picture cannot disagree. The arrow ends on the joint, as the
        load arrows do; the arc is a circle perpendicular to the moment vector,
        read with the right-hand rule.
        """
        if not self._show_reactions or not self._reactions:
            return
        if self._node_original_points is None:
            return
        diagonal = max(self._diag_of_points(self._node_original_points), 1e-9)
        coords = {node.id: np.asarray(node.coords, dtype=float) for node in project.nodes}
        max_force = largest_force(self._reactions)
        max_moment = largest_moment(self._reactions)
        arrow_max = self._screen_size(self._settings.reaction_size_percent, minimum=1e-9)
        arc_max = 0.5 * arrow_max

        f_points, f_dirs, f_lengths = [], [], []
        m_points, m_axes, m_radii = [], [], []
        for row in self._reactions:
            point = coords.get(row.node_id)
            if point is None:
                continue
            if max_force > 0.0 and row.magnitude > 0.0:
                f_points.append(point)
                f_dirs.append(np.asarray(row.forces, dtype=float) / row.magnitude)
                f_lengths.append(max(arrow_max * row.magnitude / max_force, 0.01 * diagonal))
            if max_moment > 0.0 and row.moment_magnitude > 0.0:
                m_points.append(point)
                m_axes.append(np.asarray(row.moments, dtype=float) / row.moment_magnitude)
                m_radii.append(max(arc_max * row.moment_magnitude / max_moment, 0.01 * diagonal))

        self._add_arrow_batch(f_points, f_dirs, f_lengths, (0.85, 0.1, 0.1), "reactions_forces")
        self._add_arc_batch(m_points, m_axes, m_radii, (0.55, 0.1, 0.75), "reactions_moments")

    def _add_arc_batch(
        self,
        points: list[np.ndarray],
        axes: list[np.ndarray],
        radii: list[float],
        color: tuple[float, float, float],
        name: str,
    ) -> None:
        """Draw one circle per moment, in the plane perpendicular to its axis."""
        if not points:
            return
        angles = np.linspace(0.0, 2.0 * np.pi, 33)
        circle = np.column_stack([np.zeros_like(angles), np.cos(angles), np.sin(angles)])
        template = pv.MultipleLines(circle)
        cloud = pv.PolyData(np.asarray(points, dtype=float))
        cloud["vectors"] = np.asarray(axes, dtype=float)
        cloud["radius"] = np.asarray(radii, dtype=float)
        glyphs = cloud.glyph(orient="vectors", scale="radius", geom=template)
        actor = self._plotter.add_mesh(
            glyphs, color=color, line_width=2.0, pickable=False, lighting=False, name=name
        )
        self._add_screen_actor(actor)

    def _build_loads(self, project: Project) -> None:
        """Load arrows, one actor per family instead of one per arrow.

        A pattern with a load on every joint and every member used to draw over
        a thousand actors — each one a draw call and a freshly built arrow mesh.
        The arrows now go into three point clouds (nodal, element, point) and a
        single glyph places, rotates and scales every copy.
        """
        if not project.load_patterns or self._node_original_points is None:
            return
        scale = self._screen_size(self._settings.load_size_percent, minimum=1e-9)
        load_color = (0.2, 0.85, 0.2)
        elem_load_color = (1.0, 0.55, 0.2)  # orange
        point_load_color = (0.85, 0.2, 0.75)  # magenta
        n_arrows_per_elem = 5

        nodes = {node.id: node for node in project.nodes}
        elements = {element.id: element for element in project.elements}
        nodal: list[tuple[np.ndarray, np.ndarray]] = []
        element: list[tuple[np.ndarray, np.ndarray, float]] = []
        point: list[tuple[np.ndarray, np.ndarray]] = []

        for pattern in project.load_patterns:
            if not isinstance(pattern, PlainLoadPattern):
                continue

            for nload in pattern.nodal_loads:
                if not isinstance(nload, NodalLoad):
                    continue
                node = nodes.get(nload.node_id)
                if node is None:
                    continue
                force = np.asarray(nload.forces[:3], dtype=float)
                magnitude = float(np.linalg.norm(force))
                if magnitude < 1e-12:
                    continue
                nodal.append((np.asarray(node.coords, dtype=float), force / magnitude))

            # Uniform load: a row of short arrows along the member.
            for eload in pattern.element_loads:
                if not isinstance(eload, UniformElementLoad):
                    continue
                frame = self._element_local_frame(
                    project, eload.element_id, elements=elements, nodes=nodes
                )
                if frame is None:
                    continue
                pi, axis, (x_local, y_local, z_local) = frame
                length = float(np.linalg.norm(axis))
                load_vec = eload.wx * x_local + eload.wy * y_local + eload.wz * z_local
                magnitude = float(np.linalg.norm(load_vec))
                if magnitude < 1e-12:
                    continue
                direction = load_vec / magnitude
                arrow_len = max(0.4 * scale, length / (n_arrows_per_elem * 4))
                for k in range(n_arrows_per_elem):
                    t = (k + 0.5) / n_arrows_per_elem
                    element.append((pi + t * axis, direction, arrow_len))

            # Trapezoidal / partial: arrows over the loaded part, as long as the
            # load there relative to the largest end value.
            try:
                member_loads = pattern_distributed_loads(project, pattern)
            except AreaLoadError:
                member_loads = list(pattern.distributed_loads)
            for dload in member_loads:
                if not isinstance(dload, TrapezoidalElementLoad):
                    continue
                frame = self._element_local_frame(
                    project, dload.element_id, elements=elements, nodes=nodes
                )
                if frame is None:
                    continue
                pi, axis, (x_local, y_local, z_local) = frame
                length = float(np.linalg.norm(axis))
                ends = [np.asarray(w, dtype=float) for w in (dload.start(), dload.end())]
                peak = max(float(np.linalg.norm(w)) for w in ends)
                if peak < 1e-12:
                    continue
                full_len = max(0.4 * scale, length / (n_arrows_per_elem * 4))
                for k in range(n_arrows_per_elem):
                    t = (k + 0.5) / n_arrows_per_elem
                    wx, wy, wz = ends[0] + t * (ends[1] - ends[0])
                    load_vec = wx * x_local + wy * y_local + wz * z_local
                    magnitude = float(np.linalg.norm(load_vec))
                    if magnitude < 1e-12 * peak:
                        continue
                    x_at = dload.x_start + t * (dload.x_end - dload.x_start)
                    element.append(
                        (pi + x_at * axis, load_vec / magnitude, full_len * magnitude / peak)
                    )

            for pload in pattern.point_loads:
                if not isinstance(pload, PointElementLoad):
                    continue
                frame = self._element_local_frame(
                    project, pload.element_id, elements=elements, nodes=nodes
                )
                if frame is None:
                    continue
                pi, axis, (x_local, y_local, z_local) = frame
                load_vec = pload.px * x_local + pload.py * y_local + pload.pz * z_local
                magnitude = float(np.linalg.norm(load_vec))
                if magnitude < 1e-12:
                    continue
                point.append((pi + pload.x * axis, load_vec / magnitude))

        self._add_arrow_batch(
            [p for p, _ in nodal],
            [d for _, d in nodal],
            [scale] * len(nodal),
            load_color,
            "loads_nodal",
        )
        self._add_arrow_batch(
            [p for p, _, _ in element],
            [d for _, d, _ in element],
            [length for _, _, length in element],
            elem_load_color,
            "loads_element",
        )
        self._add_arrow_batch(
            [p for p, _ in point],
            [d for _, d in point],
            [scale] * len(point),
            point_load_color,
            "loads_point",
        )

    def _add_arrow_batch(
        self,
        points: list[np.ndarray],
        directions: list[np.ndarray],
        lengths: list[float],
        color: tuple[float, float, float],
        name: str,
    ) -> None:
        """Draw a family of load arrows as one glyph actor.

        The glyph filter aligns the template's **x axis** with the vector, so the
        template points along +X with its tip at the origin: a copy oriented
        along the load ends on the joint, where the per-arrow version put it, and
        the per-point length scales it.
        """
        if not points:
            return
        cloud = pv.PolyData(np.asarray(points, dtype=float))
        cloud["vectors"] = np.asarray(directions, dtype=float)
        cloud["length"] = np.asarray(lengths, dtype=float)
        template = pv.Arrow(
            start=(-1.0, 0.0, 0.0),
            direction=(1.0, 0.0, 0.0),
            scale=1.0,
            tip_resolution=8,
            shaft_resolution=8,
        )
        glyphs = cloud.glyph(orient="vectors", scale="length", geom=template)
        actor = self._plotter.add_mesh(
            glyphs, color=color, pickable=False, lighting=True, name=name
        )
        self._add_screen_actor(actor)

    @staticmethod
    def _element_local_frame(
        project: Project,
        element_id: int,
        *,
        elements: dict[int, Any] | None = None,
        nodes: dict[int, Any] | None = None,
    ) -> tuple[np.ndarray, np.ndarray, tuple[np.ndarray, np.ndarray, np.ndarray]] | None:
        """``(p_i, p_j - p_i, (x, y, z))`` of a two-node element, None if it has none.

        ``elements``/``nodes`` are optional id maps. ``_build_loads`` passes
        them so a pattern with thousands of member loads does not scan the
        whole project twice for every load.
        """
        elem = elements.get(element_id) if elements is not None else None
        if elem is None and elements is None:
            elem = next((e for e in project.elements if e.id == element_id), None)
        if elem is None or len(elem.nodes) != 2:
            return None
        if nodes is not None:
            node_i = nodes.get(elem.nodes[0])
            node_j = nodes.get(elem.nodes[1])
        else:
            node_i = next((n for n in project.nodes if n.id == elem.nodes[0]), None)
            node_j = next((n for n in project.nodes if n.id == elem.nodes[1]), None)
        if node_i is None or node_j is None:
            return None
        pi = np.asarray(node_i.coords, dtype=float)
        axis = np.asarray(node_j.coords, dtype=float) - pi
        length = float(np.linalg.norm(axis))
        if length < 1e-9:
            return None
        x_local = axis / length
        if project.ndm == 2:
            # A 2D model is in the X-Z plane: its local axes are OpenSees' own.
            axes2 = frame_local_axes(2, node_i.coords, node_j.coords)
            if axes2 is None:
                return None
            return pi, axis, axes2
        # Same convention as the distributed loads and the diagram renderer.
        y_local = np.cross(np.array([0.0, 0.0, 1.0]), x_local)
        if float(np.linalg.norm(y_local)) < 1e-6:
            y_local = np.cross(np.array([0.0, 1.0, 0.0]), x_local)
        y_local = y_local / float(np.linalg.norm(y_local))
        z_local = np.cross(x_local, y_local)
        return pi, axis, (x_local, y_local, z_local)

    # ── mode update ─────────────────────────────────────────────────
    def _apply_mode_to_points(self) -> None:
        if self._node_pd is None or self._node_original_points is None or self._project is None:
            return
        if self._mode == RendererMode.MODEL or self._deformation is None:
            new_pts = self._node_original_points
        else:
            new_pts = self._deformation.shifted(self._node_original_points, self._node_ids_ordered)
        self._node_pd.points = new_pts
        self._node_pd.Modified()
        if self._frame_pd is not None:
            self._frame_pd.points = new_pts
            self._frame_pd.Modified()
        if self._surface_pd is not None:
            self._surface_pd.points = new_pts
            self._surface_pd.Modified()
        self._rebuild_labels()

    # ── helpers ─────────────────────────────────────────────────────
    def _categories(self, project: Project, default_color: str) -> Categories:
        """The View → Color By categories of the elements, ``default_color`` for "none"."""
        return element_categories(project, self._settings.color_by, default_color)

    def _build_color_legend(self, project: Project) -> None:
        """A legend of the Color By categories the viewport shows (none for one colour)."""
        if self._settings.color_by == "none":
            return
        shown = set(self._frame_ids_ordered) | set(self._surface_ids_ordered)
        categories = self._categories(project, self._settings.frame_color)
        used = sorted({categories.index[eid] for eid in shown if eid in categories.index})
        if not used:
            return
        entries = [[categories.labels[k], categories.colors[k]] for k in used]
        if len(entries) > LEGEND_MAX_ENTRIES:
            entries = [*entries[: LEGEND_MAX_ENTRIES - 1], ["…", "#ffffff"]]
        self._legend_actor = self._plotter.add_legend(
            entries,
            bcolor="#ffffff",
            border=True,
            loc="upper right",
            face="rectangle",
            size=(0.24, min(0.05 * len(entries), 0.6)),
        )

    def _teardown_all(self) -> None:
        self._clear_label_actors()
        if getattr(self, "_legend_actor", None) is not None:
            with contextlib.suppress(Exception):
                self._plotter.remove_legend(render=False)
            self._legend_actor = None
        for a in (self._node_actor, self._frame_actor, self._surface_actor):
            if a is not None:
                with contextlib.suppress(Exception):
                    self._plotter.remove_actor(a, render=False)
        for a in (*self._aux_actors, *self._triad_actors):
            with contextlib.suppress(Exception):
                self._plotter.remove_actor(a, render=False)
        self._node_actor = None
        self._frame_actor = None
        self._surface_actor = None
        self._aux_actors.clear()
        self._screen_actors.clear()
        self._screen_key = None
        self._triad_actors.clear()
        self._node_pd = None
        self._node_point_size = 0.0
        self._frame_pd = None
        self._node_ids_ordered = []
        self._node_id_to_row = {}
        self._frame_ids_ordered = []
        self._frame_id_to_row = {}
        self._surface_pd = None
        self._surface_ids_ordered = []
        self._surface_id_to_row = {}
        self._node_original_points = None
        self._deformation = None
        self._mode = RendererMode.MODEL

    def _clear_label_actors(self) -> None:
        for actor in (self._node_label_actor, self._element_label_actor):
            if actor is not None:
                with contextlib.suppress(Exception):
                    self._plotter.remove_actor(actor, render=False)
        self._node_label_actor = None
        self._element_label_actor = None

    def _rebuild_labels(self) -> None:
        self._clear_label_actors()
        if self._project is None:
            return
        if self._settings.show_node_labels:
            self._node_label_actor = self._add_node_labels(self._project)
        if self._settings.show_element_labels:
            self._element_label_actor = self._add_element_labels(self._project)

    def _add_node_labels(self, project: Project) -> Any:
        if self._node_pd is None or len(project.nodes) == 0:
            return None
        pts = np.asarray(self._node_pd.points)
        labels = [
            (node.name.strip() if node.name.strip() else f"N{node.id}") for node in project.nodes
        ]
        return self._plotter.add_point_labels(
            pts,
            labels,
            font_size=self._settings.label_size_px,
            shape_opacity=0.15,
            text_color="black",
            point_color="white",
            point_size=1,
            render_points_as_spheres=False,
            always_visible=True,
            pickable=False,
        )

    def _add_element_labels(self, project: Project) -> Any:
        if self._node_pd is None:
            return None
        pts = np.asarray(self._node_pd.points)
        centers: list[np.ndarray] = []
        labels: list[str] = []
        for el in project.elements:
            if len(el.nodes) != 2:
                continue
            i = self._node_id_to_row.get(el.nodes[0])
            j = self._node_id_to_row.get(el.nodes[1])
            if i is None or j is None:
                continue
            centers.append((pts[i] + pts[j]) / 2.0)
            labels.append(el.name.strip() if el.name.strip() else f"E{el.id}")
        if not centers:
            return None
        return self._plotter.add_point_labels(
            np.asarray(centers),
            labels,
            font_size=self._settings.label_size_px,
            shape_opacity=0.15,
            text_color="black",
            point_color="white",
            point_size=1,
            render_points_as_spheres=False,
            always_visible=True,
            pickable=False,
        )

    @staticmethod
    def _diag_of_points(pts: np.ndarray | None) -> float:
        if pts is None or len(pts) == 0:
            return 1.0
        mn, mx = pts.min(axis=0), pts.max(axis=0)
        d = float(np.linalg.norm(mx - mn))
        return d if d > 0 else 1.0

    @staticmethod
    def _support_glyph(kind: str, size: float) -> pv.PolyData:
        if kind == "fix":
            return pv.Cube(x_length=size * 1.5, y_length=size * 1.5, z_length=size * 0.4)
        if kind == "pin":
            return pv.Cone(direction=(0, 0, -1), height=size * 1.5, radius=size, resolution=8)
        if kind == "roller":
            return pv.Cylinder(direction=(1, 0, 0), height=size, radius=size * 0.5, resolution=8)
        return pv.Cube(x_length=size, y_length=size, z_length=size)
