"""Per-element data for the right-click element diagram window.

While a force diagram or a deformed shape is on screen, right-clicking a frame
member opens a window with that member's diagrams side by side: axial force,
shears, moments and torsion, absolute and relative deformations, and the span
loads of the active case.

This module computes those series and draws nothing. The force curves come from
:func:`~opensees_studio.services.element_forces.element_force_curve`, so the
window uses the same end-force sign convention, the same load scaling and the
same intermediate stations as the force diagram on the canvas.

Deformations use the end translations and rotations of the result:

* **absolute** is the magnitude of the interpolated total displacement of the
  section;
* **relative** is the departure from the straight chord between the two ends
  (the member's own bending deflection).

Transverse displacement follows a cubic Hermite interpolation of the end
translations and rotations, the same shape function an Euler-Bernoulli beam
uses; the axial displacement is linear between the ends.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from opensees_studio.core import (
    ConstantTimeSeries,
    ElasticSection,
    LinearTimeSeries,
    PlainLoadPattern,
    Project,
    StaticCase,
)
from opensees_studio.core.frame_members import MemberLayout, member_layout
from opensees_studio.core.plane import dof_indices
from opensees_studio.services.element_forces import (
    ForceComponent,
    case_member_loads,
    element_force_curve,
)
from opensees_studio.services.results import StaticResults

#: Samples used for the deformation curves between the two ends.
_DEFORMATION_SAMPLES = 81


@dataclass(frozen=True)
class ForceSeries:
    """One force component along one member, ready to plot."""

    component: ForceComponent
    x: np.ndarray
    """Distance from end i, in model length units."""
    values: np.ndarray
    """Component value in model units, in the diagram's continuous sign."""
    label: str = ""
    """``"Max"`` / ``"Min"`` for an envelope bound, empty for a single result."""


@dataclass(frozen=True)
class LoadSegment:
    """A linearly varying distributed load on part of a member."""

    x0: float
    x1: float
    w0: tuple[float, float, float]
    """Local ``(wx, wy, wz)`` per unit length at ``x0``."""
    w1: tuple[float, float, float]
    """Local ``(wx, wy, wz)`` per unit length at ``x1``."""


@dataclass(frozen=True)
class PointLoad:
    """A concentrated load inside a member."""

    x: float
    p: tuple[float, float, float]
    """Local ``(px, py, pz)`` force."""


@dataclass(frozen=True)
class ElementDiagramBundle:
    """Everything the element window needs for one member."""

    element_id: int
    element_name: str
    element_type: str
    length: float
    """Joint-to-joint length, in model length units."""
    case_name: str = ""
    bound: str = ""
    forces: tuple[ForceSeries, ...] = ()
    absolute: tuple[np.ndarray, np.ndarray] | None = None
    """``(x, |u|)`` of the total section displacement."""
    relative: tuple[np.ndarray, np.ndarray] | None = None
    """``(x, |u - chord|)`` of the member's own deflection."""
    segments: tuple[LoadSegment, ...] = ()
    points: tuple[PointLoad, ...] = ()
    notes: tuple[str, ...] = ()


def element_force_curves(
    project: Project,
    results: StaticResults,
    element_id: int,
    *,
    step: int = -1,
    stations: bool = True,
    label: str = "",
) -> tuple[ForceSeries, ...]:
    """Every force component the element reports, in :class:`ForceComponent` order."""
    element = _element(project, element_id)
    length = _element_length(project, element)
    series: list[ForceSeries] = []
    for component in ForceComponent:
        curve = element_force_curve(
            project,
            results,
            element_id,
            component,
            step=step,
            stations=stations,
        )
        if curve is None:
            continue
        s, values = curve
        series.append(
            ForceSeries(
                component=component,
                x=np.asarray(s, dtype=float) * length,
                values=np.asarray(values, dtype=float),
                label=label,
            )
        )
    return tuple(series)


def element_deformation_curves(
    project: Project,
    results: StaticResults,
    element_id: int,
    *,
    step: int = -1,
    samples: int = _DEFORMATION_SAMPLES,
    stations: bool = True,
) -> tuple[
    tuple[np.ndarray, np.ndarray] | None,
    tuple[np.ndarray, np.ndarray] | None,
    str,
]:
    """``(absolute, relative, note)`` deformation curves of one member.

    Both curves are ``(x, magnitude)`` in model length units. The note is empty
    when the result carries the two nodes' displacements, and says why the
    curves are missing otherwise.

    For a linear-elastic section the relative curve integrates the member's
    moment diagram with its ``EI``, so a uniform load gives the quartic elastic
    curve rather than a cubic between the joints. A non-elastic section, or a
    result without load stations, falls back to the Hermite interpolation of
    the end translations and rotations.
    """
    element = _element(project, element_id)
    layout = _layout(project, element)
    if layout is None:
        return None, None, "A zero-length member has no deformation diagram."
    if len(element.nodes) != 2:
        return None, None, "Only a two-node line element has a deformation diagram."
    node_i, node_j = element.nodes
    if node_i not in results.node_disp or node_j not in results.node_disp:
        return None, None, "This result carries no nodal displacements for the member."

    row_i = _row(results.node_disp[node_i], step)
    row_j = _row(results.node_disp[node_j], step)
    full_i = _global_dofs(row_i, project.ndm, project.ndf)
    full_j = _global_dofs(row_j, project.ndm, project.ndf)

    x_axis, y_axis, z_axis = layout.x, layout.y, layout.z
    u_i, u_j = full_i[:3], full_j[:3]
    r_i, r_j = full_i[3:], full_j[3:]

    # Local end translations and rotations. A rotation about local z gives
    # dv/dx, and one about local y gives dw/dx = -theta_y.
    ux_i, vy_i, wz_i = float(u_i @ x_axis), float(u_i @ y_axis), float(u_i @ z_axis)
    ux_j, vy_j, wz_j = float(u_j @ x_axis), float(u_j @ y_axis), float(u_j @ z_axis)
    tz_i, tz_j = float(r_i @ z_axis), float(r_j @ z_axis)
    ty_i, ty_j = float(r_i @ y_axis), float(r_j @ y_axis)

    xi = np.linspace(0.0, 1.0, max(samples, 2))
    h00 = 2.0 * xi**3 - 3.0 * xi**2 + 1.0
    h10 = xi**3 - 2.0 * xi**2 + xi
    h01 = -2.0 * xi**3 + 3.0 * xi**2
    h11 = xi**3 - xi**2
    length = layout.length

    axial = (1.0 - xi) * ux_i + xi * ux_j
    chord_y = (1.0 - xi) * vy_i + xi * vy_j
    chord_z = (1.0 - xi) * wz_i + xi * wz_j
    hermite_y = h00 * vy_i + h10 * length * tz_i + h01 * vy_j + h11 * length * tz_j
    hermite_z = h00 * wz_i + h10 * length * (-ty_i) + h01 * wz_j + h11 * length * (-ty_j)
    relative_y = hermite_y - chord_y
    relative_z = hermite_z - chord_z

    eiz, eiy = _elastic_ei(project, element)
    integrated = False
    if stations:
        if eiz is not None and eiz > 0.0:
            curve = element_force_curve(
                project, results, element_id, ForceComponent.M3, step=step, stations=True
            )
            if curve is not None:
                moment_x, moment = curve
                _grid, values = _integrate_curvature(
                    moment_x * length, moment, eiz, length, xi, sign=-1.0
                )
                relative_y = values
                integrated = True
        if project.ndm == 3 and eiy is not None and eiy > 0.0:
            curve = element_force_curve(
                project, results, element_id, ForceComponent.M2, step=step, stations=True
            )
            if curve is not None:
                moment_x, moment = curve
                _grid, values = _integrate_curvature(
                    moment_x * length, moment, eiy, length, xi, sign=1.0
                )
                relative_z = values
                integrated = True

    displacement = (
        axial[:, None] * x_axis
        + (chord_y + relative_y)[:, None] * y_axis
        + (chord_z + relative_z)[:, None] * z_axis
    )
    absolute = np.linalg.norm(displacement, axis=1)
    relative = np.hypot(relative_y, relative_z)

    x = xi * length
    note = ""
    if layout.rigid_i or layout.rigid_j:
        note = (
            "The member has rigid end zones: the deformation is interpolated between "
            "the two joints."
        )
    elif not integrated:
        note = (
            "Relative deformation interpolates the end rotations (the section has no "
            "elastic EI, or the result has no element moments to integrate)."
        )
    return (x, absolute), (x, relative), note


def element_applied_loads(
    project: Project,
    results: StaticResults,
    element_id: int,
    *,
    step: int = -1,
) -> tuple[tuple[LoadSegment, ...], tuple[PointLoad, ...], str]:
    """``(segments, points, note)`` of the span loads the element carries.

    The loads are in the member's local axes and scaled by the active case's
    time series, including self weight, exactly as the force diagram reads
    them. A combination bound has no single load pattern, so it returns no
    loads and a note saying so.
    """
    case = next((c for c in project.analyses if c.id == results.case_id), None)
    if case is None:
        if any(combo.id == results.case_id for combo in project.combinations):
            return (
                (),
                (),
                "Applied loads are shown for a static case; this result is a combination bound.",
            )
        return (
            (),
            (),
            "Applied loads are not available: the result's static case is not in the project.",
        )
    if not isinstance(case, StaticCase):
        return (
            (),
            (),
            "Applied loads are shown for a static case; this result is a combination bound.",
        )
    if not _loads_are_scalable(project, case):
        return (
            (),
            (),
            "A load pattern uses a time series this view cannot scale, so its span "
            "loads are not drawn.",
        )

    loads = case_member_loads(project, results, step).get(element_id)
    if loads is None:
        return (), (), "No span loads on this member in this case."
    segments, points = loads
    element = _element(project, element_id)
    length = _element_length(project, element)
    segment_data = tuple(
        LoadSegment(
            x0=float(a) * length,
            x1=float(b) * length,
            w0=_vec3(w0),
            w1=_vec3(w1),
        )
        for a, b, w0, w1 in segments
    )
    point_data = tuple(PointLoad(x=float(x) * length, p=_vec3(p)) for x, p in points)
    note = "" if segment_data or point_data else "No span loads on this member in this case."
    return segment_data, point_data, note


def element_diagram_bundle(
    project: Project,
    results: StaticResults,
    element_id: int,
    *,
    step: int = -1,
    stations: bool = True,
    label: str = "",
    case_name: str | None = None,
) -> ElementDiagramBundle:
    """Build every curve of one member for the element window."""
    element = _element(project, element_id)
    layout = _layout(project, element)
    length = layout.length if layout is not None else _element_length(project, element)
    notes: list[str] = []

    forces = element_force_curves(
        project,
        results,
        element_id,
        step=step,
        stations=stations,
        label=label,
    )
    absolute, relative, deformation_note = element_deformation_curves(
        project,
        results,
        element_id,
        step=step,
        stations=stations,
    )
    segments, points, loads_note = element_applied_loads(
        project,
        results,
        element_id,
        step=step,
    )

    from opensees_studio.core import CorotTrussElement, TrussElement

    if isinstance(element, (TrussElement, CorotTrussElement)):
        notes.append("Truss element: axial force only; it has no shear or moment.")
    elif project.ndm == 2:
        notes.append("2D frame: V3, M2 and T are not part of its element force output.")
    if deformation_note:
        notes.append(deformation_note)
    if loads_note:
        notes.append(loads_note)

    return ElementDiagramBundle(
        element_id=element.id,
        element_name=element.name,
        element_type=type(element).__name__,
        length=length,
        case_name=case_name or results.case_name,
        bound=label,
        forces=forces,
        absolute=absolute,
        relative=relative,
        segments=segments,
        points=points,
        notes=tuple(notes),
    )


def combine_element_bundles(
    upper: ElementDiagramBundle, lower: ElementDiagramBundle
) -> ElementDiagramBundle:
    """Both envelope bounds of one member, as one bundle.

    The force panels draw the upper and lower curves together; the deformation
    and the loads stay those of the upper bundle (the maximum bound), and the
    notes of both are kept once each.
    """
    notes = list(upper.notes)
    for note in lower.notes:
        if note not in notes:
            notes.append(note)
    return replace(
        upper,
        bound="",
        forces=(*upper.forces, *lower.forces),
        notes=tuple(notes),
    )


# ─────────────────────────────── helpers ───────────────────────────────


def _element(project: Project, element_id: int) -> Any:
    element = next((el for el in project.elements if el.id == element_id), None)
    if element is None:
        raise ValueError(f"Element {element_id} is not in the project.")
    return element


def _layout(project: Project, element: Any) -> MemberLayout | None:
    try:
        return member_layout(project, element)
    except ValueError:
        return None


def _element_length(project: Project, element: Any) -> float:
    coords = {node.id: np.asarray(node.coords, dtype=float) for node in project.nodes}
    nodes = tuple(getattr(element, "nodes", ()))
    if len(nodes) != 2:
        return 0.0
    node_i, node_j = int(nodes[0]), int(nodes[1])
    if node_i not in coords or node_j not in coords:
        return 0.0
    p_i, p_j = coords[node_i], coords[node_j]
    if project.ndm == 2:
        p_i = p_i.copy()
        p_j = p_j.copy()
        p_i[1] = p_j[1] = 0.0
    return float(np.linalg.norm(p_j - p_i))


def _vec3(values: Any) -> tuple[float, float, float]:
    return (float(values[0]), float(values[1]), float(values[2]))


def _elastic_ei(project: Project, element: Any) -> tuple[float | None, float | None]:
    """``(EI_z, EI_y)`` of an elastic section, or ``(None, None)`` otherwise."""
    section_id = getattr(element, "section_id", None)
    if section_id is None:
        return None, None
    section = next((item for item in project.sections if item.id == section_id), None)
    if not isinstance(section, ElasticSection):
        return None, None
    eiz = float(section.E * section.Iz)
    eiy = float(section.E * section.Iy) if section.Iy is not None else None
    return eiz, eiy


def _integrate_curvature(
    moment_x: np.ndarray,
    moment: np.ndarray,
    ei: float,
    length: float,
    xi: np.ndarray,
    *,
    sign: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Deflection from ``v'' = sign * M / EI`` with zero displacement at both ends.

    The moment stations may repeat at a point load (the moment is continuous,
    so the duplicate values are averaged). The double trapezoidal integration
    is exact for a linear moment and very close for the sampled parabola of a
    uniform load.

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

    grid = np.asarray(xi, dtype=float) * length
    curvature = sign * np.interp(grid, unique_x, unique_m) / ei
    dx = np.diff(grid)
    slope = np.concatenate(([0.0], np.cumsum(0.5 * (curvature[:-1] + curvature[1:]) * dx)))
    values = np.concatenate(([0.0], np.cumsum(0.5 * (slope[:-1] + slope[1:]) * dx)))
    if length > 0.0:
        values -= values[-1] * grid / length
    return grid, values


def _row(history: np.ndarray, step: int) -> np.ndarray:
    values = np.asarray(history, dtype=float)
    return np.asarray(values[step], dtype=float)


def _global_dofs(row: np.ndarray, ndm: int, ndf: int) -> np.ndarray:
    """A result row (OpenSees DOF order, global sign already applied) as six slots.

    ``StaticResults.node_disp`` stores the runner's values after ``dof_signs``
    (``core.plane``), so unlike :func:`~opensees_studio.core.plane.from_solver_dofs`
    this does not flip a 2D rotation again.
    """
    out = np.zeros(6, dtype=float)
    for slot, value in zip(dof_indices(ndm, ndf), row, strict=False):
        out[slot] = float(value)
    return out


def _loads_are_scalable(project: Project, case: StaticCase) -> bool:
    series = {ts.id: ts for ts in project.time_series}
    patterns = {p.id: p for p in project.load_patterns}
    for pattern_id in case.pattern_ids:
        pattern = patterns.get(pattern_id)
        if not isinstance(pattern, PlainLoadPattern):
            continue
        series_value = series.get(pattern.time_series_id)
        if not isinstance(series_value, (LinearTimeSeries, ConstantTimeSeries)):
            return False
    return True


__all__ = [
    "ElementDiagramBundle",
    "ForceSeries",
    "LoadSegment",
    "PointLoad",
    "combine_element_bundles",
    "element_applied_loads",
    "element_deformation_curves",
    "element_diagram_bundle",
    "element_force_curves",
]
