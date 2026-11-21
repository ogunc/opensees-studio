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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
    ShellDKGTElement,
    ShellMITC4Element,
    TrapezoidalElementLoad,
    TrussElement,
    UniformElementLoad,
    ZeroLengthElement,
)
from opensees_studio.core.area_loads import (
    AreaLoadError,
    pattern_distributed_loads,
    shell_normal,
    surface_corner_pressures,
)
from opensees_studio.core.color_by import Categories, element_categories
from opensees_studio.core.diaphragms import constrained_node_ids
from opensees_studio.core.frame_members import member_layout
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.load_display import (
    KIND_COLORS,
    format_force,
    format_line_load,
    format_pressure,
    hex_to_rgb,
    pattern_colors,
    shown_patterns,
)
from opensees_studio.core.plane import dof_indices as plane_dof_indices
from opensees_studio.core.reactions import (
    ReactionRow,
    largest_force,
    largest_moment,
)
from opensees_studio.core.support_springs import SpringError, nodal_springs
from opensees_studio.core.units import UnitConverter
from opensees_studio.core.view_settings import ViewSettings
from opensees_studio.diagnostics.performance import perf
from opensees_studio.services.deformation import DeformationSource
from opensees_studio.views.canvas3d.style import RenderStyle, legible


@dataclass(frozen=True)
class _SurfaceArrow:
    """One arrow of a shell load: it ends at ``tip``; ``label`` is the pressure, or 0."""

    tip: np.ndarray
    direction: np.ndarray
    length: float
    pattern: Any
    label: float = 0.0


class RendererMode(enum.Enum):
    MODEL = "model"
    DEFORMED = "deformed"
    MODAL = "modal"


def dashed_line_geometry(
    start: Sequence[float],
    end: Sequence[float],
    *,
    dashes: int = 32,
    fill: float = 0.55,
) -> tuple[np.ndarray, np.ndarray]:
    """Points and line cells of a dashed segment, with a gap between each dash.

    A line stipple pattern is not dependable on every VTK backend, so the
    measurement guide is built as real short segments. ``fill`` is the share of
    each slot the dash occupies (0.55 = slightly more ink than gap).
    """
    if dashes < 1:
        raise ValueError("a dashed line needs at least one dash")
    if not 0.0 < fill <= 1.0:
        raise ValueError("fill must be in (0, 1]")
    a = np.asarray(start, dtype=float)
    b = np.asarray(end, dtype=float)
    if a.shape != (3,) or b.shape != (3,):
        raise ValueError("start and end must be 3D points")
    direction = b - a
    if float(np.linalg.norm(direction)) <= 1e-12:
        return np.empty((0, 3), dtype=float), np.empty(0, dtype=np.int64)
    points = np.empty((dashes * 2, 3), dtype=float)
    cells = np.empty(dashes * 3, dtype=np.int64)
    for index in range(dashes):
        t0 = index / dashes
        t1 = min(t0 + fill / dashes, 1.0)
        points[2 * index] = a + direction * t0
        points[2 * index + 1] = a + direction * t1
        cells[3 * index : 3 * index + 3] = (2, 2 * index, 2 * index + 1)
    return points, cells


def distributed_load_glyphs(
    bases: Sequence[np.ndarray],
    directions: Sequence[np.ndarray],
    lengths: Sequence[float],
    axis: np.ndarray,
) -> tuple[np.ndarray, list[list[int]]]:
    """Line geometry for one distributed load: shafts, arrowheads and top line.

    The members' display already has enough solid geometry; a distributed load
    reads better as a 2D-style diagram: one short line from the member to the
    load line at every station, a V-shaped head on each, and a polyline joining
    the tails (the "top line"). Everything is returned as one point array plus
    polylines of indices, so the caller can draw the whole family in one actor.

    ``bases`` lie on the member, ``directions`` are unit load vectors (the way
    the load acts) and ``lengths`` scale each arrow. The load line is offset
    **against** the direction, so the arrows point from the line onto the
    member, as a load diagram should. A zero length keeps the tail on the
    member (a triangular load that starts at zero) and contributes to the top
    line without drawing a shaft or head. ``axis`` is the member's direction,
    used to put the arrowheads in the member/load plane.
    """
    base_array = np.asarray(bases, dtype=float)
    direction_array = np.asarray(directions, dtype=float)
    length_array = np.maximum(np.asarray(lengths, dtype=float), 0.0)
    if base_array.ndim != 2 or base_array.shape[1] != 3:
        raise ValueError("bases must be an N x 3 array")
    if direction_array.shape != base_array.shape or length_array.shape != (len(base_array),):
        raise ValueError("bases, directions and lengths must have one row per station")
    axis = np.asarray(axis, dtype=float)
    if axis.shape != (3,):
        raise ValueError("axis must be a 3-vector")

    count = len(base_array)
    if count == 0:
        return np.empty((0, 3), dtype=float), []

    tails = base_array - direction_array * length_array[:, None]
    dots = direction_array @ axis
    sides = axis[None, :] - direction_array * dots[:, None]
    norms = np.linalg.norm(sides, axis=1)
    bad = norms <= 1e-12
    if np.any(bad):
        fallback = np.zeros_like(sides)
        fallback[:, 2] = 1.0
        along_z = np.abs(direction_array[:, 2]) > 0.9
        fallback[along_z] = (1.0, 0.0, 0.0)
        fallback_dots = np.einsum("ij,ij->i", fallback, direction_array)
        fallback_sides = fallback - direction_array * fallback_dots[:, None]
        fallback_norms = np.linalg.norm(fallback_sides, axis=1)
        sides[bad] = fallback_sides[bad]
        norms[bad] = fallback_norms[bad]
    safe = norms > 1e-12
    sides[safe] /= norms[safe, None]
    sides[~safe] = 0.0

    head_lengths = 0.45 * length_array
    head_widths = 0.6 * head_lengths
    heads = base_array - direction_array * head_lengths[:, None]
    head_minus = heads - sides * head_widths[:, None]
    head_plus = heads + sides * head_widths[:, None]

    points = np.empty((count * 4, 3), dtype=float)
    points[0::4] = base_array
    points[1::4] = tails
    points[2::4] = head_minus
    points[3::4] = head_plus

    polylines: list[list[int]] = []
    for index, length in enumerate(length_array):
        if length <= 0.0:
            continue
        base = index * 4
        polylines.append([base, base + 1])
        polylines.append([base, base + 2])
        polylines.append([base, base + 3])
    if count > 1:
        polylines.append([index * 4 + 1 for index in range(count)])
    return points, polylines


def uniform_load_glyphs(
    bases: np.ndarray,
    directions: np.ndarray,
    lengths: np.ndarray,
    axes: np.ndarray,
    stations: int,
) -> tuple[np.ndarray, list[list[int]]]:
    """Line geometry for a batch of uniform member loads, one top line per member.

    This is the batched form of :func:`distributed_load_glyphs` for the dense
    case (one uniform load on every member of a grid): the per-call numpy
    overhead of a few hundred small arrays is what pushed the loaded benchmark
    over its render budget. ``bases``/``directions``/``axes`` are ``N x 3``,
    ``lengths`` is ``N``; each member gets ``stations`` stations along its axis.
    """
    if stations < 2:
        raise ValueError("A load diagram needs at least two stations.")
    bases = np.asarray(bases, dtype=float)
    directions = np.asarray(directions, dtype=float)
    axes = np.asarray(axes, dtype=float)
    lengths = np.maximum(np.asarray(lengths, dtype=float), 0.0)
    if bases.ndim != 2 or bases.shape[1] != 3:
        raise ValueError("bases must be an N x 3 array")
    if directions.shape != bases.shape or axes.shape != bases.shape:
        raise ValueError("directions and axes must be N x 3 arrays")
    if lengths.shape != (len(bases),):
        raise ValueError("lengths must have one entry per member")
    if len(bases) == 0:
        return np.empty((0, 3), dtype=float), []

    count = len(bases)
    t = np.linspace(0.0, 1.0, stations)
    base_points = bases[:, None, :] + t[None, :, None] * axes[:, None, :]
    directions_b = np.broadcast_to(directions[:, None, :], base_points.shape)
    lengths_b = np.broadcast_to(lengths[:, None], (count, stations))
    tails = base_points - directions_b * lengths_b[..., None]

    dots = np.einsum("nj,nj->n", directions, axes)
    sides = axes - directions * dots[:, None]
    norms = np.linalg.norm(sides, axis=1)
    bad = norms <= 1e-12
    if np.any(bad):
        fallback = np.zeros_like(sides)
        fallback[:, 2] = 1.0
        along_z = np.abs(directions[:, 2]) > 0.9
        fallback[along_z] = (1.0, 0.0, 0.0)
        fallback_dots = np.einsum("nj,nj->n", fallback, directions)
        fallback_sides = fallback - directions * fallback_dots[:, None]
        fallback_norms = np.linalg.norm(fallback_sides, axis=1)
        sides[bad] = fallback_sides[bad]
        norms[bad] = fallback_norms[bad]
    safe = norms > 1e-12
    sides[safe] /= norms[safe, None]
    sides[~safe] = 0.0

    head_lengths = 0.45 * lengths_b
    head_widths = 0.6 * head_lengths
    heads = base_points - directions_b * head_lengths[..., None]
    head_minus = heads - sides[:, None, :] * head_widths[..., None]
    head_plus = heads + sides[:, None, :] * head_widths[..., None]
    points = np.stack((base_points, tails, head_minus, head_plus), axis=2).reshape(-1, 3)

    polylines: list[list[int]] = []
    for index in range(count):
        offset = index * stations * 4
        for station in range(stations):
            base = offset + station * 4
            polylines.append([base, base + 1])
            polylines.append([base, base + 2])
            polylines.append([base, base + 3])
        polylines.append([offset + station * 4 + 1 for station in range(stations)])
    return points, polylines


#: Colours of the origin reference: the usual X red, Y green, Z blue.
_TRIAD_COLORS: tuple[str, str, str] = ("#d0402f", "#2f9e4f", "#2f5fcf")

#: Local x / y / z of a member, in the same colour language as the origin triad.
_LOCAL_AXIS_COLORS: tuple[tuple[float, float, float], ...] = (
    (0.82, 0.25, 0.18),
    (0.18, 0.62, 0.31),
    (0.18, 0.37, 0.81),
)

#: Arrow length as a fraction of the model's extent, so it reads at any zoom.
_TRIAD_LENGTH_FRACTION = 0.08

#: Elements drawn as surfaces (a filled face) rather than as lines.
#: The Color By legend lists at most this many categories.
LEGEND_MAX_ENTRIES = 15

_SURFACE_CLASSES = (
    QuadElement,
    ShellMITC4Element,
    ShellDKGTElement,
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
        #: Legend rows of the loads the last build drew (``_build_loads``).
        self._load_legend_entries: list[list[str]] = []
        #: The magnitudes beside the loads, when View settings ask for them.
        self._load_values_actor: Any = None
        self._screen_key: tuple[float, ...] | None = None
        self._hover_actor: Any = None  # single yellow-ring snap marker
        #: Measure Distance's transient graphics: the first joint, the dashed
        #: guide to the joint under the pointer, and the length badge.
        self._measure_anchor_actor: Any = None
        self._measure_guide_actor: Any = None
        self._measure_label_actor: Any = None
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
        if self._settings.show_local_axes:
            self._timed_build("local_axes", self._build_local_axes, project)
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
        self._timed_build("color_legend", self._build_color_legend, project)
        # After the loads: it names the load patterns they drew.
        self._timed_build("load_legend", self._build_load_legend, project)
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

    def set_style(self, style: RenderStyle) -> None:
        """Swap the style (dark mode) and repaint the scene with it."""
        self._style = style
        if self._project is not None:
            self.render(self._project)

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

    @property
    def mode(self) -> RendererMode:
        """What the viewport is drawing: the model, a deformation or a mode shape."""
        return self._mode

    #: Marker colour per snap kind; the grid preview keeps the amber default.
    SNAP_COLORS: ClassVar[dict[str, tuple[float, float, float]]] = {
        "node": (1.0, 0.9, 0.0),  # bright yellow: the joint a click would pick
        "midpoint": (1.0, 0.85, 0.0),  # amber
        "perpendicular": (0.15, 0.75, 1.0),  # blue
        "on_element": (0.35, 1.0, 0.45),  # green
    }

    def set_hover_snap(
        self, world_point: tuple[float, float, float] | None, kind: str | None = None
    ) -> None:
        """Show / hide the snap-target indicator.

        Passing ``None`` removes the marker. Passing a world point
        renders (or repositions) a single sphere at that point — the
        visual cue telling the user where a click would land. ``kind``
        selects the member-snap colour; the grid preview stays amber.
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
        colour = self.SNAP_COLORS.get(kind or "", (1.0, 0.85, 0.0))
        self._hover_actor = self._plotter.add_mesh(
            sphere,
            color=colour,
            opacity=0.85,
            pickable=False,
            lighting=False,
        )

    def node_point(self, node_id: int) -> tuple[float, float, float] | None:
        """World point of a drawn joint, or None when it is hidden or absent."""
        row = self._node_id_to_row.get(node_id)
        if row is None or self._node_pd is None:
            return None
        point = np.asarray(self._node_pd.points)[row]
        return (float(point[0]), float(point[1]), float(point[2]))

    def set_measure_anchor(self, world_point: tuple[float, float, float] | None) -> None:
        """Red marker on the first joint of a running measurement."""
        if self._measure_anchor_actor is not None:
            with contextlib.suppress(Exception):
                self._plotter.remove_actor(self._measure_anchor_actor, render=False)
            self._measure_anchor_actor = None
        if world_point is None:
            return
        radius = 0.5 * self._screen_size(self._settings.node_size_percent * 1.9, minimum=1e-9)
        sphere = pv.Sphere(
            center=tuple(float(value) for value in world_point),
            radius=radius,
            theta_resolution=20,
            phi_resolution=20,
        )
        self._measure_anchor_actor = self._plotter.add_mesh(
            sphere,
            color="#ff2d2d",
            opacity=1.0,
            pickable=False,
            lighting=False,
        )

    def set_measure_guide(
        self,
        start: tuple[float, float, float] | None,
        end: tuple[float, float, float] | None,
        label: str,
    ) -> None:
        """Thin dashed guide between the first joint and the candidate second one."""
        self.clear_measure_guide()
        if start is None or end is None:
            return
        points, cells = dashed_line_geometry(start, end)
        if not len(points):
            return
        self._measure_guide_actor = self._plotter.add_mesh(
            pv.PolyData(points, lines=cells),
            color="#d93025",
            line_width=1.5,
            pickable=False,
            lighting=False,
        )
        midpoint = (np.asarray(start, dtype=float) + np.asarray(end, dtype=float)) / 2.0
        self._measure_label_actor = self._plotter.add_point_labels(
            [midpoint],
            [label],
            font_size=self._settings.label_size_px,
            shape="rounded_rect",
            shape_color=self._style.label_paper,
            shape_opacity=0.9,
            text_color=self._style.label_ink,
            show_points=False,
            always_visible=True,
            pickable=False,
        )

    def clear_measure_guide(self) -> None:
        """Remove the dashed guide and its length badge, keeping the anchor."""
        for attribute in ("_measure_guide_actor", "_measure_label_actor"):
            actor = getattr(self, attribute)
            if actor is not None:
                with contextlib.suppress(Exception):
                    self._plotter.remove_actor(actor, render=False)
                setattr(self, attribute, None)

    def clear_measure_preview(self) -> None:
        """Remove every transient graphic Measure Distance drew."""
        self.set_measure_anchor(None)
        self.clear_measure_guide()

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
            if len(rows) not in (3, 4):
                continue
            cells.extend([len(rows), *rows])  # a face cell: size then its corners
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

    def _build_local_axes(self, project: Project) -> None:
        """A red/green/blue x/y/z triad at the midpoint of every frame member.

        The triad uses exactly the axes the runner and the load conversion use
        (:func:`frame_local_axes`), so it answers "which way is local y here?"
        with the same answer as the analysis. Screen size is not involved: the
        axes are a fraction of each member's length, so they zoom with the model.
        """
        nodes = {node.id: node for node in project.nodes}
        points: list[np.ndarray] = []
        cells: list[int] = []
        colors: list[tuple[float, float, float]] = []
        for element in project.elements:
            if not isinstance(element, _FRAME_CLASSES) or len(element.nodes) != 2:
                continue
            node_i = nodes.get(element.nodes[0])
            node_j = nodes.get(element.nodes[1])
            if node_i is None or node_j is None:
                continue
            pi = np.asarray(node_i.coords, dtype=float)
            pj = np.asarray(node_j.coords, dtype=float)
            length = float(np.linalg.norm(pj - pi))
            if length < 1e-9:
                continue
            angle = float(getattr(element, "local_axis_angle", 0.0) or 0.0)
            axes = frame_local_axes(project.ndm, node_i.coords, node_j.coords, angle)
            if axes is None:
                continue
            midpoint = 0.5 * (pi + pj)
            size = 0.22 * length
            # Just beside the member, so the local x line does not disappear
            # under the member's own (blue) line.
            origin = midpoint + axes[1] * (0.12 * length)
            for axis, color in zip(axes, _LOCAL_AXIS_COLORS, strict=True):
                start_index = len(points)
                points.append(origin)
                points.append(origin + axis * size)
                cells.extend([2, start_index, start_index + 1])
                colors.append(color)
        if not cells:
            return
        pd = pv.PolyData()
        pd.points = np.asarray(points, dtype=float)
        pd.lines = np.asarray(cells, dtype=np.int64)
        pd.cell_data["_axis_color"] = np.asarray(colors, dtype=float)
        actor = self._plotter.add_mesh(
            pd,
            scalars="_axis_color",
            rgb=True,
            line_width=2.5,
            pickable=False,
            lighting=False,
            name="local_axes",
        )
        self._aux_actors.append(actor)

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
                text_color=self._style.label_ink,
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
        bed = self._distributed_spring_glyphs(project, size)
        if bed is not None:
            actor = self._plotter.add_mesh(
                bed, color=(0.55, 0.35, 0.15), line_width=2, pickable=False, name="bed_springs"
            )
            self._add_screen_actor(actor)

    def _distributed_spring_glyphs(self, project: Project, size: float) -> pv.PolyData | None:
        """A zigzag at every node of a line, edge or area spring, toward the medium.

        The glyph hangs along -Z from its joint; it is turned so that it hangs on
        the side of the supporting medium (``-d``, ``d`` pointing to the structure).
        """
        try:
            springs = nodal_springs(project)
        except SpringError:
            return None
        if not springs:
            return None
        coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
        glyphs = []
        seen: set[tuple[int, tuple[float, float, float]]] = set()
        for spring in springs:
            key = (spring.node_id, spring.direction)
            if spring.node_id not in coords or key in seen:
                continue
            seen.add(key)
            d = np.asarray(spring.direction, dtype=float)
            glyph = self._spring_glyph(0.7 * size)
            glyph.transform(_rotation_to(d), inplace=True)
            glyphs.append(glyph.translate(coords[spring.node_id]))
        return pv.merge(glyphs) if glyphs else None

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

        Nodal and point loads keep the 3D glyph; distributed member loads are
        drawn as a 2D-style diagram — a row of line shafts with V-shaped heads
        joined by a top line — because it reads as a load diagram rather than a
        row of unrelated spears, and costs one line actor instead of a glyph
        per station.

        What is drawn follows the view settings (Display → Show Load Assigns,
        ``core.load_display``): one load pattern or all of them, and which kinds
        of load. With several patterns each one takes its colour, and loads that
        share a member, a point or a joint are stacked outward so none hides
        another. Arrow sizes are proportional to the magnitudes drawn: forces
        against the largest force, loads per length against the largest one.
        """
        self._load_legend_entries = []
        self._load_values_actor = None
        if not project.load_patterns or self._node_original_points is None:
            return
        settings = self._settings
        plain = [p for p in project.load_patterns if isinstance(p, PlainLoadPattern)]
        patterns = shown_patterns(plain, settings.load_pattern_id)
        if not patterns:
            return
        by_pattern = len(patterns) > 1
        palette = pattern_colors(plain)
        units = UnitConverter.of(project.meta)
        scale = self._screen_size(settings.load_size_percent, minimum=1e-9)
        gap = 0.25 * scale
        distributed_stations = 5

        nodes = {node.id: node for node in project.nodes}
        elements = {element.id: element for element in project.elements}
        drawn: dict[int, set[str]] = {}
        #: key → [top of the stack]: where the next load at that place starts.
        stacks: dict[tuple[Any, ...], list[float]] = {}

        pattern_rgb = {pid: hex_to_rgb(color) for pid, color in palette.items()}
        kind_rgb = {kind: hex_to_rgb(color) for kind, color in KIND_COLORS.items()}

        def color_of(pattern: Any, kind: str) -> tuple[float, float, float]:
            drawn.setdefault(pattern.id, set()).add(kind)
            return pattern_rgb[pattern.id] if by_pattern else kind_rgb[kind]

        def stacked(key: tuple[Any, ...], height: float) -> float:
            """The offset of the next load drawn at ``key``; reserves ``height`` above it."""
            entry = stacks.setdefault(key, [0.0])
            base = float(entry[0])
            entry[0] = base + height + gap
            return base

        def direction_key(direction: np.ndarray) -> bytes:
            return direction.round(3).tobytes()

        # ── what is drawn, before any size: the sizes are relative ──────
        joint_items: list[tuple[Any, np.ndarray, np.ndarray, int]] = []
        point_items: list[tuple[Any, PointElementLoad, np.ndarray, np.ndarray]] = []
        uniform_items: list[tuple[Any, UniformElementLoad, tuple[Any, ...], np.ndarray]] = []
        trapezoid_items: list[tuple[Any, TrapezoidalElementLoad, tuple[Any, ...]]] = []
        for pattern in patterns:
            if settings.show_joint_loads:
                for nload in pattern.nodal_loads:
                    node = nodes.get(nload.node_id) if isinstance(nload, NodalLoad) else None
                    if node is None:
                        continue
                    force = np.asarray(nload.forces[:3], dtype=float)
                    if float(np.linalg.norm(force)) >= 1e-12:
                        joint_items.append(
                            (pattern, np.asarray(node.coords, dtype=float), force, node.id)
                        )
            if settings.show_frame_point_loads:
                for pload in pattern.point_loads:
                    if not isinstance(pload, PointElementLoad):
                        continue
                    frame = self._element_local_frame(
                        project, pload.element_id, elements=elements, nodes=nodes
                    )
                    if frame is None:
                        continue
                    pi, axis, (x_local, y_local, z_local) = frame
                    vector = pload.px * x_local + pload.py * y_local + pload.pz * z_local
                    if float(np.linalg.norm(vector)) >= 1e-12:
                        point_items.append((pattern, pload, pi + pload.x * axis, vector))
            if settings.show_frame_distributed_loads:
                for eload in pattern.element_loads:
                    if not isinstance(eload, UniformElementLoad):
                        continue
                    frame = self._element_local_frame(
                        project, eload.element_id, elements=elements, nodes=nodes
                    )
                    if frame is None:
                        continue
                    _, _, (x_local, y_local, z_local) = frame
                    vector = eload.wx * x_local + eload.wy * y_local + eload.wz * z_local
                    if float(np.linalg.norm(vector)) >= 1e-12:
                        uniform_items.append((pattern, eload, frame, vector))
                # Trapezoidal / partial: the top line follows the load intensity
                # over the loaded part, so a triangular load shows its zero end.
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
                    if frame is not None:
                        trapezoid_items.append((pattern, dload, frame))

        force_peak = max(
            [float(np.linalg.norm(f)) for _, _, f, _ in joint_items]
            + [float(np.linalg.norm(v)) for _, _, _, v in point_items],
            default=0.0,
        )
        line_peak = max(
            [float(np.linalg.norm(v)) for _, _, _, v in uniform_items]
            + [
                max(float(np.linalg.norm(w)) for w in (d.start(), d.end()))
                for _, d, _ in trapezoid_items
            ],
            default=0.0,
        )

        def force_length(magnitude: float) -> float:
            return scale * max(0.45, magnitude / force_peak) if force_peak > 0 else scale

        want_values = settings.show_load_values
        values: list[tuple[np.ndarray, str]] = []
        nodal: list[tuple[np.ndarray, np.ndarray, float, tuple[float, float, float]]] = []
        for pattern, location, force, node_id in joint_items:
            magnitude = float(np.linalg.norm(force))
            direction = force / magnitude
            length = force_length(magnitude)
            offset = stacked(("joint", node_id, direction_key(direction)), length)
            tip = location - direction * offset
            nodal.append((tip, direction, length, color_of(pattern, "joint")))
            if want_values:
                values.append((tip - direction * length, format_force(magnitude, units)))

        point: list[tuple[np.ndarray, np.ndarray, float, tuple[float, float, float]]] = []
        for pattern, pload, location, vector in point_items:
            magnitude = float(np.linalg.norm(vector))
            direction = vector / magnitude
            length = force_length(magnitude)
            # Point loads stack only where they coincide; the member's
            # distributed diagrams start above the tallest of them.
            side = direction_key(direction)
            key = ("point", pload.element_id, round(pload.x, 4), side)
            offset = stacked(key, length)
            tip = location - direction * offset
            member_key = ("member", pload.element_id, side)
            above = offset + length + gap
            if above > stacks.get(member_key, [0.0])[0]:
                stacks[member_key] = [above]
            point.append((tip, direction, length, color_of(pattern, "frame_point")))
            if want_values:
                values.append((tip - direction * length, format_force(magnitude, units)))

        distributed_points: list[np.ndarray] = []
        distributed_polylines: list[list[int]] = []
        distributed_colors: list[tuple[float, float, float]] = []

        def add_polylines(
            local_points: np.ndarray,
            local_polylines: list[list[int]],
            color: tuple[float, float, float],
        ) -> None:
            offset = len(distributed_points)
            distributed_points.extend(local_points)
            distributed_polylines.extend(
                [[index + offset for index in polyline] for polyline in local_polylines]
            )
            distributed_colors.extend([color] * len(local_polylines))

        # Uniform loads: the batched glyph builder (dense grids carry one on
        # every member), shifted outward by each load's place in its stack.
        uniform_bases: list[np.ndarray] = []
        uniform_directions: list[np.ndarray] = []
        uniform_lengths: list[float] = []
        uniform_axes: list[np.ndarray] = []
        uniform_colors: list[tuple[float, float, float]] = []
        for pattern, eload, (pi, axis, _), vector in uniform_items:
            magnitude = float(np.linalg.norm(vector))
            direction = vector / magnitude
            member_length = float(np.linalg.norm(axis))
            full_len = max(0.6 * scale, member_length / 12.0)
            arrow_len = full_len * max(0.2, magnitude / line_peak)
            offset = stacked(("member", eload.element_id, direction_key(direction)), arrow_len)
            uniform_bases.append(pi - direction * offset)
            uniform_directions.append(direction)
            uniform_lengths.append(arrow_len)
            uniform_axes.append(axis)
            uniform_colors.append(color_of(pattern, "frame_distributed"))
            if want_values:
                # On the top line, a quarter along: the middle is where point
                # loads and other labels gather.
                at = pi + 0.25 * axis - direction * (offset + arrow_len + 0.3 * gap)
                values.append((at, format_line_load(magnitude, None, units)))

        for pattern, dload, (pi, axis, (x_local, y_local, z_local)) in trapezoid_items:
            member_length = float(np.linalg.norm(axis))
            ends = [np.asarray(w, dtype=float) for w in (dload.start(), dload.end())]
            peak = max(float(np.linalg.norm(w)) for w in ends)
            if peak < 1e-12:
                continue
            full_len = max(0.6 * scale, member_length / 12.0) * max(0.2, peak / line_peak) / peak
            peak_end = (
                ends[0]
                if float(np.linalg.norm(ends[0])) >= float(np.linalg.norm(ends[1]))
                else ends[1]
            )
            peak_vector = peak_end[0] * x_local + peak_end[1] * y_local + peak_end[2] * z_local
            peak_direction = peak_vector / float(np.linalg.norm(peak_vector))
            offset = stacked(
                ("member", dload.element_id, direction_key(peak_direction)), full_len * peak
            )
            bases = []
            directions = []
            lengths = []
            for k in range(distributed_stations):
                t = k / (distributed_stations - 1)
                wx, wy, wz = ends[0] + t * (ends[1] - ends[0])
                load_vec = wx * x_local + wy * y_local + wz * z_local
                magnitude = float(np.linalg.norm(load_vec))
                x_at = dload.x_start + t * (dload.x_end - dload.x_start)
                bases.append(pi + x_at * axis - peak_direction * offset)
                if magnitude < 1e-12 * peak:
                    directions.append(np.zeros(3))
                    lengths.append(0.0)
                else:
                    directions.append(load_vec / magnitude)
                    lengths.append(full_len * magnitude)
            local_points, local_polylines = distributed_load_glyphs(
                bases, directions, lengths, axis
            )
            add_polylines(local_points, local_polylines, color_of(pattern, "frame_distributed"))
            if want_values:
                # Over the loaded part, a quarter of the way along it, above the
                # tallest arrow so the varying top line does not cross the text.
                at = dload.x_start + 0.25 * (dload.x_end - dload.x_start)
                values.append(
                    (
                        pi + at * axis - peak_direction * (offset + full_len * peak + 0.3 * gap),
                        format_line_load(
                            self._signed_along(ends[0], peak_end),
                            self._signed_along(ends[1], peak_end),
                            units,
                        ),
                    )
                )

        if uniform_bases:
            batch_points, batch_polylines = uniform_load_glyphs(
                np.asarray(uniform_bases),
                np.asarray(uniform_directions),
                np.asarray(uniform_lengths),
                np.asarray(uniform_axes),
                distributed_stations,
            )
            # Each member contributes stations * 3 shafts/heads and one top line.
            per_member = distributed_stations * 3 + 1
            offset = len(distributed_points)
            distributed_points.extend(batch_points)
            distributed_polylines.extend(
                [[index + offset for index in polyline] for polyline in batch_polylines]
            )
            for color in uniform_colors:
                distributed_colors.extend([color] * per_member)

        self._add_arrow_batch(
            [p for p, _, _, _ in nodal],
            [d for _, d, _, _ in nodal],
            [length for _, _, length, _ in nodal],
            hex_to_rgb(KIND_COLORS["joint"]),
            "loads_nodal",
            colors=[c for _, _, _, c in nodal] if by_pattern else None,
        )
        if distributed_polylines:
            cells: list[int] = []
            for polyline in distributed_polylines:
                cells.append(len(polyline))
                cells.extend(polyline)
            pd = pv.PolyData()
            pd.points = np.asarray(distributed_points, dtype=float)
            pd.lines = np.asarray(cells, dtype=np.int64)
            style: dict[str, Any]
            if by_pattern:
                pd.cell_data["rgb"] = np.asarray(
                    np.round(np.asarray(distributed_colors) * 255), dtype=np.uint8
                )
                style = {"scalars": "rgb", "rgb": True}
            else:
                style = {"color": hex_to_rgb(KIND_COLORS["frame_distributed"])}
            actor = self._plotter.add_mesh(
                pd,
                line_width=2.0,
                pickable=False,
                lighting=False,
                name="loads_element",
                **style,
            )
            self._add_screen_actor(actor)
        self._add_arrow_batch(
            [p for p, _, _, _ in point],
            [d for _, d, _, _ in point],
            [length for _, _, length, _ in point],
            hex_to_rgb(KIND_COLORS["frame_point"]),
            "loads_point",
            colors=[c for _, _, _, c in point] if by_pattern else None,
        )
        if settings.show_shell_loads:
            surface = self._surface_load_arrows(
                project, nodes, elements, scale, patterns=patterns, gap=gap
            )
            self._add_arrow_batch(
                [a.tip for a in surface],
                [a.direction for a in surface],
                [a.length for a in surface],
                hex_to_rgb(KIND_COLORS["shell"]),
                "loads_surface",
                colors=[color_of(a.pattern, "shell") for a in surface] if by_pattern else None,
            )
            for arrow in surface:
                drawn.setdefault(arrow.pattern.id, set()).add("shell")
                if arrow.label and want_values:
                    values.append(
                        (
                            arrow.tip - arrow.direction * arrow.length,
                            format_pressure(arrow.label, units),
                        )
                    )
        if settings.show_load_values and values:
            actor = self._plotter.add_point_labels(
                np.asarray([p for p, _ in values], dtype=float),
                [text for _, text in values],
                font_size=self._settings.label_size_px,
                shape_opacity=0.15,
                shape_color=self._style.label_paper,
                text_color=self._style.label_ink,
                point_color="white",
                point_size=1,
                render_points_as_spheres=False,
                always_visible=True,
                pickable=False,
                name="loads_values",
            )
            self._add_screen_actor(actor)
            self._load_values_actor = actor
        self._load_legend_entries = self._load_legend(patterns, palette, drawn, by_pattern)

    @staticmethod
    def _signed_along(value: np.ndarray, reference: np.ndarray) -> float:
        """The magnitude of ``value``, negative when it points against ``reference``."""
        magnitude = float(np.linalg.norm(value))
        return -magnitude if float(np.dot(value, reference)) < 0.0 else magnitude

    def _load_legend(
        self,
        patterns: list[Any],
        palette: dict[int, str],
        drawn: dict[int, set[str]],
        by_pattern: bool,
    ) -> list[list[str]]:
        """Legend rows ``[text, colour]``: each pattern drawn, or the one chosen.

        A project with a single pattern and no choice made keeps the canvas as
        it was, without a legend.
        """
        if by_pattern:
            rows = [[p.name or f"Pattern {p.id}", palette[p.id]] for p in patterns if p.id in drawn]
            return [["Load patterns", self._style.label_ink], *rows] if rows else []
        if self._settings.load_pattern_id is None or not patterns:
            return []
        pattern = patterns[0]
        return [[f"Load pattern: {pattern.name or f'Pattern {pattern.id}'}", self._style.label_ink]]

    #: Natural coordinates of the arrows drawn on a loaded shell (3 x 3).
    _SURFACE_STATIONS = (-2.0 / 3.0, 0.0, 2.0 / 3.0)

    def _surface_load_arrows(
        self,
        project: Project,
        nodes: dict[int, Any],
        elements: dict[int, Any],
        scale: float,
        *,
        patterns: list[Any] | None = None,
        gap: float = 0.0,
    ) -> list[_SurfaceArrow]:
        """Arrows on the loaded shells, nine per shell and load.

        Each arrow ends on the shell and is as long as the pressure there relative
        to the largest pressure drawn, so a pressure by joint pattern shows its
        variation (a hydrostatic load is a triangle of arrows) and a uniform one a
        field of equal arrows. A sign change flips the arrow. A second load on
        the same shell and side is drawn above the first. The centre arrow of
        each load carries the pressure there as its ``label``.
        """
        loads: list[tuple[Any, int, np.ndarray, np.ndarray, np.ndarray]] = []
        for pattern in project.load_patterns if patterns is None else patterns:
            if not isinstance(pattern, PlainLoadPattern):
                continue
            for load in pattern.surface_loads:
                element = elements.get(load.element_id)
                if element is None or len(element.nodes) != 4:
                    continue
                try:
                    pressures = surface_corner_pressures(project, load)
                    points = np.array([nodes[n].coords for n in element.nodes], dtype=float)
                    if load.direction == "normal":
                        axis = shell_normal(points)
                    else:
                        axis = np.zeros(3)
                        axis["XYZ".index(load.direction)] = 1.0
                except (AreaLoadError, KeyError):
                    continue
                loads.append((pattern, load.element_id, points, pressures, axis))
        peak = max((float(np.max(np.abs(p))) for _, _, _, p, _ in loads), default=0.0)
        if peak <= 0.0:
            return []
        full = 2.0 * scale
        arrows: list[_SurfaceArrow] = []
        stacks: dict[tuple[int, float], float] = {}
        corners = ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))
        for pattern, element_id, points, pressures, axis in loads:
            side = 1.0 if float(np.mean(pressures)) >= 0.0 else -1.0
            tallest = full * float(np.max(np.abs(pressures))) / peak
            offset = stacks.get((element_id, side), 0.0)
            stacks[(element_id, side)] = offset + tallest + gap
            for xi in self._SURFACE_STATIONS:
                for eta in self._SURFACE_STATIONS:
                    n = np.array([0.25 * (1 + a * xi) * (1 + b * eta) for a, b in corners])
                    value = float(n @ pressures)
                    if abs(value) < 1e-9 * peak:
                        continue
                    direction = axis if value > 0 else -axis
                    arrows.append(
                        _SurfaceArrow(
                            tip=n @ points - side * axis * offset,
                            direction=direction,
                            length=full * abs(value) / peak,
                            pattern=pattern,
                            label=abs(value) if xi == 0.0 and eta == 0.0 else 0.0,
                        )
                    )
        return arrows

    def _add_arrow_batch(
        self,
        points: list[np.ndarray],
        directions: list[np.ndarray],
        lengths: list[float],
        color: tuple[float, float, float],
        name: str,
        *,
        colors: list[tuple[float, float, float]] | None = None,
    ) -> None:
        """Draw a family of load arrows as one glyph actor.

        The glyph filter aligns the template's **x axis** with the vector, so the
        template points along +X with its tip at the origin: a copy oriented
        along the load ends on the joint, where the per-arrow version put it, and
        the per-point length scales it. ``colors`` gives each arrow its own
        colour (one per load pattern); without it the family takes ``color``.
        """
        if not points:
            return
        cloud = pv.PolyData(np.asarray(points, dtype=float))
        cloud["vectors"] = np.asarray(directions, dtype=float)
        cloud["length"] = np.asarray(lengths, dtype=float)
        if colors is not None:
            cloud["rgb"] = np.asarray(np.round(np.asarray(colors) * 255), dtype=np.uint8)
        template = pv.Arrow(
            start=(-1.0, 0.0, 0.0),
            direction=(1.0, 0.0, 0.0),
            scale=1.0,
            tip_resolution=8,
            shaft_resolution=8,
        )
        glyphs = cloud.glyph(orient="vectors", scale="length", geom=template)
        style: dict[str, Any] = (
            {"scalars": "rgb", "rgb": True} if colors is not None else {"color": color}
        )
        actor = self._plotter.add_mesh(glyphs, pickable=False, lighting=True, name=name, **style)
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
        if project.ndm == 2:
            # A 2D model is in the X-Z plane: its local axes are OpenSees' own.
            axes2 = frame_local_axes(2, node_i.coords, node_j.coords)
            if axes2 is None:
                return None
            return pi, axis, axes2
        angle = float(getattr(elem, "local_axis_angle", 0.0) or 0.0)
        if angle == 0.0:
            # The common case: compute the same axes frame_local_axes would,
            # without rebuilding the axis and length it already has.
            x = axis / length
            vecxz = (
                np.array([1.0, 0.0, 0.0])
                if abs(float(x[2])) > abs(float(x[0]))
                else np.array([0.0, 0.0, 1.0])
            )
            y = np.cross(vecxz, x)
            y_norm = float(np.linalg.norm(y))
            if y_norm < 1e-12:
                return None
            y /= y_norm
            return pi, axis, (x, y, np.cross(x, y))
        # The same axes the runner emits (including a member's local-axis rotation).
        axes3 = frame_local_axes(
            3,
            node_i.coords,
            node_j.coords,
            angle,
        )
        if axes3 is None:
            return None
        return pi, axis, axes3

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
        """The Color By key, top right: each category the viewport shows, in its colour.

        Plain text lines, right-aligned on the viewport edge, like the load key
        (top left): a VTK legend box has a fixed width, and a long section or
        group name ran past its right edge. Nothing for a single colour.
        """
        if self._settings.color_by == "none":
            return
        shown = set(self._frame_ids_ordered) | set(self._surface_ids_ordered)
        categories = self._categories(project, self._settings.frame_color)
        used = sorted({categories.index[eid] for eid in shown if eid in categories.index})
        if not used:
            return
        entries = [(categories.labels[k], categories.colors[k]) for k in used]
        if len(entries) > LEGEND_MAX_ENTRIES:
            hidden = len(entries) - (LEGEND_MAX_ENTRIES - 1)
            entries = [*entries[: LEGEND_MAX_ENTRIES - 1], (f"… {hidden} more", "#808080")]
        for row, (label, color) in enumerate(entries):
            actor = self._plotter.add_text(
                label,
                position=(0.99, 0.95 - row * self._LOAD_LEGEND_ROW),
                viewport=True,
                font_size=max(8, self._settings.label_size_px),
                color=legible(color, self._style.background),
                name=f"color_legend_{row}",
            )
            text = actor.GetTextProperty()
            text.SetBold(True)
            text.SetJustificationToRight()
            self._aux_actors.append(actor)
            if row == 0:
                self._legend_actor = actor

    #: Row height of the load legend, as a fraction of the viewport height.
    _LOAD_LEGEND_ROW = 0.045

    def _build_load_legend(self, project: Project) -> None:
        """The load key, top left: a heading, then each pattern name in its colour.

        Plain text lines rather than a VTK legend box, whose text runs past its
        right edge, and out of the way of the Color By key (top right).
        """
        if not self._settings.show_loads:
            return
        for row, (label, color) in enumerate(self._load_legend_entries[:LEGEND_MAX_ENTRIES]):
            actor = self._plotter.add_text(
                label,
                position=(0.01, 0.95 - row * self._LOAD_LEGEND_ROW),
                viewport=True,
                font_size=max(8, self._settings.label_size_px),
                color=legible(color, self._style.background),
                name=f"loads_legend_{row}",
            )
            actor.GetTextProperty().SetBold(True)
            self._aux_actors.append(actor)

    def _teardown_all(self) -> None:
        self.clear_measure_preview()
        self._clear_label_actors()
        # The Color By key's lines are auxiliary actors, removed with them below.
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
            shape_color=self._style.label_paper,
            text_color=self._style.label_ink,
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
            shape_color=self._style.label_paper,
            text_color=self._style.label_ink,
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


def _rotation_to(d: np.ndarray) -> np.ndarray:
    """4 x 4 rotation taking +Z onto the unit vector ``d`` (Rodrigues)."""
    z = np.array([0.0, 0.0, 1.0])
    d = d / float(np.linalg.norm(d))
    v = np.cross(z, d)
    c = float(z @ d)
    matrix = np.eye(4)
    if float(np.linalg.norm(v)) < 1e-12:
        if c < 0:
            matrix[:3, :3] = np.diag([1.0, -1.0, -1.0])  # half a turn about X
        return matrix
    k = np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])
    matrix[:3, :3] = np.eye(3) + k + k @ k / (1.0 + c)
    return matrix
