"""An elastic section from a cold-formed AISI profile (Define → Cold-Formed Sections).

The geometry and the properties are :mod:`opensees_studio.core.sections.cold_formed`;
this turns them into the :class:`ElasticSection` a frame member uses, with the
orientation of an AISC shape (``core.aisc.shape_to_elastic_section``): in 2D the
strong axis is Iz, in 3D the depth stands along local z, so the strong axis is
Iy. The shear areas are the profile's, and the section is made of a material
(``core.section_materials``) — A653 SS Gr. 50 sheet when the project has it.

No Qt.
"""

from __future__ import annotations

from typing import Any

from opensees_studio.core.section_materials import linked, shear_areas
from opensees_studio.core.sections import ElasticSection
from opensees_studio.core.sections.cold_formed import ColdFormedShape, properties, scaled
from opensees_studio.core.units import UnitSystem, length_scale

#: The material a cold-formed section takes when the project has it.
COLD_FORMED_MATERIAL_NAME = "A653SSGr50"


def default_cold_formed_material(project: Any) -> Any:
    """The project's A653 SS Gr. 50 sheet, else its A572 Gr. 50, else None."""
    from opensees_studio.core.default_materials import DEFAULT_MATERIAL_NAME

    for name in (COLD_FORMED_MATERIAL_NAME, DEFAULT_MATERIAL_NAME):
        material = next((m for m in project.materials if m.name == name), None)
        if material is not None:
            return material
    return None


def in_units(shape_in_inches: ColdFormedShape, units: UnitSystem) -> ColdFormedShape:
    """A generated size (inches) in the project's ``units``."""
    return scaled(shape_in_inches, length_scale(UnitSystem.US_IN_KIP, units))


def cold_formed_section(
    shape: ColdFormedShape,
    *,
    section_id: int,
    ndm: int,
    name: str = "",
    material: Any = None,
    units: UnitSystem = UnitSystem.SI_M_N,
    elastic_modulus: float = 1.0,
    shear_modulus: float | None = None,
) -> ElasticSection:
    """The elastic section of ``shape`` (in the project's units), made of ``material``.

    Without a material the moduli are the given ones (E and G typed in).
    """
    props = properties(shape)
    iz, iy = props.Ix, props.Iy
    if ndm == 3:
        iz, iy = iy, iz
    as2, as3 = shear_areas(shape, ndm) or (0.0, 0.0)
    section = ElasticSection(
        id=section_id,
        name=name or shape.dimension_name,
        E=elastic_modulus,
        G=shear_modulus,
        A=props.A,
        Iz=iz,
        Iy=iy,
        J=props.J,
        As2=as2,
        As3=as3,
        shape=shape,
    )
    return linked(section, material, units) if material is not None else section


__all__ = [
    "COLD_FORMED_MATERIAL_NAME",
    "cold_formed_section",
    "default_cold_formed_material",
    "in_units",
]
