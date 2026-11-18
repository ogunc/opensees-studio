"""Single-plate shear connections (shear tabs): AISC Manual Part 10, AISC 360 Chapter J.

A plate welded to the support (a column flange or web, or a girder web) and
bolted to the web of a simply connected beam, in the **conventional
configuration**: one vertical row of ``n`` bolts at spacing ``s``, the bolt line
``a`` from the weld, edge distances ``Lev`` (vertical) and ``Leh`` (horizontal).

Every limit state the Manual lists for it, each from :mod:`core.design.chapter_j`:

* **Bolt shear** (J3.1) on the most loaded bolt of the group under the end
  shear at an eccentricity ``a`` (elastic method,
  :func:`core.design.bolt_groups.eccentric_bolt_group`). The Manual allows a
  smaller eccentricity for the conventional configuration; taking the full
  ``a`` is conservative.
* **Bolt bearing and tearout** (J3.6) on the plate and on the beam web, with
  the vertical edge distance ``Lev`` for every bolt (conservative).
* **Plate shear yielding and rupture** (J4.3, J4.4) and **block shear** (J4.5)
  of the plate.
* **Weld** (J2.4): fillet welds on both sides of the plate, full plate length;
  and the Manual's detailing rule ``w >= 5/8 tp``, which makes the weld stronger
  than the plate so the plate yields first.
* **Ductility** of the conventional configuration: ``tp <= d / 2 + 1/16 in``
  for the plate, so the bolts do not fracture before the plate deforms
  (reported as a ratio).

Axial force in the beam (a collector or drag strut) is not checked here.
No Qt, no OpenSees.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from opensees_studio.core.design.bolt_groups import eccentric_bolt_group
from opensees_studio.core.design.chapter_j import (
    block_shear_strength,
    bolt_bearing_strength,
    bolt_shear_strength,
    fillet_weld_strength,
    plate_shear_rupture,
    plate_shear_yielding,
)
from opensees_studio.core.design.shear_tab_model import BOLT_GRADES, ShearTabDesign

__all__ = ["BOLT_GRADES", "ShearTabDesign", "ShearTabResult", "TabCheck", "check_shear_tab"]


@dataclass
class TabCheck:
    name: str
    ratio: float
    reference: str


@dataclass
class ShearTabResult:
    checks: list[TabCheck] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def governing(self) -> TabCheck | None:
        return max(self.checks, key=lambda c: c.ratio, default=None)


def check_shear_tab(
    tab: ShearTabDesign,
    *,
    vu: float,
    fnv: float,
    plate_fy: float,
    plate_fu: float,
    web_thickness: float,
    web_fu: float,
    hole_extra: float,
    inch: float,
    method: str = "LRFD",
) -> ShearTabResult:
    """Every limit state of the tab under the end shear ``vu`` (consistent units).

    ``hole_extra`` is the standard hole's oversize (1/16 in in the project's
    length unit); ``inch`` is one inch in it, for the ductility rule.
    """
    out = ShearTabResult()
    vu = abs(vu)
    d = tab.bolt_diameter
    hole = d + hole_extra
    n = tab.bolts

    def ratio(available: float) -> float:
        return vu / available if available > 0.0 else float("inf")

    # Bolt shear, most loaded bolt of the group with the shear at the weld line.
    ys = [k * tab.spacing for k in range(n)]
    group = eccentric_bolt_group([(0.0, y) for y in ys], px=0.0, py=vu, ex=-tab.weld_to_bolts)
    one_bolt = bolt_shear_strength(fnv=fnv, diameter=d, count=1, method=method)  # type: ignore[arg-type]
    out.checks.append(
        TabCheck(
            "Bolt shear (most loaded bolt, e = a)",
            group.max_force / one_bolt.available if one_bolt.available > 0.0 else float("inf"),
            "J3.1, Manual Part 7 elastic method",
        )
    )
    for name, thickness, fu in (
        ("Bolt bearing on the plate", tab.tp, plate_fu),
        ("Bolt bearing on the beam web", web_thickness, web_fu),
    ):
        bearing = bolt_bearing_strength(
            fu=fu,
            thickness=thickness,
            diameter=d,
            count=n,
            edge_distance=tab.edge_vertical,
            hole_diameter=hole,
            method=method,  # type: ignore[arg-type]
        )
        out.checks.append(TabCheck(name, ratio(bearing.available), bearing.equation))

    length = tab.length
    agv = length * tab.tp
    anv = (length - n * (hole + hole_extra)) * tab.tp
    yielding = plate_shear_yielding(fy=plate_fy, agv=agv, method=method)  # type: ignore[arg-type]
    out.checks.append(TabCheck("Plate shear yielding", ratio(yielding.available), "J4.3"))
    if anv > 0.0:
        rupture = plate_shear_rupture(fu=plate_fu, anv=anv, method=method)  # type: ignore[arg-type]
        out.checks.append(TabCheck("Plate shear rupture", ratio(rupture.available), "J4.4"))
    else:
        out.checks.append(TabCheck("Plate shear rupture", float("inf"), "J4.4"))
        out.notes.append("The holes take the whole plate length: no net section left.")
    agv_block = (length - tab.edge_vertical) * tab.tp
    anv_block = agv_block - (n - 0.5) * (hole + hole_extra) * tab.tp
    ant_block = max(0.0, (tab.edge_horizontal - 0.5 * (hole + hole_extra)) * tab.tp)
    if anv_block > 0.0:
        block = block_shear_strength(
            fy=plate_fy,
            fu=plate_fu,
            agv=agv_block,
            anv=anv_block,
            ant=ant_block,
            method=method,  # type: ignore[arg-type]
        )
        out.checks.append(TabCheck("Plate block shear", ratio(block.available), "J4.5"))

    weld = fillet_weld_strength(
        fexx=tab.fexx,
        leg=tab.weld_leg,
        length=length,
        both_sides=True,
        method=method,  # type: ignore[arg-type]
    )
    out.checks.append(TabCheck("Fillet welds to the support", ratio(weld.available), "J2.4"))
    out.checks.append(
        TabCheck(
            "Weld detailing w >= 5/8 tp",
            0.625 * tab.tp / tab.weld_leg,
            "Manual Part 10 (plate yields first)",
        )
    )
    out.checks.append(
        TabCheck(
            "Ductility tp <= d/2 + 1/16 in",
            tab.tp / (d / 2.0 + inch / 16.0),
            "Manual Part 10, conventional configuration",
        )
    )
    if tab.weld_to_bolts > 3.5 * inch:
        out.notes.append(
            "a > 3 1/2 in: outside the conventional configuration (Manual Table 10-9); "
            "design it as an extended configuration."
        )
    return out
