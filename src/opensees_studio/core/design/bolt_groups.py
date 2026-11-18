"""Bolted connections: prying action and eccentrically loaded bolt groups (LRFD).

* **Prying action** (AISC Steel Construction Manual, 15th ed., Part 9): a tee
  flange or end plate of thickness ``t`` and tensile strength ``Fu`` with bolts
  of diameter ``db`` in holes ``d'`` at a pitch ``p`` (tributary width per bolt),
  ``b`` from the bolt line to the face of the stem and ``a`` to the edge.
  ``b' = b - db/2``, ``a' = min(a, 1.25 b) + db/2``, ``ρ = b'/a'``,
  ``δ = 1 - d'/p``, ``tc = √(4 B b' / (φ p Fu))`` with ``φ = 0.90`` and ``B``
  the bolt's available tension; ``α' = ((tc/t)² - 1) / (δ (1 + ρ))`` clipped to
  [0, 1], ``Q = (t/tc)² (1 + δ α') ≤ 1``, and the available tension per bolt
  with prying is ``B Q``. The thickness with no prying is
  ``√(4 T b' / (φ p Fu (1 + δ)))`` for the demand ``T`` per bolt.
* **Eccentric bolt group** (elastic method, Manual Part 7): bolts at ``(x, y)``
  about the group's centroid, a force ``(Px, Py)`` at ``(ex, ey)``; each bolt
  takes ``P/n`` plus the torsion ``M r / Ip`` (``Ip = Σ r²``). Conservative next
  to the instantaneous centre of rotation; the bolt with the largest resultant
  governs against the single-bolt strength (shear, bearing).

No Qt, no OpenSees.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

PHI_PRYING = 0.90


@dataclass(frozen=True)
class PryingResult:
    b_prime: float
    a_prime: float
    rho: float
    delta: float
    tc: float
    alpha_prime: float
    q: float
    available: float
    """Available tension per bolt with prying, ``B Q``."""
    t_no_prying: float
    """Thickness that needs no prying for the demand."""

    def ratio(self, demand: float) -> float:
        return demand / self.available if self.available > 0.0 else math.inf


def prying_action(
    *,
    t: float,
    fu: float,
    b: float,
    a: float,
    db: float,
    hole: float,
    pitch: float,
    bolt_tension: float,
    demand: float,
) -> PryingResult:
    """AISC Manual Part 9 prying: the available tension per bolt of a flange of thickness ``t``."""
    if min(t, fu, b, a, db, pitch, bolt_tension) <= 0.0:
        raise ValueError("Every dimension, Fu and the bolt tension must be positive.")
    b_prime = b - db / 2.0
    a_prime = min(a, 1.25 * b) + db / 2.0
    rho = b_prime / a_prime
    delta = 1.0 - hole / pitch
    tc = math.sqrt(4.0 * bolt_tension * b_prime / (PHI_PRYING * pitch * fu))
    alpha = ((tc / t) ** 2 - 1.0) / (delta * (1.0 + rho)) if delta > 0.0 else 1.0
    alpha = min(max(alpha, 0.0), 1.0)
    q = min(1.0, (t / tc) ** 2 * (1.0 + delta * alpha))
    t_free = math.sqrt(4.0 * demand * b_prime / (PHI_PRYING * pitch * fu * (1.0 + delta)))
    return PryingResult(
        b_prime=b_prime,
        a_prime=a_prime,
        rho=rho,
        delta=delta,
        tc=tc,
        alpha_prime=alpha,
        q=q,
        available=bolt_tension * q,
        t_no_prying=t_free,
    )


@dataclass(frozen=True)
class BoltGroupResult:
    forces: tuple[float, ...]
    """Resultant on each bolt, in the order given."""
    governing: int
    max_force: float

    def ratio(self, bolt_strength: float) -> float:
        return self.max_force / bolt_strength if bolt_strength > 0.0 else math.inf


def eccentric_bolt_group(
    bolts: Sequence[tuple[float, float]],
    *,
    px: float,
    py: float,
    ex: float = 0.0,
    ey: float = 0.0,
) -> BoltGroupResult:
    """Elastic method: the force on each bolt of a group loaded at ``(ex, ey)``.

    Positions and eccentricities are measured from any origin; the group's
    centroid is found first. The moment about it is ``Py (ex - xc) - Px (ey - yc)``.
    """
    if not bolts:
        raise ValueError("A bolt group needs bolts.")
    n = len(bolts)
    xc = sum(x for x, _ in bolts) / n
    yc = sum(y for _, y in bolts) / n
    moment = py * (ex - xc) - px * (ey - yc)
    ip = sum((x - xc) ** 2 + (y - yc) ** 2 for x, y in bolts)
    forces: list[float] = []
    for x, y in bolts:
        rx = px / n - (moment * (y - yc) / ip if ip > 0.0 else 0.0)
        ry = py / n + (moment * (x - xc) / ip if ip > 0.0 else 0.0)
        forces.append(math.hypot(rx, ry))
    governing = max(range(n), key=lambda k: forces[k])
    return BoltGroupResult(forces=tuple(forces), governing=governing, max_force=forces[governing])
