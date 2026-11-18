"""Reading influence lines out of an influence-line run, and a vehicle's extremes.

An :class:`~opensees_studio.services.results.InfluenceLineResults` holds every
response at every stop. :func:`influence_line` picks one of them — a joint's
displacement, a support's reaction, or a member's end force in the force
diagram's sign convention (end j reversed, as everywhere a diagram is drawn) —
and scales it to a **unit** load acting in the sense of the case's load, so an
axle of ``P`` produces ``P`` times it. :func:`vehicle_envelope` hands that line
to :func:`core.influence.moving_load_envelope`.

No Qt. OpenSees is not needed: the results come in.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

import numpy as np

from opensees_studio.core.influence import MovingLoadEnvelope, moving_load_envelope
from opensees_studio.core.plane import dof_indices
from opensees_studio.services.results import InfluenceLineResults

Quantity = Literal["displacement", "reaction", "force"]

#: Member force component → localForce index at end i (3D, 2D); end j adds 6 / 3.
FORCE_COMPONENTS: dict[str, tuple[int, int | None]] = {
    "N": (0, 0),
    "V2": (1, 1),
    "V3": (2, None),
    "T": (3, None),
    "M2": (4, None),
    "M3": (5, 2),
}


def influence_line(
    project: Any,
    results: InfluenceLineResults,
    quantity: Quantity,
    target: int,
    component: str,
    *,
    end: Literal["i", "j"] = "i",
) -> np.ndarray:
    """One response at every stop, for a unit load in the sense of the case's load.

    ``component`` is a DOF label of the model (``Ux``, ``Uz``, ``Ry`` …) for a
    displacement or a reaction, and one of :data:`FORCE_COMPONENTS` for a
    member force.

    Raises:
        KeyError: the joint, member or component has no result.
    """
    scale = 1.0 / abs(results.load)
    if quantity in ("displacement", "reaction"):
        table = results.node_disp if quantity == "displacement" else results.node_reaction
        if target not in table:
            raise KeyError(f"Joint {target} has no result.")
        labels = dof_labels(project)
        if component not in labels:
            raise KeyError(f"{component} is not a DOF of this model ({', '.join(labels)}).")
        return np.asarray(table[target][:, labels.index(component)], dtype=float) * scale
    if target not in results.element_forces:
        raise KeyError(f"Member {target} has no end forces.")
    forces = np.asarray(results.element_forces[target], dtype=float)
    three_d = forces.shape[1] >= 12
    index = FORCE_COMPONENTS.get(component, (None, None))[0 if three_d else 1]
    if index is None:
        raise KeyError(f"{component} is not a force of a {'3D' if three_d else '2D'} member.")
    if end == "i":
        return forces[:, index] * scale
    offset = 6 if three_d else 3
    # The diagram's sign: OpenSees reports end j's force with the opposite sense.
    return -forces[:, index + offset] * scale


def dof_labels(project: Any) -> list[str]:
    names = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")
    return [names[slot] for slot in dof_indices(project.ndm, project.ndf)]


def vehicle_envelope(
    results: InfluenceLineResults, line: Sequence[float] | np.ndarray, axles: Sequence[Any]
) -> MovingLoadEnvelope:
    """The extremes of ``line`` (a unit influence line) under ``axles``, both ways."""
    return moving_load_envelope(results.distances, line, axles)
