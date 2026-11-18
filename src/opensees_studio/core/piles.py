"""Soil springs along a pile: p-y, t-z and q-z (OpenSees PySimple1, TzSimple1, QzSimple1).

A pile is a chain of frame members below the ground level. At every joint of it
in the soil, a zero-length element ties the joint to a fixed ground joint at the
same point with

* **p-y** springs in each horizontal direction — soft clay after Matlock (1970),
  ``pu = min((3 + γ' z / su + J z / D) su D, 9 su D)``, ``J = 0.5``,
  ``y50 = 2.5 ε50 D``; sand after API RP 2A, ``pu = min((C1 z + C2 D) γ' z,
  C3 D γ' z)`` with the curve ``A pu tanh(k z y / (A pu))``, ``A = max(0.9, 3 -
  0.8 z / D)``, so ``pult = A pu`` and ``y50 = atanh(0.5) A pu / (k z)``;
* a **t-z** spring along the axis — clay ``f = α su`` with API's ``α = 0.5 ψ^-0.5``
  (``ψ = su / sv' <= 1``, else ``0.5 ψ^-0.25``, at most 1), sand
  ``f = K sv' tan(φ - 5°)`` with ``K = 0.8``; ``z50 = 0.0025 D``;
* at the tip, a **q-z** spring — clay ``q = 9 su``, sand ``q = Nq sv'`` with API's
  ``Nq`` (8 at 20° to 50 at 40°); ``z50 = 0.0125 D``.

Each spring carries the soil of its joint's tributary length (half of each
member next to it, inside the soil). Depth ``z`` is measured down from the
ground level; ``sv' = γ' z`` (the effective vertical stress) summed over the layers above. Values are in the
project's units (``k`` is a force per length³, ``su`` a stress, ``γ'`` a force
per length³); angles in degrees.

No Qt, no OpenSees.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any, Literal

from opensees_studio.core.geometry.elements import ZeroLengthElement
from opensees_studio.core.geometry.node import Node
from opensees_studio.core.materials.library import PySimple1, QzSimple1, TzSimple1

SoilKind = Literal["clay", "sand"]

#: API RP 2A bearing factor Nq against the friction angle (degrees).
_NQ = ((20.0, 8.0), (25.0, 12.0), (30.0, 20.0), (35.0, 40.0), (40.0, 50.0))


@dataclass(frozen=True)
class SoilLayer:
    """One layer, from ``top`` to ``bottom`` depth below the ground level."""

    top: float
    bottom: float
    kind: SoilKind
    unit_weight: float
    """Effective unit weight γ' (submerged below the water table)."""
    su: float = 0.0
    """Undrained shear strength (clay)."""
    phi: float = 30.0
    """Friction angle, degrees (sand)."""
    eps50: float = 0.0
    """Strain at half the strength (clay); 0 = from su (0.02 soft, 0.01 medium, 0.005 stiff)."""
    k: float = 0.0
    """Initial modulus of subgrade reaction (sand), force / length³."""

    def __post_init__(self) -> None:
        if self.bottom <= self.top:
            raise ValueError("A soil layer's bottom must be below its top.")
        if self.kind == "clay" and self.su <= 0.0:
            raise ValueError("A clay layer needs its undrained strength su.")
        if self.kind == "sand" and (self.k <= 0.0 or not 15.0 <= self.phi <= 50.0):
            raise ValueError("A sand layer needs k > 0 and a friction angle of 15° to 50°.")


@dataclass(frozen=True)
class PileSpec:
    diameter: float
    ground_level: float
    """Elevation (Z) of the ground surface."""
    layers: tuple[SoilLayer, ...]
    stress_unit: float = 1.0
    """Size of a kPa in the project's stress unit: Matlock's ε50 bands are in kPa."""


@dataclass
class PileSprings:
    nodes: list[Node] = field(default_factory=list)
    materials: list[Any] = field(default_factory=list)
    elements: list[ZeroLengthElement] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _layer(spec: PileSpec, depth: float) -> SoilLayer | None:
    for layer in spec.layers:
        if layer.top <= depth <= layer.bottom:
            return layer
    return None


def effective_stress(spec: PileSpec, depth: float) -> float:
    """``sv'`` at ``depth``: γ' times thickness, summed over the layers above."""
    total = 0.0
    for layer in sorted(spec.layers, key=lambda layer: layer.top):
        if depth <= layer.top:
            break
        total += layer.unit_weight * (min(depth, layer.bottom) - layer.top)
    return total


def matlock_pu(layer: SoilLayer, depth: float, diameter: float) -> float:
    """Ultimate lateral resistance per unit length of soft clay (Matlock)."""
    su = layer.su
    shallow = (3.0 + layer.unit_weight * depth / su + 0.5 * depth / diameter) * su * diameter
    return min(shallow, 9.0 * su * diameter)


def api_sand_pu(layer: SoilLayer, depth: float, diameter: float, sigma: float) -> float:
    """Ultimate lateral resistance per unit length of sand (API RP 2A), before ``A``."""
    phi = math.radians(layer.phi)
    alpha, beta = phi / 2.0, math.radians(45.0) + phi / 2.0
    k0, ka = 0.4, math.tan(math.radians(45.0) - phi / 2.0) ** 2
    c1 = (math.tan(beta) ** 2 * math.tan(alpha)) / math.tan(beta - phi) + k0 * (
        math.tan(phi) * math.sin(beta) / (math.cos(alpha) * math.tan(beta - phi))
        + math.tan(beta) * (math.tan(phi) * math.sin(beta) - math.tan(alpha))
    )
    c2 = math.tan(beta) / math.tan(beta - phi) - ka
    c3 = ka * (math.tan(beta) ** 8 - 1.0) + k0 * math.tan(phi) * math.tan(beta) ** 4
    return min((c1 * depth + c2 * diameter) * sigma, c3 * diameter * sigma)


def api_alpha(su: float, sigma: float) -> float:
    """API adhesion factor ``α`` of clay, at most 1."""
    psi = su / sigma if sigma > 0.0 else 1.0
    alpha = 0.5 * psi**-0.5 if psi <= 1.0 else 0.5 * psi**-0.25
    return float(min(alpha, 1.0))


def api_nq(phi: float) -> float:
    """API RP 2A ``Nq`` against the friction angle, interpolated and capped."""
    if phi <= _NQ[0][0]:
        return _NQ[0][1]
    for (a, na), (b, nb) in itertools.pairwise(_NQ):
        if phi <= b:
            return na + (nb - na) * (phi - a) / (b - a)
    return _NQ[-1][1]


def _eps50(layer: SoilLayer, kpa: float) -> float:
    if layer.eps50 > 0.0:
        return layer.eps50
    su_kpa = layer.su / kpa
    return 0.02 if su_kpa < 48.0 else 0.01 if su_kpa < 96.0 else 0.005


def pile_springs(
    project: Any,
    element_ids: set[int],
    spec: PileSpec,
    *,
    first_node_id: int,
    first_material_id: int,
    first_element_id: int,
) -> PileSprings:
    """The ground joints, spring materials and zero-length elements of one pile.

    Raises:
        ValueError: no member of the selection reaches below the ground, or a
            joint in the soil lies in no layer.
    """
    if spec.diameter <= 0.0:
        raise ValueError("The pile diameter must be positive.")
    coords: dict[int, tuple[float, float, float]] = {
        n.id: (float(n.coords[0]), float(n.coords[1]), float(n.coords[2])) for n in project.nodes
    }
    members = [e for e in project.elements if e.id in element_ids and len(e.nodes) == 2]
    joints = sorted(
        {n for e in members for n in e.nodes if coords[n][2] <= spec.ground_level + 1e-9},
        key=lambda n: -coords[n][2],
    )
    if not joints:
        raise ValueError("None of the selected members reaches below the ground level.")
    elevations = [coords[n][2] for n in joints]
    tip = joints[-1]
    out = PileSprings()
    node_id, material_id, element_id = first_node_id, first_material_id, first_element_id
    area = math.pi * spec.diameter**2 / 4.0
    perimeter = math.pi * spec.diameter
    planar = project.ndm == 2
    for k, joint in enumerate(joints):
        z = spec.ground_level - elevations[k]
        # Half of each member next to the joint, inside the soil.
        above = min((elevations[k - 1] - elevations[k]) / 2.0, z) if k > 0 else 0.0
        below = (elevations[k] - elevations[k + 1]) / 2.0 if k + 1 < len(joints) else 0.0
        tributary = above + below
        depth = max(z, 1e-9)
        layer = _layer(spec, depth if k + 1 < len(joints) else depth - 1e-9)
        if layer is None:
            raise ValueError(f"Joint {joint} at depth {z:g} lies in no soil layer.")
        if tributary <= 0.0:
            continue
        sigma = effective_stress(spec, depth)
        if layer.kind == "clay":
            pu = matlock_pu(layer, depth, spec.diameter)
            y50 = 2.5 * _eps50(layer, spec.stress_unit) * spec.diameter
            py = PySimple1(id=material_id, soilType=1, pult=pu * tributary, Y50=y50, Cd=0.1, c=0.0)
            friction = api_alpha(layer.su, sigma) * layer.su
            tz_type: Literal[1, 2] = 1
        else:
            z_eff = max(depth, spec.diameter / 4.0)
            sigma_eff = max(sigma, effective_stress(spec, z_eff))
            pu = api_sand_pu(layer, z_eff, spec.diameter, sigma_eff)
            a_factor = max(0.9, 3.0 - 0.8 * z_eff / spec.diameter)
            pult = a_factor * pu
            y50 = math.atanh(0.5) * pult / (layer.k * z_eff)
            py = PySimple1(
                id=material_id, soilType=2, pult=pult * tributary, Y50=y50, Cd=0.1, c=0.0
            )
            friction = 0.8 * sigma_eff * math.tan(math.radians(layer.phi - 5.0))
            tz_type = 2
        py = py.model_copy(update={"name": f"p-y z={z:.3g}"})
        tz = TzSimple1(
            id=material_id + 1,
            name=f"t-z z={z:.3g}",
            soilType=tz_type,
            tult=max(friction * perimeter * tributary, 1e-12),
            z50=0.0025 * spec.diameter,
            c=0.0,
        )
        out.materials += [py, tz]
        ground = Node(id=node_id, coords=coords[joint], restraint=(True,) * 6)
        out.nodes.append(ground)
        mats: tuple[int, ...]
        dofs: tuple[int, ...]
        if planar:
            mats, dofs = (py.id, tz.id), (1, 2)
        else:
            mats, dofs = (py.id, py.id, tz.id), (1, 2, 3)
        out.elements.append(
            ZeroLengthElement(id=element_id, nodes=(ground.id, joint), material_ids=mats, dofs=dofs)
        )
        material_id += 2
        element_id += 1
        if joint == tip:
            if layer.kind == "clay":
                q = 9.0 * layer.su
                qz_type: Literal[1, 2] = 1
            else:
                q = api_nq(layer.phi) * sigma
                qz_type = 2
            qz = QzSimple1(
                id=material_id,
                name="q-z tip",
                qzType=qz_type,
                qult=q * area,
                Z50=0.0125 * spec.diameter,
                suction=0.0,
                c=0.0,
            )
            out.materials.append(qz)
            out.elements.append(
                ZeroLengthElement(
                    id=element_id,
                    nodes=(ground.id, joint),
                    material_ids=(qz.id,),
                    dofs=(2 if planar else 3,),
                )
            )
            material_id += 1
            element_id += 1
        node_id += 1
    out.notes.append(
        f"{len(out.nodes)} soil joint(s) along the pile, "
        f"{len(out.elements)} zero-length spring element(s)."
    )
    return out
