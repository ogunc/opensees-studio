"""An elastic section takes its E, G and weight from its material, and its shear areas from its shape.

SAP2000 defines a frame section *of a material*: the modulus, the shear modulus
and the weight are the material's, and changing the material changes the
section. :class:`~opensees_studio.core.sections.ElasticSection` keeps the
numbers the analysis reads (``E``, ``G``, ``unit_weight``) and, with
``material_id`` set, they are *derived*: :func:`sync_material_links` rewrites
them from the material, and the view model calls it after every edit, undo and
redo, so a material changed in the library reaches every section made of it.

What a material gives:

* ``ElasticIsotropic`` (the default materials): ``E``; ``G = E / (2 (1 + ν))``;
  ``unit_weight = ρ g`` (its mass density times standard gravity in the
  project's units);
* ``Elastic`` (uniaxial): ``E`` only;
* ``Steel01`` / ``Steel02``: their initial modulus ``E0`` only.

A material with no modulus (a concrete model) cannot be an elastic section's
material: :func:`linkable_materials` leaves it out.

The shear areas of a shape (:func:`shear_areas`) are common approximations:
the web for shear along the depth, 5/6 of the flanges across it. They are not
yet checked against a published reference (the CSI Analysis Reference Manual
or a SAP2000 property table); the tee, angle and cold-formed values are the
least certain. A section without a
shape takes them from the user, who must give a value; 0 means rigid in shear
in that direction (no shear deformation).

No Qt.
"""

from __future__ import annotations

import math
from typing import Any

from opensees_studio.core.sections import (
    AngleShape,
    ChannelShape,
    ElasticSection,
    PipeShape,
    RectShape,
    TeeShape,
    TubeShape,
    WideFlangeShape,
)
from opensees_studio.core.units import gravity


def elastic_constants(material: Any, units: Any) -> tuple[float, float | None, float | None] | None:
    """``(E, G, unit_weight)`` an elastic section takes from ``material``.

    ``G`` and ``unit_weight`` are None when the material does not define them
    (the section keeps its own); the whole is None for a material with no
    modulus.
    """
    kind = getattr(material, "type", "")
    if kind == "ElasticIsotropic":
        e = float(material.E)
        return e, e / (2.0 * (1.0 + float(material.nu))), float(material.rho) * gravity(units)
    if kind == "Elastic":
        return float(material.E), None, None
    if kind in ("Steel01", "Steel02"):
        return float(material.E0), None, None
    return None


def linkable_materials(project: Any) -> list[Any]:
    """The project's materials an elastic section can be made of, in project order."""
    units = project.meta.units
    return [m for m in project.materials if elastic_constants(m, units) is not None]


def linked(section: ElasticSection, material: Any, units: Any) -> ElasticSection:
    """``section`` made of ``material``: its E, G and weight are the material's."""
    constants = elastic_constants(material, units)
    if constants is None:
        raise ValueError(
            f"Material {material.id} ({getattr(material, 'name', '') or material.type}) has no "
            "elastic modulus; an elastic section cannot be made of it."
        )
    e, g, weight = constants
    update: dict[str, Any] = {"material_id": material.id, "E": e}
    if g is not None:
        update["G"] = g
    if weight is not None:
        update["unit_weight"] = weight
    return section.model_copy(update=update)


def sync_material_links(project: Any) -> list[int]:
    """Rewrite every material-linked elastic section from its material, in place.

    Returns the ids of the sections that changed. A section whose material is
    missing, or has no modulus, keeps its numbers (Check Model reports the
    missing reference).
    """
    materials = {m.id: m for m in project.materials}
    units = project.meta.units
    changed: list[int] = []
    for index, section in enumerate(project.sections):
        if not isinstance(section, ElasticSection) or section.material_id is None:
            continue
        material = materials.get(section.material_id)
        if material is None or elastic_constants(material, units) is None:
            continue
        updated = linked(section, material, units)
        if updated != section:
            project.sections[index] = updated
            changed.append(section.id)
    return changed


def _depth_and_width_areas(shape: Any) -> tuple[float, float] | None:
    """Shear areas for shear along the shape's depth and across it (approximations)."""
    if isinstance(shape, RectShape):
        area = 5.0 / 6.0 * shape.d * shape.b
        return area, area
    if isinstance(shape, PipeShape):
        r_o, r_i = shape.od / 2.0, max(shape.od / 2.0 - shape.t, 0.0)
        half = math.pi * (r_o**2 - r_i**2) / 2.0
        return half, half
    if isinstance(shape, TubeShape):
        return 2.0 * shape.d * shape.t, 2.0 * shape.b * shape.t
    if isinstance(shape, WideFlangeShape | ChannelShape):
        return shape.d * shape.tw, 5.0 / 3.0 * shape.bf * shape.tf
    if isinstance(shape, TeeShape):
        return shape.d * shape.tw, 5.0 / 6.0 * shape.bf * shape.tf
    if isinstance(shape, AngleShape):
        return 5.0 / 6.0 * shape.d * shape.t, 5.0 / 6.0 * shape.b * shape.t
    cold_formed = getattr(shape, "shear_areas", None)
    if callable(cold_formed):
        return cold_formed()  # type: ignore[no-any-return]
    return None


def shear_areas(shape: Any, ndm: int) -> tuple[float, float] | None:
    """``(As2, As3)`` of a shape in the project's local axes, or None for no shape.

    The shape's depth stands along local y in a 2D model and along local z in a
    3D one (``core.sections`` shapes), so the web's area is As2 in 2D and As3
    in 3D.
    """
    areas = _depth_and_width_areas(shape)
    if areas is None:
        return None
    depth, width = areas
    return (depth, width) if ndm == 2 else (width, depth)


def with_shear_areas(section: ElasticSection, ndm: int) -> ElasticSection:
    """``section`` with the shear areas of its shape; unchanged when it has no shape."""
    areas = shear_areas(section.shape, ndm) if section.shape is not None else None
    if areas is None:
        return section
    return section.model_copy(update={"As2": areas[0], "As3": areas[1]})


def frames_with_non_uniform_loads(project: Any) -> set[int]:
    """Members carrying a point, partial or varying load in any load pattern.

    OpenSees 3.8's ``ElasticTimoshenkoBeam`` takes only full-length uniform
    loads (and self weight), and PyNite has no shear deformation at all; such a
    member is therefore analysed with As2 = As3 = 0 (Euler-Bernoulli) and the
    run says so. The frame loads an area or floor load becomes count too.
    """
    from opensees_studio.core.area_loads import AreaLoadError, pattern_distributed_loads
    from opensees_studio.core.loads import PlainLoadPattern

    eps = 1e-9
    found: set[int] = set()
    for pattern in project.load_patterns:
        if not isinstance(pattern, PlainLoadPattern):
            continue
        found.update(load.element_id for load in pattern.point_loads)
        try:
            distributed = pattern_distributed_loads(project, pattern)
        except AreaLoadError:
            distributed = list(pattern.distributed_loads)
        for load in distributed:
            uniform = (
                abs(load.x_start) <= eps
                and abs(load.x_end - 1.0) <= eps
                and math.isclose(load.wx_start, load.wx_end)
                and math.isclose(load.wy_start, load.wy_end)
                and math.isclose(load.wz_start, load.wz_end)
            )
            if not uniform:
                found.add(load.element_id)
    return found


def shear_dropped_note(element_ids: list[int]) -> str:
    """The run's warning for the members analysed with As2 = As3 = 0."""
    ids = sorted(set(element_ids))
    listed = ", ".join(str(i) for i in ids[:20]) + (
        f" … ({len(ids)} in all)" if len(ids) > 20 else ""
    )
    return (
        f"Element(s) {listed}: the section has shear areas, but the member carries a point, "
        "partial or varying load, which a Timoshenko beam cannot take; it was analysed "
        "with As2 = As3 = 0 (no shear deformation)."
    )


__all__ = [
    "elastic_constants",
    "frames_with_non_uniform_loads",
    "linkable_materials",
    "linked",
    "shear_areas",
    "shear_dropped_note",
    "sync_material_links",
    "with_shear_areas",
]
