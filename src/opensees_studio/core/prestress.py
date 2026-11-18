"""Post-tensioning tendons as equivalent loads (load balancing).

A tendon of force ``P(x)`` along the parabola ``e(x)`` (local y) pushes on the
concrete it runs through:

* at each anchorage, the force ``P`` along the tendon, at the eccentricity
  ``e``: an axial force ``P``, a shear ``P e'`` and a moment ``-P e`` about the
  centroid at end i (``+P e`` at end j, where the force points the other way);
* along its curve, the pressure ``P e''`` towards the centre of curvature (the
  uniform ``8 P f / L²`` of a parabola of sag ``f``), and friction along the
  member, ``(P_j - P_i) / L``.

``P(x) = P0 exp(-(μ α + k d))`` from each stressing end (α the angle change, d
the distance), the larger of the two when stressed from both ends, times
``1 - long_term_loss``. The lateral pressure uses the mean force along the
member, so with friction the loads balance to the second order of the loss.
The tendon is not a member of the model: its own elastic shortening loss is
part of ``long_term_loss``.

No Qt, no OpenSees.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.loads import TendonLoad, UniformElementLoad


class PrestressError(ValueError):
    """A tendon that cannot be applied."""


@dataclass(frozen=True)
class TendonProfile:
    """The tendon of one member, resolved: geometry and force along it."""

    length: float
    sag: float
    """``f = (e_i + e_j) / 2 - e_mid``: positive for a tendon draped towards -y."""
    force_i: float
    force_j: float
    force_mean: float

    def eccentricity(self, x: float, e_i: float, e_j: float) -> float:
        span = self.length
        return e_i + (e_j - e_i) * x / span - 4.0 * self.sag * x * (span - x) / span**2

    def slope(self, x: float, e_i: float, e_j: float) -> float:
        span = self.length
        return (e_j - e_i) / span - 4.0 * self.sag * (span - 2.0 * x) / span**2


def _member(project: object, load: TendonLoad) -> tuple[object, tuple[np.ndarray, ...]]:
    element = next((e for e in project.elements if e.id == load.element_id), None)  # type: ignore[attr-defined]
    if element is None or len(getattr(element, "nodes", ())) != 2:
        raise PrestressError(f"Tendon on element {load.element_id}: not a frame member.")
    coords = {n.id: n.coords for n in project.nodes}  # type: ignore[attr-defined]
    axes = frame_local_axes(
        project.ndm,  # type: ignore[attr-defined]
        coords[element.nodes[0]],
        coords[element.nodes[1]],
        float(getattr(element, "local_axis_angle", 0.0) or 0.0),
    )
    if axes is None:
        raise PrestressError(f"Tendon on element {load.element_id}: the member has no length.")
    return element, axes


def tendon_profile(project: object, load: TendonLoad) -> TendonProfile:
    """Length, sag and the force at both ends and on average."""
    element, _axes = _member(project, load)
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}  # type: ignore[attr-defined]
    span = float(np.linalg.norm(coords[element.nodes[1]] - coords[element.nodes[0]]))  # type: ignore[attr-defined]
    sag = 0.5 * (load.e_i + load.e_j) - load.e_mid
    curvature = abs(8.0 * sag / span**2)

    def from_end(x: float, end: float) -> float:
        distance = abs(x - end)
        return load.force * float(
            np.exp(-(load.friction * curvature * distance + load.wobble * distance))
        )

    def force(x: float) -> float:
        if load.stressed_from == "i":
            value = from_end(x, 0.0)
        elif load.stressed_from == "j":
            value = from_end(x, span)
        else:
            value = max(from_end(x, 0.0), from_end(x, span))
        return value * (1.0 - load.long_term_loss)

    points = np.linspace(0.0, span, 41)
    values = np.array([force(x) for x in points])
    mean = float(np.trapezoid(values, points) / span)
    return TendonProfile(
        length=span, sag=sag, force_i=force(0.0), force_j=force(span), force_mean=mean
    )


def tendon_equivalent_loads(
    project: object, load: TendonLoad
) -> tuple[int, np.ndarray, int, np.ndarray, UniformElementLoad]:
    """``(node i, load i, node j, load j, uniform)``: the tendon's push on the member.

    The nodal loads are global, in storage order (Fx, Fy, Fz, Mx, My, Mz); the
    uniform load is in the member's local axes.
    """
    element, axes = _member(project, load)
    profile = tendon_profile(project, load)
    span = profile.length
    rotation = np.vstack(axes)  # rows: local x, y, z in global coordinates
    slope_i = profile.slope(0.0, load.e_i, load.e_j)
    slope_j = profile.slope(span, load.e_i, load.e_j)
    p_i, p_j = profile.force_i, profile.force_j
    # Forces on the concrete at the anchorages, local (N, Vy, Vz) and (T, My, Mz).
    ends = [
        (np.array([p_i, p_i * slope_i, 0.0]), np.array([0.0, 0.0, -p_i * load.e_i])),
        (np.array([-p_j, -p_j * slope_j, 0.0]), np.array([0.0, 0.0, p_j * load.e_j])),
    ]
    nodal = [np.concatenate([rotation.T @ force, rotation.T @ moment]) for force, moment in ends]
    uniform = UniformElementLoad(
        element_id=load.element_id,
        wy=profile.force_mean * 8.0 * profile.sag / span**2,
        wx=(p_j - p_i) / span,
    )
    nodes = element.nodes  # type: ignore[attr-defined]
    return nodes[0], nodal[0], nodes[1], nodal[1], uniform
