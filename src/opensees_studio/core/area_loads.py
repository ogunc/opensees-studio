"""Area loads: pressure on shells, floor panels handed to their frames.

- :func:`surface_nodal_loads` — a shell pressure (:class:`SurfaceLoad`) as the
  consistent nodal forces of a bilinear quad: each corner takes
  ``value × ∫N_i dA`` (``quad_tributary_areas``) along the load's direction, the
  shell's normal or a global axis.
- :func:`floor_member_loads` — a floor panel (:class:`FloorLoad`) as trapezoidal
  loads on the frame members along its four edges. Two-way panels split at 45°
  yield lines, so an edge of length ``L`` takes ``w(t) = q min(t, L - t, s/2)``
  (``s`` the short side): a trapezoid on a long edge, a triangle on a short
  one, and the four edges together carry exactly ``q A``. One-way panels hand
  ``q × span / 2`` to the two edges across the span. Each edge may be made of
  several members (a meshed beam); their pieces of the profile become
  :class:`TrapezoidalElementLoad`\\ s in each member's own local axes.
- :func:`pattern_distributed_loads` — what every consumer of a pattern's
  member loads should read: its own trapezoidal loads plus those of its floor
  panels.

This module is part of ``core``: no Qt, no OpenSees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from opensees_studio.core.geometry.elements import FRAME_ELEMENT_CLASSES
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.loads import FloorLoad, SurfaceLoad, TrapezoidalElementLoad
from opensees_studio.core.plane import VERTICAL_AXIS
from opensees_studio.core.self_weight import gravity_direction, quad_tributary_areas

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

GEOMETRY_REL_TOL = 1e-6
"""Relative tolerance (of the panel size) for flatness, right angles and collinearity."""

_AXIS = {"X": 0, "Y": 1, "Z": 2}


class AreaLoadError(ValueError):
    """A floor panel or a surface load the model cannot carry as given."""


# ─────────────────────────── shells ───────────────────────────
def shell_normal(points: np.ndarray) -> np.ndarray:
    """Unit normal of a quad (4 x 3), by the right-hand turn of its corners."""
    normal = np.cross(points[2] - points[0], points[3] - points[1])
    length = float(np.linalg.norm(normal))
    if length <= 0.0:
        raise AreaLoadError("A degenerate shell has no normal.")
    return normal / length


def surface_nodal_loads(project: Project, loads: list[SurfaceLoad]) -> dict[int, np.ndarray]:
    """Node id -> global force (Fx, Fy, Fz) of ``loads``, summed per node."""
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    elements = {e.id: e for e in project.elements}
    forces: dict[int, np.ndarray] = {}
    for load in loads:
        element = elements.get(load.element_id)
        if element is None or len(element.nodes) != 4:
            raise AreaLoadError(f"Surface load on element {load.element_id}: not a shell.")
        points = np.array([coords[n] for n in element.nodes])
        if load.direction == "normal":
            direction = shell_normal(points)
        else:
            direction = np.zeros(3)
            direction[_AXIS[load.direction]] = 1.0
        for nid, share in zip(element.nodes, quad_tributary_areas(points), strict=True):
            forces[nid] = forces.get(nid, np.zeros(3)) + load.value * share * direction
    return forces


# ─────────────────────────── floor panels ───────────────────────────
def _panel(project: Project, load: FloorLoad) -> np.ndarray:
    """The four corners, checked: distinct, horizontal, a rectangle."""
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    missing = [n for n in load.nodes if n not in coords]
    if missing:
        raise AreaLoadError(f"Floor load: missing node(s) {missing}.")
    if len(set(load.nodes)) != 4:
        raise AreaLoadError("A floor panel needs four different corner nodes.")
    points = np.array([coords[n] for n in load.nodes])
    size = float(np.max(np.ptp(points, axis=0))) or 1.0
    tol = GEOMETRY_REL_TOL * size
    if float(np.ptp(points[:, VERTICAL_AXIS])) > tol:
        raise AreaLoadError(
            f"Floor panel {list(load.nodes)} is not horizontal: its corners are at different "
            "elevations. Use a surface load on shells for a sloped area."
        )
    edges = [points[(k + 1) % 4] - points[k] for k in range(4)]
    lengths = [float(np.linalg.norm(e)) for e in edges]
    if min(lengths) <= tol:
        raise AreaLoadError(f"Floor panel {list(load.nodes)} has a zero-length edge.")
    right = all(abs(float(edges[k] @ edges[(k + 1) % 4])) <= tol * max(lengths) for k in range(4))
    if not right:
        raise AreaLoadError(
            f"Floor panel {list(load.nodes)} is not a rectangle (corners in order, right "
            "angles). Split it into rectangles, or load shells instead."
        )
    return points


def edge_profile(
    length: float, short_side: float, q: float
) -> list[tuple[float, float, float, float]]:
    """Two-way load along an edge: linear pieces ``(t0, t1, w0, w1)``, ``t`` from its start."""
    half = short_side / 2.0
    if length <= short_side + 1e-12 * length:
        mid = length / 2.0
        return [(0.0, mid, 0.0, q * mid), (mid, length, q * mid, 0.0)]
    return [
        (0.0, half, 0.0, q * half),
        (half, length - half, q * half, q * half),
        (length - half, length, q * half, 0.0),
    ]


def _edge_members(
    project: Project, start: np.ndarray, end: np.ndarray, tol: float
) -> list[tuple[Any, float, float]]:
    """Frame members lying on segment start→end: ``(element, t_i, t_j)``, distances from start."""
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    axis = end - start
    length = float(np.linalg.norm(axis))
    unit = axis / length
    found: list[tuple[Any, float, float]] = []
    for element in project.elements:
        if not isinstance(element, FRAME_ELEMENT_CLASSES) or len(element.nodes) != 2:
            continue
        ts: list[float] = []
        for nid in element.nodes:
            rel = coords[nid] - start
            t = float(rel @ unit)
            if float(np.linalg.norm(rel - t * unit)) > tol or t < -tol or t > length + tol:
                break
            ts.append(min(max(t, 0.0), length))
        else:
            if abs(ts[1] - ts[0]) > tol:
                found.append((element, ts[0], ts[1]))
    covered = sorted((min(a, b), max(a, b)) for _e, a, b in found)
    reach = 0.0
    for a, b in covered:
        if a > reach + tol:
            break
        reach = max(reach, b)
    if reach < length - tol:
        raise AreaLoadError(
            f"No frame members along the whole floor-panel edge from "
            f"{tuple(round(float(v), 6) for v in start)} to {tuple(round(float(v), 6) for v in end)}: "
            "draw the beams on that edge (or use shells)."
        )
    return found


def floor_member_loads(project: Project, load: FloorLoad) -> list[TrapezoidalElementLoad]:
    """The trapezoidal member loads a floor panel hands to the frames on its edges."""
    points = _panel(project, load)
    lengths = [float(np.linalg.norm(points[(k + 1) % 4] - points[k])) for k in range(4)]
    size = max(lengths)
    tol = GEOMETRY_REL_TOL * size
    q = load.value
    short = min(lengths)
    profiles: dict[int, list[tuple[float, float, float, float]]] = {}
    if load.distribution == "two_way":
        for k in range(4):
            profiles[k] = edge_profile(lengths[k], short, q)
    else:
        span_edge = 0 if load.distribution == "one_way_12" else 1
        span = lengths[span_edge]
        for k in ((span_edge + 1) % 4, (span_edge + 3) % 4):
            profiles[k] = [(0.0, lengths[k], q * span / 2.0, q * span / 2.0)]
    down = gravity_direction(project.ndm)
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    out: list[TrapezoidalElementLoad] = []
    for k, pieces in profiles.items():
        start, end = points[k], points[(k + 1) % 4]
        for element, ti, tj in _edge_members(project, start, end, tol):
            axes = frame_local_axes(
                project.ndm, coords[element.nodes[0]].tolist(), coords[element.nodes[1]].tolist()
            )
            if axes is None:
                continue
            x, y, z = axes
            local = (float(down @ x), float(down @ y), float(down @ z))
            span_m = tj - ti  # signed: the member may run against the edge
            for t0, t1, w0, w1 in pieces:
                lo, hi = max(t0, min(ti, tj)), min(t1, max(ti, tj))
                if hi - lo <= tol:
                    continue

                def w_at(
                    t: float, _t0: float = t0, _t1: float = t1, _w0: float = w0, _w1: float = w1
                ) -> float:
                    return _w0 + (_w1 - _w0) * (t - _t0) / (_t1 - _t0)

                xa, xb = (lo - ti) / span_m, (hi - ti) / span_m
                wa, wb = w_at(lo), w_at(hi)
                if xa > xb:
                    xa, xb, wa, wb = xb, xa, wb, wa
                out.append(
                    TrapezoidalElementLoad(
                        element_id=element.id,
                        x_start=min(max(xa, 0.0), 1.0),
                        x_end=min(max(xb, 0.0), 1.0),
                        wx_start=wa * local[0],
                        wx_end=wb * local[0],
                        wy_start=wa * local[1],
                        wy_end=wb * local[1],
                        wz_start=wa * local[2],
                        wz_end=wb * local[2],
                    )
                )
    return out


def floor_area(project: Project, load: FloorLoad) -> float:
    """Plan area of a floor panel."""
    points = _panel(project, load)
    return float(np.linalg.norm(points[1] - points[0]) * np.linalg.norm(points[2] - points[1]))


def pattern_distributed_loads(project: Project, pattern: Any) -> list[TrapezoidalElementLoad]:
    """A pattern's trapezoidal member loads, its floor panels' included."""
    loads = list(getattr(pattern, "distributed_loads", ()))
    for floor in getattr(pattern, "floor_loads", ()):
        loads.extend(floor_member_loads(project, floor))
    return loads


def floor_panels(
    project: Project, node_ids: set[int] | list[int]
) -> list[tuple[int, int, int, int]]:
    """The rectangular bays among ``node_ids`` that frames close on all four sides.

    For a building floor: the selected joints are grouped by elevation, and from
    each joint the smallest axis-aligned rectangle (+X, +Y) whose four corners
    are selected joints and whose four edges carry frame members becomes a
    panel, corners counter-clockwise from that joint. Joints on a beam between
    two columns are corners of nothing (their rectangle's edges are not framed
    across), so a meshed beam does not split a bay.
    """
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    chosen = [n for n in node_ids if n in coords]
    if len(chosen) < 4:
        return []
    size = float(np.max(np.ptp(np.array([coords[n] for n in chosen]), axis=0))) or 1.0
    tol = GEOMETRY_REL_TOL * size
    panels: list[tuple[int, int, int, int]] = []
    seen: set[frozenset[int]] = set()
    by_level: dict[float, list[int]] = {}
    for nid in chosen:
        z = float(coords[nid][VERTICAL_AXIS])
        key = next((k for k in by_level if abs(k - z) <= tol), z)
        by_level.setdefault(key, []).append(nid)
    for level_nodes in by_level.values():

        def at(x: float, y: float, _nodes: list[int] = level_nodes) -> int | None:
            for nid in _nodes:
                c = coords[nid]
                if abs(c[0] - x) <= tol and abs(c[1] - y) <= tol:
                    return nid
            return None

        xs = sorted({round(float(coords[n][0]) / tol) * tol for n in level_nodes})
        ys = sorted({round(float(coords[n][1]) / tol) * tol for n in level_nodes})
        for a in level_nodes:
            x0, y0 = float(coords[a][0]), float(coords[a][1])
            found = None
            for x1 in (x for x in xs if x > x0 + tol):
                for y1 in (y for y in ys if y > y0 + tol):
                    b, c, d = at(x1, y0), at(x1, y1), at(x0, y1)
                    if b is None or c is None or d is None:
                        continue
                    try:
                        for p, q in ((a, b), (b, c), (c, d), (d, a)):
                            _edge_members(project, coords[p], coords[q], tol)
                    except AreaLoadError:
                        continue
                    found = (a, b, c, d)
                    break
                if found:
                    break
            if found and frozenset(found) not in seen:
                seen.add(frozenset(found))
                panels.append(found)
    return panels
