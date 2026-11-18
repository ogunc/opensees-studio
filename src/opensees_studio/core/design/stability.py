"""AISC 360 Chapter C helpers: notional loads and the stiffness reduction ``tau_b``.

The Direct Analysis Method needs two things a plain second-order analysis does
not provide by itself:

* **notional loads** - a lateral force of ``Ni = 0.002 alpha Yi`` at every
  storey, where ``Yi`` is the gravity load on that storey and ``alpha`` is 1.0
  in LRFD and 1.6 in ASD (AISC 360-16 C2-1, C2.2b);
* **stiffness reduction** - ``tau_b`` on the flexural stiffness of members whose
  required axial strength exceeds half their yield strength (C2.3);
* **P-delta amplification** - ``B1`` on the moments of a member in compression
  when the analysis did not include member curvature (A-8-3, C2.1b of the 2016
  edition).

This module builds the first and computes the second. It does not run an
analysis: the caller adds the returned ``PlainLoadPattern`` to the cases that
represent the Direct Analysis Method, and applies ``tau_b`` through the frame
property modifiers. Keeping it here lets the GUI, a script and a future design
runner use the same numbers.

The gravity load of a storey comes from, in order:

1. the project's mass source, when it has one (the weight it already turns into
   mass);
2. the self weight plus the load patterns whose names read as Dead or Live;
3. the vertical component of the effective nodal masses times ``g``, as a last
   resort for a model that only carries typed masses.

No Qt, no OpenSees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opensees_studio.core.loads import NodalLoad, PlainLoadPattern
from opensees_studio.core.mass_source import (
    effective_nodal_masses,
    pattern_weight_per_node,
    self_weight_per_node,
    source_weight_per_node,
)
from opensees_studio.core.plane import VERTICAL_AXIS
from opensees_studio.core.storeys import (
    base_elevation,
    elevation_tolerance,
    nodes_at_elevation,
    storey_levels,
)
from opensees_studio.core.units import gravity

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

#: AISC 360-16 C2-1: notional load as a fraction of the storey gravity load.
NOTIONAL_FRACTION = 0.002
#: C2-1: ``alpha`` for LRFD load combinations.
ALPHA_LRFD = 1.0
#: C2-1: ``alpha`` for ASD load combinations (1.6 times the service gravity).
ALPHA_ASD = 1.6


def notional_alpha(method: str) -> float:
    """C2-1 ``alpha`` for a design method: 1.0 in LRFD, 1.6 in ASD."""
    name = method.strip().upper()
    if name == "LRFD":
        return ALPHA_LRFD
    if name == "ASD":
        return ALPHA_ASD
    raise ValueError(f"Unknown design method {method!r}: use 'LRFD' or 'ASD'.")


def tau_b(pr: float, py: float, *, alpha: float = ALPHA_LRFD) -> float:
    """C2.3 stiffness reduction factor for a member with axial force ``pr``.

    ``tau_b = 1.0`` while ``alpha Pr / Py <= 0.5``; above that it is
    ``4 (alpha Pr/Py) (1 - alpha Pr/Py)``. ``alpha`` is 1.0 in LRFD and 1.6 in
    ASD (C2-1), because ``pr`` is the service axial force there. The caller
    applies ``tau_b`` to the member's flexural stiffness (and, for a
    beam-column, may also apply it to the axial one as the Direct Analysis
    Method permits).
    """
    if py <= 0.0:
        return 1.0
    ratio = alpha * max(0.0, pr) / py
    if ratio <= 0.5:
        return 1.0
    return max(0.0, min(1.0, 4.0 * ratio * (1.0 - ratio)))


def notional_factor(*, method: str = "LRFD") -> float:
    """The C2.2b notional-load fraction for a design method, ``0.002 alpha``."""
    return NOTIONAL_FRACTION * notional_alpha(method)


def pe1(elastic_modulus: float, inertia: float, length: float, *, k: float = 1.0) -> float:
    """A-8-5: elastic critical buckling strength in the plane of bending.

    ``Pe1 = pi^2 EI / (K1 L)^2``. Pass ``EI*``: ``0.8 tau_b EI`` for the direct
    analysis method, ``EI`` for the effective length and first-order methods.
    """
    if length <= 0.0 or k <= 0.0:
        raise ValueError("The effective length used for Pe1 must be positive.")
    return math.pi**2 * elastic_modulus * inertia / (k * length) ** 2


def b1(pr: float, pe: float, *, alpha: float = ALPHA_LRFD) -> float:
    """A-8-3: P-delta amplifier of a member in compression, with ``Cm = 1.0``.

    ``B1 = Cm / (1 - alpha Pr / Pe1) >= 1``. ``Cm = 1.0`` is the conservative
    value A-8-4(b) allows for members with transverse loading between supports,
    so this function never underestimates the amplification. Tension or zero
    axial force gives 1.0 (A-8-1); a member at or beyond its elastic critical
    load gives infinity.
    """
    if pr <= 0.0:
        return 1.0
    if pe <= 0.0:
        return math.inf
    denominator = 1.0 - alpha * pr / pe
    if denominator <= 0.0:
        return math.inf
    return max(1.0, 1.0 / denominator)


def gravity_weight_per_node(project: Project) -> dict[int, float]:
    """Node id -> downward gravity weight used for the notional loads.

    A mass source is authoritative, because it is what the solver turns into
    mass. Without one, the model's self weight and its Dead/Live patterns are
    summed; typed masses are the last resort.
    """
    if project.mass_source is not None:
        weighted = source_weight_per_node(project, project.mass_source)
        if weighted:
            return weighted

    from opensees_studio.core.combinations import guess_load_role

    weights = dict(self_weight_per_node(project))
    for pattern in project.load_patterns:
        if not isinstance(pattern, PlainLoadPattern):
            continue
        if guess_load_role(pattern.name) not in ("D", "L"):
            continue
        for nid, value in pattern_weight_per_node(project, pattern).items():
            weights[nid] = weights.get(nid, 0.0) + abs(float(value))

    if any(value > 0.0 for value in weights.values()):
        return {nid: value for nid, value in weights.items() if value > 0.0}

    masses = effective_nodal_masses(project)
    g = gravity(project.meta.units)
    return {
        nid: float(mass[VERTICAL_AXIS]) * g
        for nid, mass in masses.items()
        if float(mass[VERTICAL_AXIS]) > 0.0
    }


@dataclass(frozen=True)
class StoreyNotional:
    """One storey's share of the notional loads."""

    name: str
    elevation: float
    weight: float
    force: float
    loads: tuple[NodalLoad, ...]


def storey_node_levels(project: Project) -> list[tuple[str, float, tuple[int, ...]]]:
    """``(name, elevation, node ids)`` of every storey, or of every elevation above the base."""
    levels = storey_levels(project)
    if levels:
        return [
            (level.storey.name or f"Storey {k}", level.storey.elevation, level.nodes)
            for k, level in enumerate(levels, start=1)
        ]
    base = base_elevation(project)
    tol = elevation_tolerance(project)
    weights = {n.id: float(n.coords[VERTICAL_AXIS]) for n in project.nodes}
    elevations = sorted(
        {z for z in weights.values() if z > base + tol},
    )
    return [
        (f"Level {k}", z, tuple(nodes_at_elevation(project, z)))
        for k, z in enumerate(elevations, start=1)
    ]


def storey_notional_loads(
    project: Project,
    *,
    factor: float | None = None,
    method: str = "LRFD",
    direction: int = 0,
) -> list[StoreyNotional]:
    """The notional load of every storey, with the nodal loads that carry it.

    ``factor`` overrides the C2-1 value ``0.002 alpha`` (``method`` chooses
    ``alpha``: 1.0 in LRFD, 1.6 in ASD). ``direction`` is the global lateral
    axis (0 = X, 1 = Y; a 2D model has only X). Each storey's force is shared
    between its joints in proportion to their gravity weight.
    """
    if direction not in (0, 1):
        raise ValueError("A notional load acts along X (0) or Y (1).")
    if project.ndm == 2 and direction != 0:
        raise ValueError("A 2D model has only the global X direction.")
    fraction = notional_factor(method=method) if factor is None else factor
    if fraction <= 0.0:
        raise ValueError("The notional-load factor must be positive.")

    weights = gravity_weight_per_node(project)
    out: list[StoreyNotional] = []
    for name, elevation, node_ids in storey_node_levels(project):
        shares = [max(0.0, weights.get(nid, 0.0)) for nid in node_ids]
        total = float(sum(shares))
        if total <= 0.0:
            continue
        force = fraction * total
        load_shares = [force * share / total for share in shares]
        loads: list[NodalLoad] = []
        for nid, share in zip(node_ids, load_shares, strict=True):
            if share == 0.0:
                continue
            forces = [0.0] * 6
            forces[direction] = share
            loads.append(NodalLoad(node_id=nid, forces=tuple(forces)))  # type: ignore[arg-type]
        out.append(
            StoreyNotional(
                name=name,
                elevation=elevation,
                weight=total,
                force=force,
                loads=tuple(loads),
            )
        )
    return out


def notional_loads(
    project: Project,
    *,
    factor: float | None = None,
    method: str = "LRFD",
    direction: int = 0,
) -> list[NodalLoad]:
    """Every nodal load of the notional pattern, flattened."""
    return [
        load
        for storey in storey_notional_loads(
            project, factor=factor, method=method, direction=direction
        )
        for load in storey.loads
    ]


def notional_pattern(
    project: Project,
    *,
    pattern_id: int,
    time_series_id: int,
    name: str | None = None,
    factor: float | None = None,
    method: str = "LRFD",
    direction: int = 0,
) -> PlainLoadPattern:
    """A Plain pattern holding the notional loads of one direction."""
    axis = "XY"[direction]
    return PlainLoadPattern(
        id=pattern_id,
        name=name or f"NOTIONAL {axis}",
        time_series_id=time_series_id,
        nodal_loads=notional_loads(project, factor=factor, method=method, direction=direction),
    )
