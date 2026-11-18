"""Temperature loads on elastic frame members: fixed-end forces and equivalent loads.

OpenSees' elastic beam-columns take no thermal load. A temperature change is
therefore applied the way a hand analysis would: the member is first held fixed
at both ends, where its *fixed-end forces* ``f_FE`` arise, then released by
applying ``-f_FE`` to the structure. The end forces the member really carries
are those OpenSees reports for its displacements plus ``f_FE``:

* uniform ``ΔT``: ``N = EA (ε - α ΔT)``, so a fixed member is compressed by
  ``EA α ΔT`` and a free one only grows by ``α ΔT L``;
* a gradient ``g`` across the depth: ``M = EI (κ - α g)``, a constant moment
  ``EI α g`` in a fixed member, and pure curvature ``α g`` in a free one.

``f_FE`` is in OpenSees' ``localForce`` layout and sign (the forces acting on
the member at its ends, in its local axes): ``(N, V, M)`` per end in 2D,
``(N, Vy, Vz, T, My, Mz)`` per end in 3D. A section moment ``M`` appears as
``-M`` at end i and ``+M`` at end j, as in the element's basic system.

Only elastic sections, and members without end releases, end offsets or an
insertion point (their fixed-end forces would need the condensed stiffness).
Property modifiers on A and the inertias apply.

No Qt, no OpenSees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.sections import ElasticSection

if TYPE_CHECKING:
    from opensees_studio.core.loads import TemperatureLoad
    from opensees_studio.core.project import Project


class ThermalLoadError(ValueError):
    """A temperature load on a member this method cannot take."""


def _member(project: Project, load: TemperatureLoad) -> tuple[Any, ElasticSection]:
    from opensees_studio.core.geometry.elements import ElasticBeamColumn

    element = next((e for e in project.elements if e.id == load.element_id), None)
    if not isinstance(element, ElasticBeamColumn):
        raise ThermalLoadError(
            f"Element {load.element_id}: temperature loads take elastic beam-columns only."
        )
    if (
        element.releases.any
        or not element.end_offsets.is_default()
        or not element.insertion.is_default()
    ):
        raise ThermalLoadError(
            f"Element {load.element_id}: temperature loads take members without end releases, "
            "end offsets or an insertion point."
        )
    section = next((s for s in project.sections if s.id == element.section_id), None)
    if not isinstance(section, ElasticSection):
        raise ThermalLoadError(
            f"Element {load.element_id}: temperature loads need an elastic section."
        )
    return element, section


def fixed_end_forces(project: Project, load: TemperatureLoad) -> np.ndarray:
    """``f_FE`` of a member held fixed at both ends (see the module docstring)."""
    element, section = _member(project, load)
    mods = element.modifiers
    e = section.E
    axial = e * section.A * mods.area * load.alpha * load.uniform
    # Section moments of the fixed member: about z from the gradient along y,
    # about y from the gradient along z (OpenSees: ε = ε0 - y κz + z κy).
    moment_z = e * section.Iz * mods.i33 * load.alpha * load.gradient_y
    if project.ndm == 2:
        return np.array([axial, 0.0, -moment_z, -axial, 0.0, moment_z])
    iy = section.Iy if section.Iy is not None else section.Iz
    moment_y = -e * iy * mods.i22 * load.alpha * load.gradient_z
    out = np.zeros(12)
    out[0], out[6] = axial, -axial
    out[5], out[11] = -moment_z, moment_z
    out[4], out[10] = -moment_y, moment_y
    return out


def equivalent_nodal_loads(
    project: Project, load: TemperatureLoad
) -> tuple[int, np.ndarray, int, np.ndarray]:
    """``(node i, load i, node j, load j)``: ``-f_FE`` in global storage order (Fx..Mz)."""
    element, _ = _member(project, load)
    coords = {n.id: n.coords for n in project.nodes}
    axes = frame_local_axes(project.ndm, coords[element.nodes[0]], coords[element.nodes[1]])
    if axes is None:
        raise ThermalLoadError(f"Element {load.element_id} has no length.")
    rotation = np.vstack(axes)  # rows: local x, y, z in global coordinates
    fe = fixed_end_forces(project, load)
    if project.ndm == 2:
        ends = [(fe[0], fe[1], 0.0, 0.0, 0.0, fe[2]), (fe[3], fe[4], 0.0, 0.0, 0.0, fe[5])]
    else:
        ends = [tuple(fe[0:6]), tuple(fe[6:12])]
    loads = []
    for n, v_y, v_z, t, m_y, m_z in ends:
        force = rotation.T @ np.array([n, v_y, v_z])
        moment = rotation.T @ np.array([t, m_y, m_z])
        loads.append(-np.concatenate([force, moment]))
    return element.nodes[0], loads[0], element.nodes[1], loads[1]
