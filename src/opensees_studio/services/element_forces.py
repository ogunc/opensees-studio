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
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from opensees_studio.core import Project
from opensees_studio.services.results import StaticResults


class ForceComponent(Enum):
    """Which force component to plot."""

    N = "N"        # axial
    V2 = "V2"      # shear in local y (in-plane shear for 2D)
    V3 = "V3"      # shear in local z
    T = "T"        # torsion
    M2 = "M2"      # moment about local y
    M3 = "M3"      # moment about local z (in-plane moment for 2D)


# Map (component, end) → index into the local-force vector for 3D and 2D.
_INDEX_3D = {
    (ForceComponent.N,  "i"): 0,  (ForceComponent.N,  "j"): 6,
    (ForceComponent.V2, "i"): 1,  (ForceComponent.V2, "j"): 7,
    (ForceComponent.V3, "i"): 2,  (ForceComponent.V3, "j"): 8,
    (ForceComponent.T,  "i"): 3,  (ForceComponent.T,  "j"): 9,
    (ForceComponent.M2, "i"): 4,  (ForceComponent.M2, "j"): 10,
    (ForceComponent.M3, "i"): 5,  (ForceComponent.M3, "j"): 11,
}
_INDEX_2D = {
    (ForceComponent.N,  "i"): 0,  (ForceComponent.N,  "j"): 3,
    (ForceComponent.V2, "i"): 1,  (ForceComponent.V2, "j"): 4,
    (ForceComponent.M3, "i"): 2,  (ForceComponent.M3, "j"): 5,
}

# Truss elements expose a different localForce layout than frames:
# 2D truss → 4-vector [N_i, 0, N_j, 0]  (only axial; shears are zero-padded)
# 3D truss → 6-vector [N_i, 0, 0, N_j, 0, 0]
# So we map only the N component; other components return None.
_INDEX_TRUSS_2D = {
    (ForceComponent.N, "i"): 0,  (ForceComponent.N, "j"): 2,
}
_INDEX_TRUSS_3D = {
    (ForceComponent.N, "i"): 0,  (ForceComponent.N, "j"): 3,
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
    """

    component: ForceComponent
    element_ids: np.ndarray
    values_i: np.ndarray
    values_j: np.ndarray
    abs_max: float


def extract_diagram_data(
    project: Project,
    results: StaticResults,
    component: ForceComponent,
    *,
    step: int = -1,
) -> DiagramData:
    """Build a :class:`DiagramData` for a given component and analysis step.

    Skips elements that:
    - Have no entry in ``results.element_forces`` (e.g. didn't return forces).
    - Don't expose the requested component in their force vector
      (e.g. asking for V3 on a 2D element with only 6 components).
    """
    ids: list[int] = []
    vi: list[float] = []
    vj: list[float] = []

    # Local import to avoid a cycle (element classes live in core.geometry).
    from opensees_studio.core import CorotTrussElement, TrussElement
    truss_types = (TrussElement, CorotTrussElement)

    for el in project.elements:
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
    return DiagramData(
        component=component,
        element_ids=ids_arr,
        values_i=vi_arr,
        values_j=vj_arr,
        abs_max=abs_max,
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
