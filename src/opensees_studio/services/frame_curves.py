"""The bent shape of each frame member, for drawing a deformed shape.

A deformed shape that only moves the joints draws every member as a straight
chord between its two displaced ends, so a loaded beam whose joints barely
move looks undeformed. Like SAP2000, the viewport draws the member's own
deflection along its length instead. This module computes it and draws
nothing:

* every beam-column takes the cubic Hermite interpolation of its end
  translations and rotations (the Euler-Bernoulli shape of a member without
  span loads), axial displacement linear between the ends;
* an end with a bending release (``M3`` / ``M2``, with or without a
  partial-fixity spring) does not share the joint's rotation, so the cubic
  there takes zero curvature instead of the joint's slope; both ends released
  is the straight chord;
* for the results of a static case, a member on an ``ElasticSection`` with
  span loads integrates its moment diagram with its ``EI`` (property
  modifiers included), so a uniform load draws the quartic elastic curve,
  not a cubic between the joints. That is the curve the member diagram
  window plots as its relative deformation.

Trusses, links, bearings and walls stay straight: they carry no bending
along their length.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from opensees_studio.core import ElasticSection, FrameMember, Project
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.plane import dof_indices
from opensees_studio.services.element_forces import ForceComponent, extract_diagram_data
from opensees_studio.services.results import StaticResults

#: Stations along each member, both ends included: enough for a smooth cubic
#: or quartic at screen size, few enough for a model of 20k members.
CURVE_STATIONS = 11


@dataclass(frozen=True)
class FrameCurves:
    """Displacement of evenly spaced stations along each bent member.

    ``offsets[k, s]`` is the global ``(ux, uy, uz)`` of member
    ``element_ids[k]`` at ``stations[s]`` (the fraction from end i), in the
    same units and normalisation as the joints' displacements it goes with.
    The first and the last station are the two joints' own translations, so
    the curve meets the displaced joints.
    """

    element_ids: np.ndarray
    stations: np.ndarray
    offsets: np.ndarray

    def __len__(self) -> int:
        return len(self.element_ids)


@dataclass(frozen=True)
class FrameBasis:
    """What the curves need of each beam-column, independent of any result."""

    element_ids: np.ndarray  # (F,)
    nodes_i: np.ndarray  # (F,) node ids
    nodes_j: np.ndarray
    x: np.ndarray  # (F, 3) local axes in global coordinates
    y: np.ndarray
    z: np.ndarray
    length: np.ndarray  # (F,)
    free_i: np.ndarray  # (F, 2) bending released at end i: [about z (M3), about y (M2)]
    free_j: np.ndarray
    eiz: np.ndarray  # (F,) EI of an elastic section, nan otherwise
    eiy: np.ndarray


def _has_rotations(project: Project) -> bool:
    return any(slot >= 3 for slot in dof_indices(project.ndm, project.ndf))


def _elastic_ei(project: Project, element: Any) -> tuple[float, float]:
    section_id = getattr(element, "section_id", None)
    section = next((s for s in project.sections if s.id == section_id), None)
    if not isinstance(section, ElasticSection):
        return np.nan, np.nan
    modifiers = element.modifiers
    eiz = float(section.E * section.Iz * modifiers.i33)
    eiy = float(section.E * section.Iy * modifiers.i22) if section.Iy is not None else np.nan
    return eiz, eiy


def frame_basis(project: Project) -> FrameBasis:
    """Local axes, lengths, releases and elastic EI of the beam-columns of ``project``."""
    coords = {node.id: np.asarray(node.coords, dtype=float) for node in project.nodes}
    rows: list[tuple[Any, ...]] = []
    for element in project.elements:
        if not isinstance(element, FrameMember) or len(element.nodes) != 2:
            continue
        n_i, n_j = int(element.nodes[0]), int(element.nodes[1])
        if n_i not in coords or n_j not in coords:
            continue
        p_i, p_j = coords[n_i].copy(), coords[n_j].copy()
        if project.ndm == 2:
            p_i[1] = p_j[1] = 0.0
        axes = frame_local_axes(
            project.ndm,
            p_i.tolist(),
            p_j.tolist(),
            float(getattr(element, "local_axis_angle", 0.0) or 0.0),
        )
        if axes is None:
            continue
        releases = element.releases
        free_i = ("M3" in releases.i.released, "M2" in releases.i.released)
        free_j = ("M3" in releases.j.released, "M2" in releases.j.released)
        eiz, eiy = _elastic_ei(project, element)
        rows.append(
            (
                element.id,
                n_i,
                n_j,
                *axes,
                float(np.linalg.norm(p_j - p_i)),
                free_i,
                free_j,
                eiz,
                eiy,
            )
        )
    if rows:
        cols = list(zip(*rows, strict=True))
        basis = FrameBasis(
            element_ids=np.asarray(cols[0], dtype=np.int64),
            nodes_i=np.asarray(cols[1], dtype=np.int64),
            nodes_j=np.asarray(cols[2], dtype=np.int64),
            x=np.asarray(cols[3], dtype=float),
            y=np.asarray(cols[4], dtype=float),
            z=np.asarray(cols[5], dtype=float),
            length=np.asarray(cols[6], dtype=float),
            free_i=np.asarray(cols[7], dtype=bool),
            free_j=np.asarray(cols[8], dtype=bool),
            eiz=np.asarray(cols[9], dtype=float),
            eiy=np.asarray(cols[10], dtype=float),
        )
    else:
        empty3 = np.zeros((0, 3))
        basis = FrameBasis(
            element_ids=np.zeros(0, dtype=np.int64),
            nodes_i=np.zeros(0, dtype=np.int64),
            nodes_j=np.zeros(0, dtype=np.int64),
            x=empty3,
            y=empty3,
            z=empty3,
            length=np.zeros(0),
            free_i=np.zeros((0, 2), dtype=bool),
            free_j=np.zeros((0, 2), dtype=bool),
            eiz=np.zeros(0),
            eiy=np.zeros(0),
        )
    return basis


def transverse_shape(
    xi: np.ndarray,
    a: Any,
    b: Any,
    slope_a: Any,
    slope_b: Any,
    free_a: Any = False,
    free_b: Any = False,
) -> np.ndarray:
    """Transverse displacement along a member from its two ends.

    ``a`` / ``b`` are the end displacements and ``slope_a`` / ``slope_b`` the
    end slopes times the length (``L dv/dx``). Every end argument may be a
    scalar or an array of shape ``(F,)``; the result is ``(F, S)`` (or
    ``(S,)`` for scalars). A free (released) end takes zero curvature instead
    of its slope; both ends free give the straight chord.
    """
    t = np.asarray(xi, dtype=float)
    a, b, sa, sb = (np.asarray(v, dtype=float)[..., None] for v in (a, b, slope_a, slope_b))
    fa = np.asarray(free_a, dtype=bool)[..., None]
    fb = np.asarray(free_b, dtype=bool)[..., None]
    t2, t3 = t * t, t * t * t
    chord = a + (b - a) * t
    fixed = (
        (2 * t3 - 3 * t2 + 1) * a + (t3 - 2 * t2 + t) * sa + (-2 * t3 + 3 * t2) * b + (t3 - t2) * sb
    )
    # End a released: v = a + c1 t + c3 t^3, with v(1) = b and v'(1) = sb.
    c3 = (sb - (b - a)) / 2.0
    free_at_a = a + ((b - a) - c3) * t + c3 * t3
    # End b released: the mirror, in s = 1 - t, with dv/ds = -sa at s = 1.
    s = 1.0 - t
    d3 = (-sa - (a - b)) / 2.0
    free_at_b = b + ((a - b) - d3) * s + d3 * s * s * s
    out = np.where(fa & fb, chord, np.where(fa, free_at_a, np.where(fb, free_at_b, fixed)))
    return np.asarray(out)


def _rows(dofs: dict[int, Any], ids: np.ndarray, ndm: int, ndf: int) -> np.ndarray:
    """Six global slots per node id (zeros for a node without a value)."""
    slots = list(dof_indices(ndm, ndf))
    out = np.zeros((len(ids), 6))
    for k, nid in enumerate(ids.tolist()):
        values = dofs.get(nid)
        if values is None:
            continue
        for slot, value in zip(slots, np.asarray(values, dtype=float), strict=False):
            out[k, slot] = value
    return out


def _local_parts(
    basis: FrameBasis, rows_i: np.ndarray, rows_j: np.ndarray, xi: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """``(axial, v, w, chord_v, chord_w)`` along every member, each ``(F, S)``."""

    def dot(u: np.ndarray, axis: np.ndarray) -> np.ndarray:
        return np.asarray((u * axis).sum(axis=1))

    u_i, u_j = rows_i[:, :3], rows_j[:, :3]
    r_i, r_j = rows_i[:, 3:], rows_j[:, 3:]
    ax_i, ax_j = dot(u_i, basis.x), dot(u_j, basis.x)
    v_i, v_j = dot(u_i, basis.y), dot(u_j, basis.y)
    w_i, w_j = dot(u_i, basis.z), dot(u_j, basis.z)
    length = basis.length
    # A rotation about local z is dv/dx; one about local y is -dw/dx.
    sv_i, sv_j = length * dot(r_i, basis.z), length * dot(r_j, basis.z)
    sw_i, sw_j = -length * dot(r_i, basis.y), -length * dot(r_j, basis.y)
    t = np.asarray(xi, dtype=float)
    axial = ax_i[:, None] + (ax_j - ax_i)[:, None] * t
    v = transverse_shape(t, v_i, v_j, sv_i, sv_j, basis.free_i[:, 0], basis.free_j[:, 0])
    w = transverse_shape(t, w_i, w_j, sw_i, sw_j, basis.free_i[:, 1], basis.free_j[:, 1])
    chord_v = v_i[:, None] + (v_j - v_i)[:, None] * t
    chord_w = w_i[:, None] + (w_j - w_i)[:, None] * t
    return axial, v, w, chord_v, chord_w


def _to_global(basis: FrameBasis, axial: np.ndarray, v: np.ndarray, w: np.ndarray) -> np.ndarray:
    return np.asarray(
        axial[..., None] * basis.x[:, None, :]
        + v[..., None] * basis.y[:, None, :]
        + w[..., None] * basis.z[:, None, :]
    )


def _empty(xi: np.ndarray) -> FrameCurves:
    return FrameCurves(np.zeros(0, dtype=np.int64), xi, np.zeros((0, len(xi), 3)))


def frame_curves_from_dofs(
    project: Project,
    dofs: dict[int, Any],
    *,
    stations: int = CURVE_STATIONS,
    global_slots: bool = False,
    basis: FrameBasis | None = None,
) -> FrameCurves:
    """Hermite curves of every beam-column from per-node DOF values.

    ``dofs`` maps a node id to its values in the OpenSees DOF order of a result
    row (global sign already applied), or, with ``global_slots``, to the six
    global slots ``(Ux, Uy, Uz, Rx, Ry, Rz)``. Scale the values first: the
    curves are linear in them. ``basis`` reuses :func:`frame_basis` of the
    same project across the frames of an animation.
    """
    xi = np.linspace(0.0, 1.0, max(int(stations), 2))
    if not _has_rotations(project):
        return _empty(xi)
    basis = frame_basis(project) if basis is None else basis
    if not len(basis.element_ids):
        return _empty(xi)
    if global_slots:
        table: dict[int, np.ndarray] = {}
        for nid, values in dofs.items():
            padded = np.zeros(6)
            raw = np.asarray(values, dtype=float)[:6]
            padded[: len(raw)] = raw
            table[nid] = padded
        rows_i = np.array([table.get(n, np.zeros(6)) for n in basis.nodes_i.tolist()])
        rows_j = np.array([table.get(n, np.zeros(6)) for n in basis.nodes_j.tolist()])
    else:
        rows_i = _rows(dofs, basis.nodes_i, project.ndm, project.ndf)
        rows_j = _rows(dofs, basis.nodes_j, project.ndm, project.ndf)
    axial, v, w, _cv, _cw = _local_parts(basis, rows_i, rows_j, xi)
    return FrameCurves(basis.element_ids.copy(), xi, _to_global(basis, axial, v, w))


def integrate_curvature(
    moment_x: np.ndarray,
    moment: np.ndarray,
    ei: float,
    length: float,
    xi: np.ndarray,
    *,
    sign: float,
) -> np.ndarray:
    """Deflection from ``v'' = sign * M / EI`` with zero displacement at both ends.

    ``moment_x`` is in length units from end i. The moment stations may repeat
    at a point load (the moment is continuous, so the duplicate values are
    averaged). The double trapezoidal integration is exact for a linear moment
    and very close for the sampled parabola of a uniform load; it is evaluated
    on a fine grid and sampled at ``xi``.

    ``sign`` carries the local-force convention: the diagram's M3 is positive
    where the curvature about local z is negative (``sign=-1``), while M2 has
    the same sign as the curvature about local y (``sign=+1``).
    """
    x_sorted = np.asarray(moment_x, dtype=float)
    m_sorted = np.asarray(moment, dtype=float)
    order = np.argsort(x_sorted, kind="stable")
    x_sorted = x_sorted[order]
    m_sorted = m_sorted[order]
    unique_x, inverse = np.unique(x_sorted, return_inverse=True)
    sums = np.zeros(unique_x.size)
    counts = np.zeros(unique_x.size)
    np.add.at(sums, inverse, m_sorted)
    np.add.at(counts, inverse, 1)
    unique_m = sums / np.maximum(counts, 1.0)

    target = np.asarray(xi, dtype=float) * length
    grid = np.union1d(np.linspace(0.0, length, 81), target)
    curvature = sign * np.interp(grid, unique_x, unique_m) / ei
    dx = np.diff(grid)
    slope = np.concatenate(([0.0], np.cumsum(0.5 * (curvature[:-1] + curvature[1:]) * dx)))
    values = np.concatenate(([0.0], np.cumsum(0.5 * (slope[:-1] + slope[1:]) * dx)))
    if length > 0.0:
        values -= values[-1] * grid / length
    return np.asarray(np.interp(target, grid, values))


def static_frame_curves(
    project: Project,
    results: StaticResults,
    *,
    step: int = -1,
    scale: float = 1.0,
    stations: int = CURVE_STATIONS,
    span_loads: bool = True,
) -> FrameCurves:
    """Curves of every beam-column at ``step`` of a static result, times ``scale``.

    Hermite between the ends, and for an elastic member with span loads the
    integral of its moment diagram (see the module docstring). ``scale``
    multiplies the displacements the same way it multiplies the joints'.
    ``span_loads`` reads the case's span loads back, so it needs ``results`` to
    be a static case's own results, not a combination's.
    """
    xi = np.linspace(0.0, 1.0, max(int(stations), 2))
    if not _has_rotations(project):
        return _empty(xi)
    basis = frame_basis(project)
    if not len(basis.element_ids):
        return _empty(xi)
    dofs = {
        nid: np.asarray(history[step], dtype=float) for nid, history in results.node_disp.items()
    }
    rows_i = _rows(dofs, basis.nodes_i, project.ndm, project.ndf)
    rows_j = _rows(dofs, basis.nodes_j, project.ndm, project.ndf)
    axial, v, w, chord_v, chord_w = _local_parts(basis, rows_i, rows_j, xi)

    elastic = ~np.isnan(basis.eiz) | ~np.isnan(basis.eiy)
    if span_loads and results.element_forces and bool(elastic.any()):
        row_of = {int(eid): k for k, eid in enumerate(basis.element_ids.tolist())}
        parts: list[tuple[ForceComponent, np.ndarray, np.ndarray, np.ndarray, float]] = [
            (ForceComponent.M3, v, chord_v, basis.eiz, -1.0)
        ]
        if project.ndm == 3:
            parts.append((ForceComponent.M2, w, chord_w, basis.eiy, 1.0))
        for component, transverse, chord, ei, sign in parts:
            try:
                data = extract_diagram_data(project, results, component, step=step, stations=True)
            except (IndexError, ValueError):
                continue
            # Only a member with span loads has stations: without them the
            # moment is linear, and the Hermite cubic is already its exact curve.
            for eid, (s, values) in data.stations.items():
                k = row_of.get(int(eid))
                if k is None or not ei[k] > 0.0:
                    continue
                length = float(basis.length[k])
                relative = integrate_curvature(
                    np.asarray(s) * length, np.asarray(values), float(ei[k]), length, xi, sign=sign
                )
                transverse[k] = chord[k] + relative
    offsets = _to_global(basis, axial, v, w) * float(scale)
    return FrameCurves(basis.element_ids.copy(), xi, offsets)


__all__ = [
    "CURVE_STATIONS",
    "FrameBasis",
    "FrameCurves",
    "frame_basis",
    "frame_curves_from_dofs",
    "integrate_curvature",
    "static_frame_curves",
    "transverse_shape",
]
