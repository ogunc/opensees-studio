"""Force diagram overlay renderer.

Draws N/V/M diagrams as colored polygon ribbons attached perpendicular
to each frame element. This is a separate concern from the main
:class:`ModelRenderer`: diagrams are an overlay layer that gets shown
on top of the existing model rendering, not a replacement for it.

Convention:
- Axial (N) diagrams are drawn along the element's axis as a thin tube
  whose radius scales with |N|. Sign is shown by color
  (red = compression, blue = tension).
- Shear/moment diagrams are drawn perpendicular to the element. The
  perpendicular direction depends on the component:
  * V2 / M3 → drawn in local-y direction (in-plane for 2D models).
  * V3 / M2 → drawn in local-z direction (out-of-plane for 2D).
  * T → drawn around the axis as a ribbon (visualised as V2-style for now).
- The diagram polygon goes from the element line out to the value-scaled
  perpendicular offset and back, forming a filled triangle/trapezoid per
  element. Linear interpolation between end values (good enough for
  elastic beams without distributed loads).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pyvista as pv

from opensees_studio.core import Project
from opensees_studio.services.element_forces import DiagramData, ForceComponent

_LOG = logging.getLogger("opensees_studio.diagram")

# Components that draw perpendicular to the element axis vs along it.
_PERPENDICULAR = {ForceComponent.V2, ForceComponent.V3,
                  ForceComponent.M2, ForceComponent.M3, ForceComponent.T}

# Which local axis the value is plotted along (2 = local y, 3 = local z).
_LOCAL_AXIS = {
    ForceComponent.V2: 2, ForceComponent.M3: 2,
    ForceComponent.V3: 3, ForceComponent.M2: 3,
    ForceComponent.T:  2,
}


class DiagramRenderer:
    """Renders a single :class:`DiagramData` overlay on a PyVista plotter.

    Lifecycle:
    - ``render(project, data, scale)`` paints the diagram. Replaces any
      previously rendered overlay.
    - ``clear()`` removes the overlay.
    """

    def __init__(self, plotter: Any) -> None:
        self._plotter = plotter
        self._actor: Any = None
        self._label_actor: Any = None

    # ── public ──────────────────────────────────────────────────────
    def render(self, project: Project, data: DiagramData, scale: float) -> None:
        """Build and display the diagram for ``data`` at ``scale``."""
        self.clear()
        if data.element_ids.size == 0:
            return
        if data.abs_max <= 0.0:
            # All values are zero → no diagram to draw. This is normal —
            # e.g. asking for "torsion" on a planar bending model. Log
            # a hint so the user understands the empty viewport.
            _LOG.info("All '%s' values are zero for this analysis step "
                      "— nothing to draw.", data.component.name)
            return

        node_pos = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
        elem_lookup = {e.id: e for e in project.elements}

        is_perpendicular = data.component in _PERPENDICULAR
        axis_id = _LOCAL_AXIS.get(data.component, 2)

        polys: list[np.ndarray] = []         # vertex arrays for each polygon
        scalars: list[float] = []            # one value per polygon (avg of end values)
        for k, eid in enumerate(data.element_ids):
            elem = elem_lookup.get(int(eid))
            if elem is None:
                continue
            n_i, n_j = elem.nodes
            pi, pj = node_pos.get(n_i), node_pos.get(n_j)
            if pi is None or pj is None:
                continue
            v_i = data.values_i[k] * scale
            v_j = data.values_j[k] * scale

            if is_perpendicular:
                perp = self._local_perp(pi, pj, axis_id)
                if perp is None:
                    continue
                # Trapezoid: i, j, j+perp*v_j, i+perp*v_i
                quad = np.vstack([pi, pj, pj + perp * v_j, pi + perp * v_i])
                polys.append(quad)
                scalars.append(0.5 * (data.values_i[k] + data.values_j[k]))
            else:
                # Axial: thin perpendicular rectangle (constant width visualises
                # sign via color); use local-y axis for the perpendicular.
                perp = self._local_perp(pi, pj, 2)
                if perp is None:
                    continue
                width = abs(v_i) * 0.5     # half-width fall-off
                if width == 0.0:
                    width = abs(v_j) * 0.5
                if width == 0.0:
                    continue
                quad = np.vstack([
                    pi - perp * width, pj - perp * width,
                    pj + perp * width, pi + perp * width,
                ])
                polys.append(quad)
                scalars.append(0.5 * (data.values_i[k] + data.values_j[k]))

        if not polys:
            return

        # Assemble all polygons into a single PolyData (one quad per element).
        all_pts = np.vstack(polys)
        # vtkPolyData face encoding: [n_pts_in_face, p0, p1, p2, p3, ...]
        faces = []
        offset = 0
        for q in polys:
            n = len(q)
            faces.append(n)
            faces.extend(range(offset, offset + n))
            offset += n
        faces_arr = np.asarray(faces, dtype=np.int64)
        mesh = pv.PolyData(all_pts, faces_arr)
        mesh.cell_data["value"] = np.asarray(scalars, dtype=float)

        # Symmetric color range so zero stays at the colormap mid-point.
        vmax = float(np.max(np.abs(scalars))) or 1.0
        # Defensive: accept either ForceComponent enum or its name string.
        comp_label = data.component.value if hasattr(data.component, "value") else str(data.component)
        self._actor = self._plotter.add_mesh(
            mesh,
            scalars="value",
            cmap="coolwarm",
            clim=(-vmax, vmax),
            show_scalar_bar=True,
            scalar_bar_args={"title": comp_label, "n_labels": 5},
            opacity=0.85,
            edge_color="#222222",
            show_edges=True,
            line_width=0.5,
            pickable=False,
            render=False,
        )

        # ── Numerical labels at the global min and max element ends. ──
        self._label_actor = self._add_value_labels(project, data, scale)

    def _add_value_labels(self, project: Project, data: DiagramData,
                          scale: float) -> Any:
        """Annotate the diagram's extreme ends with their numerical values.

        Avoids visual clutter by labelling only the two ends carrying the
        global maximum and minimum values. Skips if there's no
        non-zero value to highlight.
        """
        # Pair each end value with the world-space label position
        # (element end + perpendicular offset, if applicable).
        node_pos = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
        elem_lookup = {e.id: e for e in project.elements}
        is_perp = data.component in _PERPENDICULAR
        axis_id = _LOCAL_AXIS.get(data.component, 2)

        candidates: list[tuple[float, np.ndarray]] = []  # (value, position)
        for k, eid in enumerate(data.element_ids):
            elem = elem_lookup.get(int(eid))
            if elem is None:
                continue
            n_i, n_j = elem.nodes
            pi, pj = node_pos.get(n_i), node_pos.get(n_j)
            if pi is None or pj is None:
                continue
            for end_pt, val in ((pi, data.values_i[k]), (pj, data.values_j[k])):
                if is_perp:
                    perp = self._local_perp(pi, pj, axis_id)
                    label_pos = end_pt + (perp * val * scale if perp is not None else 0)
                else:
                    label_pos = end_pt
                candidates.append((float(val), np.asarray(label_pos)))

        if not candidates:
            return None

        # Pick the global max and min by value.
        vals = np.array([c[0] for c in candidates])
        idx_max = int(np.argmax(vals))
        idx_min = int(np.argmin(vals))
        # If max == min (all equal) just one label; skip the dup.
        unique_indices = [idx_max] if idx_max == idx_min else [idx_max, idx_min]
        positions = np.vstack([candidates[i][1] for i in unique_indices])
        labels = [self._format_value(candidates[i][0]) for i in unique_indices]

        try:
            return self._plotter.add_point_labels(
                positions, labels,
                font_size=14,
                point_size=0,            # don't draw the underlying points
                shape=None,
                always_visible=True,
                pickable=False,
                render=False,
            )
        except Exception:
            return None

    @staticmethod
    def _format_value(v: float) -> str:
        """Engineering-style formatting: 1.23e3 N → '1.23k', 4.5e6 → '4.50M'."""
        absv = abs(v)
        if absv == 0.0:
            return "0"
        if absv >= 1e9:
            return f"{v / 1e9:.2f}G"
        if absv >= 1e6:
            return f"{v / 1e6:.2f}M"
        if absv >= 1e3:
            return f"{v / 1e3:.2f}k"
        if absv >= 1.0:
            return f"{v:.2f}"
        return f"{v:.2e}"

    def clear(self) -> None:
        if self._actor is not None:
            try:
                self._plotter.remove_actor(self._actor, render=False)
                self._plotter.remove_scalar_bar()
            except Exception:
                pass
            self._actor = None
        if self._label_actor is not None:
            try:
                self._plotter.remove_actor(self._label_actor, render=False)
            except Exception:
                pass
            self._label_actor = None

    # ── helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _local_perp(pi: np.ndarray, pj: np.ndarray, axis: int) -> np.ndarray | None:
        """Unit vector perpendicular to the element axis.

        ``axis`` selects which local perpendicular axis (2 = local y, 3 = local z).
        For local y we use the cross product (axis × global Z) — falls back
        to (axis × global Y) if the element is vertical. For local z we
        cross local-x with local-y.
        """
        x_local = pj - pi
        n = float(np.linalg.norm(x_local))
        if n == 0.0:
            return None
        x_local = x_local / n
        # Pick a vertical-ish reference vector for local y.
        z_global = np.array([0.0, 0.0, 1.0])
        y_local = np.cross(z_global, x_local)
        if float(np.linalg.norm(y_local)) < 1e-6:
            # Element is vertical; use global Y for the cross product instead.
            y_local = np.cross(np.array([0.0, 1.0, 0.0]), x_local)
        y_local = y_local / float(np.linalg.norm(y_local))
        if axis == 2:
            return y_local
        # axis == 3: local z = x × y (right-handed)
        z_local = np.cross(x_local, y_local)
        return z_local / float(np.linalg.norm(z_local))
