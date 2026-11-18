"""AISC 358-22 connections: the RBS entity and its prequalified geometry.

The entity is what a project saves; :func:`rbs_geometry` checks the dimensions
against Section 5.7 of AISC 358-22 and returns the reduced plastic modulus:

    Z_RBS = Zb - 2 c tbf (d - tbf)                       (5.7-4)
    Sh    = a + b / 2                                    (5.7-5)

with ``0.5 bbf <= a <= 0.75 bbf``, ``0.65 d <= b <= 0.85 d`` and
``0.1 bbf <= c <= 0.25 bbf`` (5.7-1 to 5.7-3). ``Mpr`` uses the expected yield
stress and the RBS modulus, and ``Mf = Mpr + Vh Sh`` projects it to the column
face. No Qt, no OpenSees.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from opensees_studio.core._base import omit_when_default
from opensees_studio.core.design.expected import cpr


class RbsConnection(BaseModel):
    """A reduced-beam-section connection of AISC 358-22 Chapter 5."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    serialize_without_defaults = omit_when_default(
        "name",
        "web_connection_type",
        "web_plate_thickness",
        "web_plate_height",
        "web_bolt_count",
        "web_bolt_diameter",
        "web_bolt_fnv",
        "web_weld_leg",
        "web_weld_fexx",
    )

    id: PositiveInt
    name: str = ""
    beam_element_id: PositiveInt
    column_element_id: PositiveInt
    a: PositiveFloat = Field(description="Face of column to the start of the cut.")
    b: PositiveFloat = Field(description="Length of the RBS cut.")
    c: PositiveFloat = Field(description="Depth of the cut at its centre.")
    web_connection_type: Literal["cjp", "bolted"] = Field(
        default="cjp",
        description="Beam web connection: CJP groove weld or bolted single plate.",
    )
    web_plate_thickness: PositiveFloat | None = Field(
        default=None, description="Single-plate thickness; None leaves 5.5 unchecked."
    )
    web_plate_height: PositiveFloat | None = Field(
        default=None, description="Plate height along the column flange."
    )
    web_bolt_count: PositiveInt | None = Field(
        default=None, description="Number of bolts in the single plate."
    )
    web_bolt_diameter: PositiveFloat | None = Field(default=None, description="Bolt diameter.")
    web_bolt_fnv: PositiveFloat | None = Field(
        default=None, description="Bolt nominal shear strength Fnv; None = 54 ksi."
    )
    web_weld_leg: PositiveFloat | None = Field(
        default=None, description="Fillet weld leg to the column flange."
    )
    web_weld_fexx: PositiveFloat | None = Field(
        default=None, description="Electrode strength Fexx; None = 70 ksi."
    )


class BeamShape(Protocol):
    """The beam properties the RBS geometry needs."""

    @property
    def d(self) -> float:
        """Beam depth."""

    @property
    def bf(self) -> float:
        """Beam flange width."""

    @property
    def tf(self) -> float:
        """Beam flange thickness."""

    @property
    def Zx(self) -> float:
        """Plastic section modulus about the major axis."""


@dataclass(frozen=True)
class RbsGeometry:
    """The checked RBS dimensions and the derived quantities."""

    a: float
    b: float
    c: float
    sh: float
    """Distance from the column face to the plastic hinge, ``a + b/2``."""
    z_rbs: float
    """Plastic modulus at the centre of the cut."""


def rbs_limits(shape: BeamShape) -> dict[str, tuple[float, float]]:
    """The 5.7-1 to 5.7-3 limits of ``a``, ``b`` and ``c`` for a beam."""
    return {
        "a": (0.5 * shape.bf, 0.75 * shape.bf),
        "b": (0.65 * shape.d, 0.85 * shape.d),
        "c": (0.1 * shape.bf, 0.25 * shape.bf),
    }


def rbs_geometry(connection: RbsConnection, shape: BeamShape) -> RbsGeometry:
    """Check the cut against Section 5.7 and return its geometry.

    Raises:
        ValueError: one of ``a``, ``b`` or ``c`` is outside its limit.
    """
    limits = rbs_limits(shape)
    for name in ("a", "b", "c"):
        value = getattr(connection, name)
        low, high = limits[name]
        if not low <= value <= high:
            raise ValueError(
                f"RBS {name} = {value:g} is outside [{low:g}, {high:g}] "
                f"for {getattr(shape, 'name', 'the beam')}."
            )
    z_rbs = shape.Zx - 2.0 * connection.c * shape.tf * (shape.d - shape.tf)
    if z_rbs <= 0.0:
        raise ValueError("The RBS cut removes the whole plastic modulus.")
    return RbsGeometry(
        a=connection.a,
        b=connection.b,
        c=connection.c,
        sh=connection.a + connection.b / 2.0,
        z_rbs=z_rbs,
    )


def rbs_mpr(
    geometry: RbsGeometry,
    *,
    ry: float,
    fy: float,
    fu: float | None = None,
) -> float:
    """Probable maximum moment at the hinge, ``Cpr Ry Fy Z_RBS`` (2.4.3)."""
    if ry <= 0.0 or fy <= 0.0:
        raise ValueError("Ry and Fy must be positive for Mpr.")
    return cpr(fy, fu) * ry * fy * geometry.z_rbs


def rbs_mf(geometry: RbsGeometry, mpr: float, vh: float) -> float:
    """Probable moment at the column face, ``Mf = Mpr + Vh Sh`` (2.4.5)."""
    return mpr + max(0.0, vh) * geometry.sh


def rbs_radius(geometry: RbsGeometry) -> float:
    """Radius of the cut, ``R = (4 c^2 + b^2) / (8 c)`` (Figure 5.1)."""
    if geometry.c <= 0.0:
        raise ValueError("The RBS cut depth c must be positive.")
    return (4.0 * geometry.c**2 + geometry.b**2) / (8.0 * geometry.c)


def rbs_protected_zone(geometry: RbsGeometry) -> tuple[float, float]:
    """The protected zone of Section 5.3.1(8), measured from the column face.

    It runs from the face of the column to the end of the cut farthest from it,
    i.e. ``a + b``.
    """
    return (0.0, geometry.a + geometry.b)


def rbs_mpe(ry: float, fy: float, zb: float) -> float:
    """5.7-6: ``Mpe = Ry Fy Zb`` with the full beam modulus."""
    if ry <= 0.0 or fy <= 0.0 or zb <= 0.0:
        raise ValueError("Ry, Fy and Zb must be positive for Mpe.")
    return ry * fy * zb


def rbs_flexure_ratio(mf: float, mpe: float, *, method: str = "LRFD") -> float:
    """5.7-7: ``Mf / (phi_d Mpe)``; ``phi_d = 1.0`` LRFD, ``1/1.5`` ASD."""
    if mpe <= 0.0:
        raise ValueError("Mpe must be positive.")
    available = mpe if method == "LRFD" else mpe / 1.5
    return mf / available
