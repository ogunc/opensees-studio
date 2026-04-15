"""Project → PyVista renderer (high-performance, single-actor strategy).

- Nodes:    one ``pv.PolyData`` of N points + sphere glyph filter → one actor
- Frames:   one ``pv.PolyData`` of N line cells → one actor
- Selection: per-cell scalar (0=normal, 1=selected) + 2-color LUT;
  toggling rewrites the scalar array — no actor rebuild.

Mode-aware: MODEL / DEFORMED / MODAL change only the points array.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

import numpy as np
import pyvista as pv

from opensees_studio.core import (
    CorotTrussElement,
    DispBeamColumn,
    ElasticBeamColumn,
    ForceBeamColumn,
    NodalLoad,
    PlainLoadPattern,
    Project,
    TrussElement,
    ZeroLengthElement,
)
from opensees_studio.views.canvas3d.style import RenderStyle


class RendererMode(enum.Enum):
    MODEL = "model"
    DEFORMED = "deformed"
    MODAL = "modal"


_FRAME_CLASSES = (ElasticBeamColumn, DispBeamColumn, ForceBeamColumn,
                  TrussElement, CorotTrussElement, ZeroLengthElement)


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


def _dof_indices(ndf: int) -> tuple[int, ...]:
    if ndf == 6:
        return (0, 1, 2, 3, 4, 5)
    if ndf == 3:
        return (0, 1, 5)
    if ndf == 2:
        return (0, 1)
    return tuple(range(ndf))


@dataclass
class DeformationSource:
    """Per-node displacement vectors used to draw deformed shapes."""

    displacements: np.ndarray         # shape (n_nodes, 3) — x, y, z components
    node_id_to_row: dict[int, int]
    scale: float = 1.0

    def shifted(self, original_points: np.ndarray, node_ids: list[int]) -> np.ndarray:
        out = original_points.copy()
        for i, nid in enumerate(node_ids):
            row = self.node_id_to_row.get(nid)
            if row is not None:
                out[i] += self.scale * self.displacements[row]
        return out


class ModelRenderer:
    """Glyphed-PolyData renderer with mode-aware deformation support."""

    @staticmethod
    def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
        r, g, b = (int(round(x * 255)) for x in rgb)
        return f"#{r:02x}{g:02x}{b:02x}"

    _NODE_LUT = ["#d9d9d9", "#00ffff"]    # gray normal, cyan selected
    _FRAME_LUT = ["#338cd9", "#00ffff"]   # blue normal, cyan selected

    def __init__(self, plotter: Any, style: RenderStyle | None = None) -> None:
        self._plotter = plotter
        self._style = style or RenderStyle()
        self._project: Project | None = None
        self._mode = RendererMode.MODEL
        self._deformation: DeformationSource | None = None

        self._node_pd: pv.PolyData | None = None
        self._node_glyph: pv.PolyData | None = None
        self._node_actor: Any = None
        self._node_ids_ordered: list[int] = []
        self._node_id_to_row: dict[int, int] = {}
        self._node_original_points: np.ndarray | None = None

        self._frame_pd: pv.PolyData | None = None
        self._frame_actor: Any = None
        self._frame_ids_ordered: list[int] = []
        self._frame_id_to_row: dict[int, int] = {}

        self._aux_actors: list[Any] = []

        try:
            self._plotter.enable_anti_aliasing("ssaa")
        except Exception:
            pass

    # ── public API ───────────────────────────────────────────────────
    def render(self, project: Project | None) -> None:
        """Full render: rebuild everything. Call when topology changes."""
        self._project = project
        self._teardown_all()
        if project is None or not project.nodes:
            return
        self._build_node_polydata(project)
        self._build_frame_polydata(project)
        self._build_supports(project)
        self._build_loads(project)
        self._apply_mode_to_points()

    def update_selection(self, node_ids: frozenset[int],
                         element_ids: frozenset[int]) -> None:
        """In-place selection update — no full re-render."""
        if self._node_pd is not None and self._node_ids_ordered:
            states = np.zeros(len(self._node_ids_ordered), dtype=np.int8)
            for nid in node_ids:
                row = self._node_id_to_row.get(nid)
                if row is not None:
                    states[row] = 1
            self._node_pd["_oss_state"] = states
            # Re-glyph so the LUT-coloured sphere instances refresh.
            self._reglyph_nodes()

        if self._frame_pd is not None and self._frame_ids_ordered:
            states = np.zeros(len(self._frame_ids_ordered), dtype=np.int8)
            for eid in element_ids:
                row = self._frame_id_to_row.get(eid)
                if row is not None:
                    states[row] = 1
            self._frame_pd.cell_data["_oss_state"] = states
            self._frame_pd.Modified()

    def set_mode(self, mode: RendererMode,
                 deformation: DeformationSource | None = None) -> None:
        self._mode = mode
        self._deformation = deformation
        self._apply_mode_to_points()

    # ── builders ────────────────────────────────────────────────────
    def _build_node_polydata(self, project: Project) -> None:
        ids = [n.id for n in project.nodes]
        coords = np.array([n.coords for n in project.nodes], dtype=float)
        self._node_ids_ordered = ids
        self._node_id_to_row = {nid: i for i, nid in enumerate(ids)}
        self._node_original_points = coords.copy()

        pd = pv.PolyData(coords)
        pd["_oss_id"] = np.array(ids, dtype=np.int64)
        pd["_oss_kind"] = np.array(["node"] * len(ids), dtype=object)
        pd["_oss_state"] = np.zeros(len(ids), dtype=np.int8)
        self._node_pd = pd
        self._reglyph_nodes()

    def _reglyph_nodes(self) -> None:
        """Rebuild the glyph polydata after points or state change."""
        if self._node_pd is None or self._node_original_points is None:
            return
        radius = self._auto_node_radius(np.asarray(self._node_pd.points))
        sphere = pv.Sphere(radius=radius, theta_resolution=8, phi_resolution=8)
        glyph = self._node_pd.glyph(geom=sphere, scale=False, orient=False)
        if self._node_actor is not None:
            try:
                self._plotter.remove_actor(self._node_actor, render=False)
            except Exception:
                pass
        self._node_glyph = glyph
        self._node_actor = self._plotter.add_mesh(
            glyph,
            scalars="_oss_state",
            cmap=self._NODE_LUT,
            clim=[0, 1],
            show_scalar_bar=False,
            pickable=True,
            lighting=True,
        )

    def _build_frame_polydata(self, project: Project) -> None:
        frames = [el for el in project.elements if isinstance(el, _FRAME_CLASSES)]
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
        pd.cell_data["_oss_state"] = np.zeros(len(ids), dtype=np.int8)

        self._frame_pd = pd
        self._frame_ids_ordered = ids
        self._frame_id_to_row = {eid: i for i, eid in enumerate(ids)}
        self._frame_actor = self._plotter.add_mesh(
            pd,
            scalars="_oss_state",
            cmap=self._FRAME_LUT,
            clim=[0, 1],
            show_scalar_bar=False,
            line_width=3.0,
            pickable=True,
            lighting=False,
        )

    def _build_supports(self, project: Project) -> None:
        if not project.nodes or self._node_original_points is None:
            return
        ndf = project.ndf
        dof_idx = _dof_indices(ndf)
        size = max(self._diag_of_points(self._node_original_points) * 0.015, 1e-6)
        support_color = (1.0, 0.5, 0.1)
        for node in project.nodes:
            if not any(node.restraint[i] for i in dof_idx):
                continue
            kind = _classify_support(node.restraint, dof_idx)
            geom = self._support_glyph(kind, size)
            geom.translate(node.coords, inplace=True)
            actor = self._plotter.add_mesh(geom, color=support_color,
                                           pickable=False, lighting=True)
            self._aux_actors.append(actor)

    def _build_loads(self, project: Project) -> None:
        if not project.load_patterns or self._node_original_points is None:
            return
        scale = max(self._diag_of_points(self._node_original_points) * 0.05, 1e-6)
        load_color = (0.2, 0.85, 0.2)
        for pattern in project.load_patterns:
            if not isinstance(pattern, PlainLoadPattern):
                continue
            for nload in pattern.nodal_loads:
                if not isinstance(nload, NodalLoad):
                    continue
                node = next((n for n in project.nodes if n.id == nload.node_id), None)
                if node is None:
                    continue
                f = np.asarray(nload.forces[:3], dtype=float)
                mag = np.linalg.norm(f)
                if mag < 1e-12:
                    continue
                direction = f / mag
                arrow = pv.Arrow(
                    start=tuple(np.array(node.coords) - direction * scale),
                    direction=tuple(direction),
                    scale=scale,
                )
                actor = self._plotter.add_mesh(arrow, color=load_color,
                                               pickable=False, lighting=True)
                self._aux_actors.append(actor)

    # ── mode update ─────────────────────────────────────────────────
    def _apply_mode_to_points(self) -> None:
        if (self._node_pd is None or self._node_original_points is None
                or self._project is None):
            return
        if self._mode == RendererMode.MODEL or self._deformation is None:
            new_pts = self._node_original_points
        else:
            new_pts = self._deformation.shifted(
                self._node_original_points, self._node_ids_ordered
            )
        self._node_pd.points = new_pts
        self._reglyph_nodes()
        if self._frame_pd is not None:
            self._frame_pd.points = new_pts
            self._frame_pd.Modified()

    # ── helpers ─────────────────────────────────────────────────────
    def _teardown_all(self) -> None:
        for a in (self._node_actor, self._frame_actor):
            if a is not None:
                try:
                    self._plotter.remove_actor(a, render=False)
                except Exception:
                    pass
        for a in self._aux_actors:
            try:
                self._plotter.remove_actor(a, render=False)
            except Exception:
                pass
        self._node_actor = None
        self._frame_actor = None
        self._aux_actors.clear()
        self._node_pd = None
        self._node_glyph = None
        self._frame_pd = None
        self._node_ids_ordered = []
        self._node_id_to_row = {}
        self._frame_ids_ordered = []
        self._frame_id_to_row = {}
        self._node_original_points = None
        self._deformation = None
        self._mode = RendererMode.MODEL

    @staticmethod
    def _diag_of_points(pts: np.ndarray | None) -> float:
        if pts is None or len(pts) == 0:
            return 1.0
        mn, mx = pts.min(axis=0), pts.max(axis=0)
        d = float(np.linalg.norm(mx - mn))
        return d if d > 0 else 1.0

    def _auto_node_radius(self, pts: np.ndarray) -> float:
        return max(self._diag_of_points(pts) * 0.008, 1e-6)

    @staticmethod
    def _support_glyph(kind: str, size: float) -> pv.PolyData:
        if kind == "fix":
            return pv.Cube(x_length=size * 1.5, y_length=size * 1.5, z_length=size * 0.4)
        if kind == "pin":
            return pv.Cone(direction=(0, 0, -1), height=size * 1.5, radius=size,
                           resolution=8)
        if kind == "roller":
            return pv.Cylinder(direction=(1, 0, 0), height=size, radius=size * 0.5,
                               resolution=8)
        return pv.Cube(x_length=size, y_length=size, z_length=size)
