"""Paint a scalar field on the shell faces, with a colour bar.

A separate overlay layer, like the force diagram: the model keeps its own
actor and this one is added on top (and removed when the dock closes). Two
things can be drawn:

- the **field**, as node-averaged scalars on the face mesh, warped by the
  displacements when the field *is* a displacement (that is what makes a
  deformation contour readable) or by an explicit scale;
- the **principal direction**, as one line segment per shell element, oriented
  along the major principal axis of that element and coloured by the same
  scalar range. Only the principal fields carry a direction, and only when the
  caller asks for it.

The numbers come from :mod:`opensees_studio.services.shell_fields`; this module
only decides how they look.
"""

from __future__ import annotations

import contextlib
from typing import Any

import numpy as np
import pyvista as pv

from opensees_studio.core.shell_results import principal_angle
from opensees_studio.core.units import UnitSystem
from opensees_studio.services.shell_fields import (
    element_values,
    field_by_key,
    nodal_values,
    shell_elements,
    warped_positions,
)

#: Diverging map: a moment or a membrane force is read by its sign.
CMAP = "coolwarm"

#: Direction glyphs: half-length as a fraction of the element's own size, and
#: the share of the field range a segment of full length stands for.
GLYPH_LENGTH_FRACTION = 0.35


class ShellContourRenderer:
    """Draws one shell contour (and its principal directions) on a plotter."""

    def __init__(self, plotter: Any) -> None:
        self._plotter = plotter
        self._actor: Any = None
        self._glyph_actor: Any = None
        self.range: tuple[float, float] | None = None
        """The colour limits actually used, or ``None`` when nothing was drawn."""
        self.points: int = 0
        self.cells: int = 0

    # ── public ──────────────────────────────────────────────────────
    def render(
        self,
        project: Any,
        results: Any,
        field_key: str,
        *,
        step: int = -1,
        scale: float = 0.0,
        show_directions: bool = False,
        units: UnitSystem | None = None,
    ) -> None:
        """Colour the shell faces by ``field_key`` and remember the range used.

        ``scale`` warps the mesh by the displacements; the caller passes the
        displacement scale for a deformation field and 0 for an undeformed
        force contour. Nothing is drawn — and :attr:`range` stays ``None`` —
        when the model has no shell with a value for that field, which is the
        case for a frame model and for a result object whose elements have no
        section response.
        """
        self.clear()
        field = field_by_key(field_key)
        values = nodal_values(project, results, field_key, step)
        # One value per element too: the glyphs are drawn per element while the
        # nodal map is keyed by node, so the two must not be confused.
        per_element = element_values(project, results, field_key, step)
        elements = [el for el in shell_elements(project) if el.id in per_element]
        if not values or not elements:
            return

        positions = warped_positions(project, results, scale, step)
        rows: dict[int, int] = {}
        coords: list[tuple[float, float, float]] = []
        cells: list[int] = []
        drawn = 0
        for element in elements:
            indices: list[int] = []
            for node_id in element.nodes:
                if node_id not in values or node_id not in positions:
                    indices = []
                    break
                if node_id not in rows:
                    rows[node_id] = len(coords)
                    coords.append(positions[node_id])
                indices.append(rows[node_id])
            if len(indices) < 3:
                continue
            cells.extend([len(indices), *indices])
            drawn += 1

        if not cells:
            return

        mesh = pv.PolyData()
        mesh.points = np.asarray(coords, dtype=float)
        mesh.faces = np.asarray(cells, dtype=np.int64)
        mesh.point_data["value"] = np.asarray([values[nid] for nid in rows], dtype=float)

        values_array = np.asarray(list(values.values()), dtype=float)
        self.range = _limits(values_array)
        label = field.label
        unit = field.unit_label(units) if units is not None else ""
        title = f"{label} [{unit}]" if unit else label

        self._actor = self._plotter.add_mesh(
            mesh,
            scalars="value",
            cmap=CMAP,
            clim=self.range,
            show_scalar_bar=True,
            scalar_bar_args={"title": title, "n_labels": 5},
            show_edges=True,
            edge_color="#333333",
            line_width=0.5,
            lighting=False,
            pickable=False,
            render=False,
        )
        self.points = len(coords)
        self.cells = drawn

        if show_directions and field.direction:
            self._glyph_actor = self._draw_directions(
                project,
                results,
                field_key,
                step,
                positions,
                per_element,
                self.range,
            )

    def clear(self) -> None:
        for actor in (self._actor, self._glyph_actor):
            if actor is not None:
                with contextlib.suppress(Exception):
                    self._plotter.remove_actor(actor, render=False)
        if self._actor is not None:
            with contextlib.suppress(Exception):
                self._plotter.remove_scalar_bar()
        self._actor = None
        self._glyph_actor = None
        self.range = None
        self.points = 0
        self.cells = 0

    @property
    def is_drawn(self) -> bool:
        return self._actor is not None

    # ── direction glyphs ────────────────────────────────────────────
    def _draw_directions(
        self,
        project: Any,
        results: Any,
        field_key: str,
        step: int,
        positions: dict[int, tuple[float, float, float]],
        element_map: dict[int, float],
        limits: tuple[float, float],
    ) -> Any:
        """One segment per element, along its major principal axis.

        The length carries the *spread* ``|major - minor|`` — a state with equal
        principals has no direction to show and draws nothing — and the colour
        is the element's own value of the same field, so a segment can never
        disagree with the surface it sits on.
        """
        stresses = getattr(results, "element_stresses", {}) or {}
        candidates: list[tuple[np.ndarray, np.ndarray, float, float, float]] = []
        for element in shell_elements(project):
            history = stresses.get(element.id)
            if history is None or element.id not in element_map:
                continue
            rows = np.asarray(history)
            if rows.size == 0:
                continue
            row = rows[step]
            corners = np.asarray(
                [positions[nid] for nid in element.nodes if nid in positions],
                dtype=float,
            )
            axes = _in_plane_axes(corners)
            if axes is None:
                continue
            e1, e2, size = axes
            centre = corners.mean(axis=0)
            direction = _unit_at(principal_angle(row, field_key), e1, e2)
            major, minor = _principal_pair(row, field_key)
            candidates.append(
                (centre, direction, size, abs(major - minor), element_map[element.id]),
            )

        if not candidates:
            return None
        largest = max(candidate[3] for candidate in candidates) or 1.0
        points: list[np.ndarray] = []
        segments: list[int] = []
        scalars: list[float] = []
        for centre, direction, size, spread, value in candidates:
            half = GLYPH_LENGTH_FRACTION * size * (spread / largest)
            if half <= 0.0:
                continue
            segments.extend([2, len(points)])
            points.append(centre - direction * half)
            segments.append(len(points))
            points.append(centre + direction * half)
            scalars.append(value)

        if not segments:
            return None
        lines = pv.PolyData()
        lines.points = np.asarray(points, dtype=float)
        lines.lines = np.asarray(segments, dtype=np.int64)
        lines.cell_data["value"] = np.asarray(scalars, dtype=float)
        return self._plotter.add_mesh(
            lines,
            scalars="value",
            cmap=CMAP,
            clim=limits,
            line_width=3,
            lighting=False,
            pickable=False,
            render=False,
        )


def _unit_at(angle_deg: float, e1: np.ndarray, e2: np.ndarray) -> np.ndarray:
    """A unit vector at ``angle_deg`` from ``e1`` towards ``e2``."""
    radians = np.radians(angle_deg)
    direction = np.cos(radians) * e1 + np.sin(radians) * e2
    norm = float(np.linalg.norm(direction))
    return direction / norm if norm > 0 else e1


def _in_plane_axes(corners: np.ndarray) -> tuple[np.ndarray, np.ndarray, float] | None:
    """The element's own 1- and 2-axes and its size, from its corners."""
    if len(corners) < 3:
        return None
    e1 = corners[1] - corners[0]
    normal = np.cross(corners[1] - corners[0], corners[-1] - corners[0])
    size = float(np.linalg.norm(e1))
    if size == 0.0 or float(np.linalg.norm(normal)) == 0.0:
        return None
    e1 = e1 / np.linalg.norm(e1)
    normal = normal / np.linalg.norm(normal)
    e2 = np.cross(normal, e1)
    return e1, e2, size


def _principal_pair(row: np.ndarray, field_key: str) -> tuple[float, float]:
    """The ``(major, minor)`` pair behind a principal field key."""
    from opensees_studio.core.shell_results import bending_principal, membrane_principal

    principal = membrane_principal(row) if field_key.startswith("N") else bending_principal(row)
    return principal.major, principal.minor


def _limits(values: np.ndarray) -> tuple[float, float]:
    """Colour limits: symmetric about zero when the field changes sign.

    A moment or a membrane force is read by its sign, so the middle of the
    colour map must be zero; a magnitude keeps its own range. A constant field
    gets a band of its own width (or ±1 around zero) so the map is not degenerate.
    """
    low = float(np.min(values))
    high = float(np.max(values))
    if low < 0.0 < high:
        limit = max(abs(low), abs(high))
        return (-limit, limit)
    if low == high:
        pad = abs(low) if low != 0.0 else 1.0
        return (low - pad, high + pad)
    return (low, high)
