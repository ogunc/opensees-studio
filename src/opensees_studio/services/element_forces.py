"""Element force diagram data extraction.

Translates a :class:`StaticResults`'s raw 12-component local-force vectors
into per-element ``(value_at_i, value_at_j)`` pairs for a chosen force
component. The 3D beam local-force convention (matches OpenSees
``forceBeamColumn``/``elasticBeamColumn`` ``localForce`` response):

    index   component   description
    0       N1          axial force at node i (- = compression)
    1       Vy1         shear in local y at node i
    2       Vz1         shear in local z at node i
    3       T1          torsion at node i
    4       My1         moment about local y at node i
    5       Mz1         moment about local z at node i
    6       N2          axial force at node j
    7       Vy2         shear in local y at node j
    8       Vz2         shear in local z at node j
    9       T2          torsion at node j
    10      My2         moment about local y at node j
    11      Mz2         moment about local z at node j

For 2D models OpenSees returns only 6 components per element
([N1, Vy1, Mz1, N2, Vy2, Mz2]); we handle both shapes.

Diagram orientation: shear/moment values must be drawn perpendicular
to the element's local axis. The :class:`DiagramData` returned here
includes everything a renderer needs without re-querying OpenSees.

Between the ends a member under span loads is not linear. With
``stations=True`` the diagram also carries intermediate stations for every
frame member that has a span load (uniform, point, trapezoidal, self weight):
the internal forces follow from the end forces and the loads by statics, so
the moment diagram is parabolic under a uniform load and piecewise under point
loads. The values are those of ``values_i`` / ``values_j`` at the two ends.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from opensees_studio.core import (
    ConstantTimeSeries,
    FrameMember,
    LinearTimeSeries,
    PlainLoadPattern,
    Project,
    StaticCase,
)
from opensees_studio.core.area_loads import pattern_distributed_loads
from opensees_studio.core.frame_members import (
    ClearPiece,
    ClearPoint,
    member_layout,
    split_member_loads,
)
from opensees_studio.core.self_weight import self_weight_loads
from opensees_studio.services.results import StaticResults


class ForceComponent(Enum):
    """Which force component to plot."""

    N = "N"  # axial
    V2 = "V2"  # shear in local y (in-plane shear for 2D)
    V3 = "V3"  # shear in local z
    T = "T"  # torsion
    M2 = "M2"  # moment about local y
    M3 = "M3"  # moment about local z (in-plane moment for 2D)

    @property
    def is_moment(self) -> bool:
        """True for the moment components (M2, M3, torsion), whose unit is force × length."""
        return self in (ForceComponent.T, ForceComponent.M2, ForceComponent.M3)

    @property
    def quantity_kind(self) -> str:
        """The :class:`UnitConverter` quantity this component is measured in."""
        return "moment" if self.is_moment else "force"


# Map (component, end) → index into the local-force vector for 3D and 2D.
_INDEX_3D = {
    (ForceComponent.N, "i"): 0,
    (ForceComponent.N, "j"): 6,
    (ForceComponent.V2, "i"): 1,
    (ForceComponent.V2, "j"): 7,
    (ForceComponent.V3, "i"): 2,
    (ForceComponent.V3, "j"): 8,
    (ForceComponent.T, "i"): 3,
    (ForceComponent.T, "j"): 9,
    (ForceComponent.M2, "i"): 4,
    (ForceComponent.M2, "j"): 10,
    (ForceComponent.M3, "i"): 5,
    (ForceComponent.M3, "j"): 11,
}
_INDEX_2D = {
    (ForceComponent.N, "i"): 0,
    (ForceComponent.N, "j"): 3,
    (ForceComponent.V2, "i"): 1,
    (ForceComponent.V2, "j"): 4,
    (ForceComponent.M3, "i"): 2,
    (ForceComponent.M3, "j"): 5,
}

# Truss elements expose a different localForce layout than frames:
# 2D truss → 4-vector [N_i, 0, N_j, 0]  (only axial; shears are zero-padded)
# 3D truss → 6-vector [N_i, 0, 0, N_j, 0, 0]
# So we map only the N component; other components return None.
_INDEX_TRUSS_2D = {
    (ForceComponent.N, "i"): 0,
    (ForceComponent.N, "j"): 2,
}
_INDEX_TRUSS_3D = {
    (ForceComponent.N, "i"): 0,
    (ForceComponent.N, "j"): 3,
}


@dataclass
class DiagramData:
    """Per-element force values for a chosen component, ready to render.

    Attributes
    ----------
    component:
        Which scalar component these values represent.
    element_ids:
        Length-N array of element IDs (parallel to the value arrays).
    values_i, values_j:
        Length-N arrays of the component's value at each element's i/j end.
        Sign convention is OpenSees local: positive axial = tension,
        positive shear/moment follows the right-hand rule about local axes.
    abs_max:
        Largest absolute value across all elements; used to normalize
        diagram heights so the largest force draws at the requested scale.
    ends:
        Element id → the two points the end forces act at, for a member whose
        flexible part does not run joint to joint (rigid end zones, an
        insertion point). The end forces are those of the flexible part, so
        the diagram is drawn there. Every other element runs node to node.
    """

    component: ForceComponent
    element_ids: np.ndarray
    values_i: np.ndarray
    values_j: np.ndarray
    abs_max: float
    ends: dict[int, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)
    stations: dict[int, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)
    """Element id → ``(s, values)``: stations along a loaded member's flexible part, ``s`` the
    fraction from end i (ascending, 0 first and 1 last; a repeated ``s`` is a jump under a
    point load), ``values`` in the sign of ``values_i`` / ``values_j``. A member without a
    span load, or a diagram that was not asked for stations, has no entry: it is linear."""


# ──────────────────────────── stations under span loads ────────────────────────────
_STATION_INTERVALS = 24
_EPS = 1e-9

_Segment = tuple[float, float, tuple[float, ...], tuple[float, ...]]
_Point = tuple[float, tuple[float, float, float]]


def _case_member_loads(
    project: Project, results: StaticResults, step: int
) -> dict[int, tuple[list[_Segment], list[_Point]]]:
    """Span loads each member carries at ``step`` of the case behind ``results``.

    ``{element id: (segments, points)}`` as :func:`split_member_loads` takes
    them, scaled by each pattern's time series at that step. Empty when the
    case is unknown or a pattern uses a time series that is not a plain ramp
    or constant, so the caller falls back to straight lines.
    """
    case = next((c for c in project.analyses if c.id == results.case_id), None)
    if not isinstance(case, StaticCase):
        return {}
    series = {ts.id: ts for ts in project.time_series}
    patterns = {p.id: p for p in project.load_patterns}
    index = step % max(results.n_steps, 1)
    ramp = (index + 1) * case.load_factor_increment
    out: dict[int, tuple[list[_Segment], list[_Point]]] = {}

    def add(eid: int) -> tuple[list[_Segment], list[_Point]]:
        return out.setdefault(eid, ([], []))

    for pid in case.pattern_ids:
        pattern = patterns.get(pid)
        if not isinstance(pattern, PlainLoadPattern):
            continue
        ts = series.get(pattern.time_series_id)
        if isinstance(ts, LinearTimeSeries):
            scale = ts.factor * ramp
        elif isinstance(ts, ConstantTimeSeries):
            scale = ts.factor
        else:
            return {}
        uniform = [*pattern.element_loads, *self_weight_loads(project, pattern.self_weight)]
        for ul in uniform:
            w = (scale * ul.wx, scale * ul.wy, scale * ul.wz)
            add(ul.element_id)[0].append((0.0, 1.0, w, w))
        for dl in pattern_distributed_loads(project, pattern):
            w0 = tuple(scale * v for v in dl.start())
            w1 = tuple(scale * v for v in dl.end())
            add(dl.element_id)[0].append((dl.x_start, dl.x_end, w0, w1))
        for pl in pattern.point_loads:
            p = (scale * pl.px, scale * pl.py, scale * pl.pz)
            add(pl.element_id)[1].append((pl.x, p))
    return out


def _load_sums(
    pieces: Sequence[ClearPiece],
    points: Sequence[ClearPoint],
    clear: float,
    x: float,
    inclusive: bool,
) -> tuple[np.ndarray, np.ndarray]:
    """``(F, M1)``: the resultant of the loads between 0 and ``x`` and its first moment about 0.

    Both are local ``(x, y, z)`` vectors; ``x`` is a distance along the flexible
    part and a point load at exactly ``x`` counts when ``inclusive``.
    """
    force = np.zeros(3)
    moment = np.zeros(3)
    for piece in pieces:
        d_a, d_b = piece.a * clear, piece.b * clear
        if x <= d_a or d_b <= d_a:
            continue
        e = min(x, d_b)
        n = e - d_a
        slope = (np.asarray(piece.w_b) - np.asarray(piece.w_a)) / (d_b - d_a)
        w0 = np.asarray(piece.w_a)
        force += w0 * n + slope * n * n / 2.0
        moment += w0 * (e * e - d_a * d_a) / 2.0 + slope * (
            (e**3 - d_a**3) / 3.0 - d_a * (e * e - d_a * d_a) / 2.0
        )
    for point in points:
        p = point.x * clear
        if p < x - _EPS * clear or (inclusive and p <= x + _EPS * clear):
            force += point.p
            moment += p * point.p
    return force, moment


def _station_value(
    component: ForceComponent,
    end_i: np.ndarray,
    loads: tuple[np.ndarray, np.ndarray],
    x: float,
) -> float:
    """Internal force at distance ``x`` from end i: the end force plus the loads before ``x``.

    ``end_i`` is ``(N, Vy, Vz, T, My, Mz)`` at end i and ``loads`` the
    ``(F, M1)`` sums of the span loads before ``x``; every force acts on the
    member, as OpenSees reports its end forces. The moment of a force at
    distance ``p`` about the section at ``x`` is ``(p - x)`` times it.
    """
    f, m1 = loads
    if component is ForceComponent.N:
        return float(end_i[0] + f[0])
    if component is ForceComponent.V2:
        return float(end_i[1] + f[1])
    if component is ForceComponent.V3:
        return float(end_i[2] + f[2])
    if component is ForceComponent.T:
        return float(end_i[3])
    if component is ForceComponent.M3:
        return float(end_i[5] - x * end_i[1] + (m1[1] - x * f[1]))
    return float(end_i[4] + x * end_i[2] - (m1[2] - x * f[2]))


def internal_force_stations(
    component: ForceComponent,
    end_i: Sequence[float],
    value_j: float,
    segments: Sequence[_Segment],
    points: Sequence[_Point],
    layout: Any,
) -> tuple[np.ndarray, np.ndarray] | None:
    """``(s, values)`` of ``component`` along a member's flexible part, None if it stays linear.

    ``end_i`` is ``(N, Vy, Vz, T, My, Mz)`` as OpenSees reports it at end i;
    ``value_j`` the diagram value at end j, which pins the last station. The
    loads are given along the joint-to-joint length, as everywhere else.
    """
    if component is ForceComponent.N or not (segments or points):
        return None
    clear = layout.clear_length
    split = split_member_loads(layout, segments, points)
    if not split.pieces and not split.points:
        return None
    ends = np.asarray(end_i, dtype=float)
    abscissae = {k / _STATION_INTERVALS for k in range(_STATION_INTERVALS + 1)}
    jumps = {pt.x for pt in split.points if 0.0 < pt.x < 1.0}
    for piece in split.pieces:
        abscissae.update((piece.a, piece.b))
    abscissae.update(jumps)
    ordered = sorted(a for a in abscissae if 0.0 <= a <= 1.0)
    s: list[float] = []
    values: list[float] = []
    for a in ordered:
        sides = (False, True) if any(abs(a - j) < _EPS for j in jumps) else (True,)
        for inclusive in sides:
            x = a * clear
            loads = _load_sums(split.pieces, split.points, clear, x, inclusive)
            s.append(a)
            values.append(_station_value(component, ends, loads, x))
    values[0] = _station_value(component, ends, (np.zeros(3), np.zeros(3)), 0.0)
    values[-1] = value_j
    return np.asarray(s, dtype=float), np.asarray(values, dtype=float)


def _local_end_i(row: np.ndarray, n_components: int) -> list[float]:
    """``(N, Vy, Vz, T, My, Mz)`` at end i from a 6- or 12-component ``localForce`` row."""
    if n_components >= 12:
        return [float(v) for v in row[:6]]
    return [float(row[0]), float(row[1]), 0.0, 0.0, 0.0, float(row[2])]


def extract_diagram_data(
    project: Project,
    results: StaticResults,
    component: ForceComponent,
    *,
    step: int = -1,
    stations: bool = False,
) -> DiagramData:
    """Build a :class:`DiagramData` for a given component and analysis step.

    ``stations`` adds the intermediate stations of loaded members (see the
    module docstring). It needs ``results`` to be the results of a static case
    of ``project`` (not a combination), whose loads it reads back.

    Skips elements that:
    - Have no entry in ``results.element_forces`` (e.g. didn't return forces).
    - Don't expose the requested component in their force vector
      (e.g. asking for V3 on a 2D element with only 6 components).
    """
    ids: list[int] = []
    vi: list[float] = []
    vj: list[float] = []
    ends: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    station_data: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    member_loads = _case_member_loads(project, results, step) if stations else {}

    # Local import to avoid a cycle (element classes live in core.geometry).
    from opensees_studio.core import CorotTrussElement, TrussElement

    truss_types = (TrussElement, CorotTrussElement)

    for el in project.elements:
        # A diagram is drawn between two ends: a quad or a shell returns a
        # 24-component element force vector, but it has no i/j stations to plot
        # along. Reading its components through the beam index map produced
        # nonsense magnitudes and then killed the renderer, which unpacked
        # `n_i, n_j = el.nodes`.
        if len(el.nodes) != 2:
            continue
        forces = results.element_forces.get(el.id)
        if forces is None or forces.size == 0:
            continue
        n_components = forces.shape[1]

        if isinstance(el, truss_types):
            # Truss elements only carry axial — shears/moments not defined.
            idx_map = _INDEX_TRUSS_3D if n_components >= 6 else _INDEX_TRUSS_2D
        else:
            idx_map = _INDEX_3D if n_components >= 12 else _INDEX_2D
        idx_i = idx_map.get((component, "i"))
        idx_j = idx_map.get((component, "j"))
        if idx_i is None or idx_j is None or idx_j >= n_components:
            continue
        ids.append(el.id)
        if isinstance(el, FrameMember):
            try:
                layout = member_layout(project, el)
            except ValueError:
                layout = None
            if layout is not None and (layout.has_offset("i") or layout.has_offset("j")):
                ends[el.id] = (layout.face_i, layout.face_j)
            loads = member_loads.get(el.id)
            if layout is not None and loads is not None:
                end_i = _local_end_i(forces[step], n_components)
                found = internal_force_stations(
                    component, end_i, -float(forces[step, idx_j]), loads[0], loads[1], layout
                )
                if found is not None:
                    station_data[el.id] = found
        # OpenSees localForce returns dual-sign end forces: at end-j the
        # "internal" force is reported with the sign that points opposite
        # to end-i (equilibrium convention). For drawing continuous
        # shear/moment/axial diagrams we need a single sign convention
        # along the element — so flip end-j's sign. This is the same
        # transformation every FE post-processor does.
        raw_i = float(forces[step, idx_i])
        raw_j = float(forces[step, idx_j])
        vi.append(raw_i)
        vj.append(-raw_j)

    ids_arr = np.asarray(ids, dtype=int)
    vi_arr = np.asarray(vi, dtype=float)
    vj_arr = np.asarray(vj, dtype=float)
    abs_max = float(np.max(np.abs(np.concatenate([vi_arr, vj_arr])))) if ids else 0.0
    for _, values in station_data.values():
        abs_max = max(abs_max, float(np.max(np.abs(values))))
    return DiagramData(
        component=component,
        element_ids=ids_arr,
        values_i=vi_arr,
        values_j=vj_arr,
        abs_max=abs_max,
        ends=ends,
        stations=station_data,
    )


def envelope_diagram_data(
    project: Project,
    upper: StaticResults,
    lower: StaticResults,
    component: ForceComponent,
) -> DiagramData:
    """The max and the min diagram of an envelope, as one :class:`DiagramData`.

    Each element appears twice, once per bound, so a renderer draws both
    ribbons and labels the largest value of the max diagram and the smallest of
    the min one. ``upper`` and ``lower`` are the bounds of a
    :class:`~opensees_studio.services.results.CombinationResults`, whose forces
    are bounded in the diagram's sign convention.
    """
    a = extract_diagram_data(project, upper, component)
    b = extract_diagram_data(project, lower, component)
    return DiagramData(
        component=component,
        element_ids=np.concatenate([a.element_ids, b.element_ids]),
        values_i=np.concatenate([a.values_i, b.values_i]),
        values_j=np.concatenate([a.values_j, b.values_j]),
        abs_max=max(a.abs_max, b.abs_max),
        # Both bounds act on the same flexible parts.
        ends={**a.ends, **b.ends},
    )


def auto_scale(project: Project, data: DiagramData, target_fraction: float = 0.08) -> float:
    """Suggested geometric scale so the max diagram draws at ``target_fraction``
    of the model's bounding box diagonal.

    Returns 1.0 for empty data or zero-magnitude force fields.
    """
    if data.abs_max <= 0.0 or not project.nodes:
        return 1.0
    coords = np.array([n.coords for n in project.nodes], dtype=float)
    bbox = float(np.linalg.norm(coords.max(axis=0) - coords.min(axis=0)))
    if bbox <= 0.0:
        return 1.0
    return (bbox * target_fraction) / data.abs_max
