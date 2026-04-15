"""Project → PyVista renderer.

A pure-rendering class: given a ``pyvista.Plotter`` and a ``Project``,
paint the model. No Qt imports here; the caller (``ModelCanvas``)
wires picking callbacks to selection signals.

Picking metadata is stored on each mesh as ``cell_data['_oss_id']``
plus ``'_oss_kind']`` ("node" or "element"). The picking callback
reads these to map back to entity ids.

Auto-scaling: glyph sizes are proportional to the model's bounding-box
diagonal so a 1 mm specimen and a 100 m bridge both render legibly.
"""

from __future__ import annotations

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


# ──────────────────────────── helpers ────────────────────────────
def _tag_mesh(mesh: pv.DataSet, kind: str, entity_id: int) -> pv.DataSet:
    """Attach picking metadata as cell data."""
    n = mesh.n_cells if mesh.n_cells > 0 else 1
    mesh.cell_data["_oss_id"] = np.full(n, entity_id, dtype=np.int64)
    mesh.cell_data["_oss_kind"] = np.full(n, kind, dtype=object)
    return mesh


def _classify_support(restraint: tuple[bool, ...], dof_idx: tuple[int, ...]) -> str:
    """Return 'fix' | 'pin' | 'roller' | 'custom' from the restraint pattern.

    Heuristics (applied to the DOFs the model actually exposes):
        - all DOFs fixed                                 → 'fix'
        - all translational DOFs fixed, no rotation      → 'pin'
        - exactly one DOF fixed                           → 'roller'
        - anything else                                   → 'custom'

    Translation vs. rotation is identified by the *index* into the
    canonical 6-DOF storage: indices 0–2 are translations (Ux, Uy, Uz),
    3–5 are rotations (Rx, Ry, Rz). The ``dof_idx`` argument comes from
    :func:`_dof_indices` and tells us which of those the model uses.
    """
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


# ──────────────────────────── renderer ────────────────────────────
class ModelRenderer:
    """Render a Project into a PyVista plotter."""

    def __init__(self, plotter: Any, style: RenderStyle | None = None) -> None:
        self._plotter = plotter
        self._style = style or RenderStyle()
        self._actors: list[Any] = []           # everything we add — easy to clear
        self._project: Project | None = None
        self._scale: float = 1.0
        self._dof_idx: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
        self._selected_nodes: frozenset[int] = frozenset()
        self._selected_elements: frozenset[int] = frozenset()

    # ── public API ───────────────────────────────────────────────────
    @property
    def project(self) -> Project | None:
        return self._project

    def render(self, project: Project | None) -> None:
        """(Re)paint the model. Pass ``None`` to clear."""
        self._clear_model_actors()
        self._project = project
        if project is None or not project.nodes:
            self._plotter.render()
            return

        self._dof_idx = self._dof_indices(project.ndm, project.ndf)
        self._scale = self._compute_bbox_diag(project)

        self._render_elements(project)
        self._render_nodes(project)
        self._render_supports(project)
        self._render_loads(project)
        self._render_masses(project)
        self._plotter.render()

    def update_selection(self, nodes: frozenset[int], elements: frozenset[int]) -> None:
        """Re-paint with the given highlight set."""
        self._selected_nodes = nodes
        self._selected_elements = elements
        if self._project is not None:
            self.render(self._project)

    # ── internals ────────────────────────────────────────────────────
    def _clear_model_actors(self) -> None:
        for actor in self._actors:
            try:
                self._plotter.remove_actor(actor)
            except Exception:
                pass
        self._actors.clear()

    @staticmethod
    def _dof_indices(ndm: int, ndf: int) -> tuple[int, ...]:
        table = {
            (2, 2): (0, 1),
            (2, 3): (0, 1, 5),
            (3, 3): (0, 1, 2),
            (3, 6): (0, 1, 2, 3, 4, 5),
        }
        return table.get((ndm, ndf), (0, 1, 2, 3, 4, 5))

    @staticmethod
    def _compute_bbox_diag(project: Project) -> float:
        coords = np.array([n.coords for n in project.nodes], dtype=float)
        extent = coords.max(axis=0) - coords.min(axis=0)
        return float(max(np.linalg.norm(extent), 1.0))

    # ── element rendering ────────────────────────────────────────────
    def _render_elements(self, project: Project) -> None:
        node_lookup = {n.id: np.array(n.coords, dtype=float) for n in project.nodes}
        tube_radius = max(self._scale * self._style.tube_relative_radius,
                          self._style.tube_min_radius)

        for el in project.elements:
            color, radius = self._element_appearance(el, tube_radius)
            if isinstance(el, ZeroLengthElement):
                # Draw at midpoint as a small marker.
                p0 = node_lookup[el.nodes[0]]
                marker = pv.Sphere(radius=tube_radius * 1.5, center=p0)
                marker = _tag_mesh(marker, "element", el.id)
                actor = self._plotter.add_mesh(
                    marker, color=color, pickable=True, name=f"_oss_elem_{el.id}",
                )
                self._actors.append(actor)
                continue

            p0 = node_lookup[el.nodes[0]]
            p1 = node_lookup[el.nodes[1]]
            line = pv.Line(p0, p1)
            tube = line.tube(radius=radius)
            tube = _tag_mesh(tube, "element", el.id)
            actor = self._plotter.add_mesh(
                tube, color=color, pickable=True,
                smooth_shading=True, name=f"_oss_elem_{el.id}",
            )
            self._actors.append(actor)

    def _element_appearance(self, el: Any, base_radius: float) -> tuple[str, float]:
        s = self._style
        selected = el.id in self._selected_elements
        radius = base_radius * (s.selection_thickness_factor if selected else 1.0)

        if selected:
            color = s.selected_color
        elif isinstance(el, (TrussElement, CorotTrussElement)):
            color = s.truss_color
        elif isinstance(el, (ElasticBeamColumn, ForceBeamColumn, DispBeamColumn)):
            color = s.frame_color
        elif isinstance(el, ZeroLengthElement):
            color = s.zerolength_color
        else:
            color = s.frame_color
        return color, radius

    # ── node rendering ───────────────────────────────────────────────
    def _render_nodes(self, project: Project) -> None:
        s = self._style
        radius = max(self._scale * s.node_relative_radius, s.node_min_radius)

        # Add each node as an individually-tagged sphere so picking → id is direct.
        # For very large models we'd switch to glyphs + cell_data; a TODO in Phase 7.
        for node in project.nodes:
            selected = node.id in self._selected_nodes
            color = s.node_selected_color if selected else s.node_color
            r = radius * (s.selection_thickness_factor if selected else 1.0)
            sphere = pv.Sphere(radius=r, center=np.array(node.coords))
            sphere = _tag_mesh(sphere, "node", node.id)
            actor = self._plotter.add_mesh(
                sphere, color=color, pickable=True,
                smooth_shading=True, name=f"_oss_node_{node.id}",
            )
            self._actors.append(actor)

    # ── supports ─────────────────────────────────────────────────────
    def _render_supports(self, project: Project) -> None:
        s = self._style
        size = max(self._scale * s.support_relative_size, s.support_min_size)

        for node in project.nodes:
            if not node.is_restrained:
                continue
            kind = _classify_support(node.restraint, self._dof_idx)
            center = np.array(node.coords) - np.array([0, 0, size * 0.6])
            if kind == "fix":
                glyph = pv.Cube(center=center, x_length=size, y_length=size, z_length=size)
                color = s.fix_color
            elif kind == "pin":
                glyph = pv.Cone(center=center, direction=(0, 0, 1),
                                height=size * 1.4, radius=size * 0.7, resolution=24)
                color = s.pin_color
            elif kind == "roller":
                glyph = pv.Cylinder(center=center, direction=(1, 0, 0),
                                    radius=size * 0.4, height=size * 1.2, resolution=24)
                color = s.roller_color
            else:
                glyph = pv.Cube(center=center,
                                x_length=size * 0.7, y_length=size * 0.7, z_length=size * 0.7)
                color = s.custom_support_color

            actor = self._plotter.add_mesh(glyph, color=color, pickable=False,
                                           name=f"_oss_sup_{node.id}")
            self._actors.append(actor)

    # ── loads ────────────────────────────────────────────────────────
    def _render_loads(self, project: Project) -> None:
        s = self._style
        max_len = max(self._scale * s.load_relative_length, s.load_min_length)

        # Aggregate Plain pattern nodal loads only (UniformExcitation is global).
        loads_by_node: dict[int, np.ndarray] = {}
        for pat in project.load_patterns:
            if not isinstance(pat, PlainLoadPattern):
                continue
            for nl in pat.nodal_loads:
                forces = np.array(nl.forces[:3], dtype=float)  # plot translation forces
                loads_by_node[nl.node_id] = loads_by_node.get(nl.node_id, np.zeros(3)) + forces

        if not loads_by_node:
            return

        max_mag = max(np.linalg.norm(v) for v in loads_by_node.values()) or 1.0
        node_lookup = {n.id: np.array(n.coords, dtype=float) for n in project.nodes}

        for node_id, force in loads_by_node.items():
            mag = float(np.linalg.norm(force))
            if mag < 1e-12:
                continue
            length = max_len * (mag / max_mag)
            direction = force / mag
            tip = node_lookup[node_id]
            tail = tip - direction * length      # arrow points TOWARD the node
            arrow = pv.Arrow(start=tail, direction=direction, scale=length)
            actor = self._plotter.add_mesh(arrow, color=s.load_color, pickable=False,
                                           name=f"_oss_load_{node_id}")
            self._actors.append(actor)

    # ── masses ───────────────────────────────────────────────────────
    def _render_masses(self, project: Project) -> None:
        s = self._style
        radius = max(self._scale * s.node_relative_radius, s.node_min_radius) * 1.4
        for node in project.nodes:
            if not any(node.mass):
                continue
            ring = pv.Disc(center=np.array(node.coords), inner=radius, outer=radius * 1.4,
                           normal=(0, 0, 1), r_res=24, c_res=24)
            actor = self._plotter.add_mesh(ring, color=s.mass_color, pickable=False,
                                           name=f"_oss_mass_{node.id}")
            self._actors.append(actor)
